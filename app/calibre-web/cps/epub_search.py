#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#  Full-text EPUB search — optimize edilmiş versiyon
#
#  Özellikler:
#    • lxml parser      — BeautifulSoup html.parser'dan ~5x hızlı
#    • Paralel parse    — ThreadPoolExecutor ile EPUB'lar eş zamanlı taranır
#    • SQLite FTS5      — tek seferlik indeks, aramalar milisaniyeler içinde
#    • Startup worker   — uygulama açılırken indeks arka planda hazırlanır
#    • Otomatik güncelleme — kitap eklenince sadece o kitap yeniden indekslenir
#
#  Gerekli paketler:
#    pip install beautifulsoup4 lxml
#
#  İndeks dosyası: <calibre_dir>/fts_index.db

import os
import re
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import logger

log = logger.create()

# ── Parser seçimi: lxml varsa kullan (5x hız), yoksa html.parser'a dön ──
try:
    from bs4 import BeautifulSoup
    import lxml  # noqa
    _PARSER        = "lxml"
    _BS4_AVAILABLE = True
    log.debug("FTS: using lxml parser")
except ImportError:
    try:
        from bs4 import BeautifulSoup
        _PARSER        = "html.parser"
        _BS4_AVAILABLE = True
        log.warning("FTS: lxml not found, using html.parser. "
                    "Run: pip install lxml  for faster indexing.")
    except ImportError:
        _BS4_AVAILABLE = False
        log.warning("FTS: BeautifulSoup4 not installed. Run: pip install beautifulsoup4 lxml")

_INDEX_WORKERS = 4      # paralel parse thread sayısı (100 kitap için ideal)
_startup_thread = None
_startup_lock   = threading.Lock()


# ═══════════════════════════════════════════════════════════
# İNDEKS VERİTABANI
# ═══════════════════════════════════════════════════════════

def _index_path(calibre_dir):
    return os.path.join(calibre_dir, "fts_index.db")


def _open_index(calibre_dir):
    """FTS5 veritabanını aç, tablolar yoksa oluştur."""
    conn = sqlite3.connect(_index_path(calibre_dir), timeout=60,
                           check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS book_paragraphs (
            book_id       INTEGER NOT NULL,
            epub_mtime    REAL    NOT NULL,
            chapter_href  TEXT    NOT NULL,
            chapter_title TEXT    NOT NULL,
            para_index    INTEGER NOT NULL,
            para_text     TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bp_book_id ON book_paragraphs(book_id)
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts5_idx
        USING fts5(
            book_id       UNINDEXED,
            chapter_href  UNINDEXED,
            chapter_title UNINDEXED,
            para_index    UNINDEXED,
            para_text,
            content='book_paragraphs',
            content_rowid='rowid',
            tokenize='unicode61'
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS bp_ai AFTER INSERT ON book_paragraphs BEGIN
            INSERT INTO fts5_idx(rowid, book_id, chapter_href, chapter_title,
                                 para_index, para_text)
            VALUES (new.rowid, new.book_id, new.chapter_href, new.chapter_title,
                    new.para_index, new.para_text);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS bp_ad AFTER DELETE ON book_paragraphs BEGIN
            INSERT INTO fts5_idx(fts5_idx, rowid, book_id, chapter_href, chapter_title,
                                 para_index, para_text)
            VALUES ('delete', old.rowid, old.book_id, old.chapter_href,
                    old.chapter_title, old.para_index, old.para_text);
        END
    """)
    conn.commit()
    return conn


def _book_is_current(conn, book_id, epub_mtime):
    row = conn.execute(
        "SELECT epub_mtime FROM book_paragraphs WHERE book_id=? LIMIT 1",
        (book_id,)
    ).fetchone()
    return row is not None and float(row[0]) >= epub_mtime


def _remove_book(conn, book_id):
    conn.execute("DELETE FROM book_paragraphs WHERE book_id=?", (book_id,))
    conn.commit()


def _write_paragraphs(conn, book_id, epub_mtime, chapters):
    """Parse sonuçlarını veritabanına yaz — her zaman tek thread'den çağrılır."""
    rows = []
    seen = set()
    for ch in chapters:
        for para in ch["paragraphs"]:
            key = para["text"][:200]
            if key in seen:
                continue
            seen.add(key)
            rows.append((book_id, epub_mtime,
                         ch["href"], ch["title"],
                         para["index"], para["text"]))
    if rows:
        conn.executemany(
            """INSERT INTO book_paragraphs
               (book_id, epub_mtime, chapter_href, chapter_title, para_index, para_text)
               VALUES (?,?,?,?,?,?)""",
            rows
        )
        conn.commit()
    return len(rows)


# ═══════════════════════════════════════════════════════════
# EPUB AYRIŞTIRICISI
# ═══════════════════════════════════════════════════════════

def _get_epub_path(calibre_dir, book):
    for data in book.data:
        if data.format.upper() == "EPUB":
            return os.path.join(calibre_dir, book.path, data.name + ".epub")
    return None


def _parse_epub(epub_path):
    """
    EPUB'ı ayrıştır:
    • lxml ile hızlı HTML parse
    • chapter_title: h1 > h2 > h3 > h4 > <title> > dosya adı
    • Sadece leaf-level <p> ve <li> (tekrar sorunu çözüldü)
    """
    chapters = []
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            names = set(zf.namelist())

            opf_path, opf_dir = None, ""
            for n in zf.namelist():
                if n.endswith(".opf"):
                    opf_path, opf_dir = n, os.path.dirname(n)
                    break

            spine_hrefs = []
            if opf_path:
                try:
                    opf_soup = BeautifulSoup(
                        zf.read(opf_path).decode("utf-8", errors="replace"),
                        _PARSER
                    )
                    manifest = {}
                    for item in opf_soup.find_all("item"):
                        mt   = item.get("media-type", "")
                        href = item.get("href", "")
                        if "html" in mt or href.endswith((".html", ".xhtml", ".htm")):
                            manifest[item.get("id", "")] = href
                    for ref in opf_soup.find_all("itemref"):
                        idref = ref.get("idref", "")
                        if idref in manifest:
                            spine_hrefs.append(manifest[idref])
                except Exception as e:
                    log.debug("OPF parse error %s: %s", epub_path, e)

            if not spine_hrefs:
                spine_hrefs = [n for n in zf.namelist()
                               if n.endswith((".html", ".xhtml", ".htm"))]

            for href in spine_hrefs:
                full   = (opf_dir + "/" + href).lstrip("/").replace("\\", "/") \
                         if opf_dir else href
                actual = full if full in names else (href if href in names else None)
                if not actual:
                    continue
                try:
                    raw = zf.read(actual).decode("utf-8", errors="replace")
                except Exception:
                    continue

                soup = BeautifulSoup(raw, _PARSER)

                chapter_title = None
                for tag in ("h1", "h2", "h3", "h4"):
                    el = soup.find(tag)
                    if el:
                        t = el.get_text(strip=True)
                        if t:
                            chapter_title = t
                            break
                if not chapter_title:
                    tel = soup.find("title")
                    if tel:
                        t = tel.get_text(strip=True)
                        if " - " in t:
                            t = t.rsplit(" - ", 1)[-1].strip()
                        if t:
                            chapter_title = t
                if not chapter_title:
                    chapter_title = os.path.splitext(os.path.basename(href))[0]

                paragraphs = []
                para_idx   = 0
                for tag in soup.find_all(["p", "li"]):
                    if tag.find(["p", "li"]):
                        continue
                    text = tag.get_text(separator=" ", strip=True)
                    if len(text) < 30:
                        continue
                    paragraphs.append({"index": para_idx, "text": text})
                    para_idx += 1

                chapters.append({"href": actual, "title": chapter_title,
                                 "paragraphs": paragraphs})

    except Exception as e:
        log.warning("Could not parse EPUB %s: %s", epub_path, e)

    return chapters


# ═══════════════════════════════════════════════════════════
# PARALEL İNDEKSLEME
# ═══════════════════════════════════════════════════════════

def _index_books(conn, books_to_index, calibre_dir):
    """
    books_to_index: [(book_id, epub_mtime, epub_path), ...]

    Strateji:
    • Parse işleri ThreadPoolExecutor ile paralel (CPU/IO yoğun kısım)
    • SQLite yazma tek thread'den sıralı (WAL modunda okuma etkilenmez)

    100 kitap tahmini süre:
      html.parser sıralı  → ~120 sn
      lxml sıralı         → ~25 sn
      lxml + 4 worker     → ~8-10 sn
    """
    if not books_to_index:
        return

    log.info("FTS: indexing %d book(s) [workers=%d, parser=%s]",
             len(books_to_index), _INDEX_WORKERS, _PARSER)

    parse_results = {}
    with ThreadPoolExecutor(max_workers=_INDEX_WORKERS) as ex:
        future_map = {
            ex.submit(_parse_epub, epub_path): (book_id, epub_mtime)
            for book_id, epub_mtime, epub_path in books_to_index
        }
        for future in as_completed(future_map):
            book_id, epub_mtime = future_map[future]
            try:
                parse_results[book_id] = (epub_mtime, future.result())
            except Exception as e:
                log.warning("FTS: parse failed book %s: %s", book_id, e)

    total = 0
    for book_id, _, __ in books_to_index:
        if book_id not in parse_results:
            continue
        epub_mtime, chapters = parse_results[book_id]
        _remove_book(conn, book_id)
        n     = _write_paragraphs(conn, book_id, epub_mtime, chapters)
        total += n
        log.debug("FTS: book %s → %d paragraphs", book_id, n)

    log.info("FTS: done — %d total paragraphs", total)


# ═══════════════════════════════════════════════════════════
# STARTUP WORKER
# ═══════════════════════════════════════════════════════════

def start_background_indexing(calibre_dir, calibre_db_instance):
    """
    Calibre-Web açılırken çağrılır, indeksi arka planda hazırlar.
    Kullanıcı arama yapabilir — mevcut indeksten anlık sonuç gelir.

    cps/__init__.py veya cps/web.py içine ekle:
    ─────────────────────────────────────────────
    from . import epub_search, config
    epub_search.start_background_indexing(
        config.get_content_path(), calibre_db)
    ─────────────────────────────────────────────
    """
    global _startup_thread
    with _startup_lock:
        if _startup_thread and _startup_thread.is_alive():
            return

        def _worker():
            if not _BS4_AVAILABLE:
                return
            try:
                from . import db
                conn  = _open_index(calibre_dir)
                books = (calibre_db_instance.session.query(db.Books)
                         .join(db.Data)
                         .filter(db.Data.format == "EPUB")
                         .all())
                pending = []
                for book in books:
                    ep = _get_epub_path(calibre_dir, book)
                    if not ep or not os.path.exists(ep):
                        continue
                    mt = os.path.getmtime(ep)
                    if not _book_is_current(conn, book.id, mt):
                        pending.append((book.id, mt, ep))
                if pending:
                    _index_books(conn, pending, calibre_dir)
                else:
                    log.info("FTS startup: index already up to date")
                conn.close()
            except Exception as e:
                log.error("FTS startup worker error: %s", e)

        _startup_thread = threading.Thread(target=_worker, daemon=True,
                                           name="fts-startup")
        _startup_thread.start()
        log.info("FTS: background indexing started (daemon thread)")


def index_single_book(calibre_dir, book, force=False):
    """
    Tek kitabı indeksle — kitap yüklenince çağrılır.

    Upload route'una ekle (cps/editbooks.py vb.):
    ──────────────────────────────────────────────
    from . import epub_search, config
    epub_search.index_single_book(config.get_content_path(), book)
    ──────────────────────────────────────────────
    """
    if not _BS4_AVAILABLE:
        return
    ep = _get_epub_path(calibre_dir, book)
    if not ep or not os.path.exists(ep):
        return
    mt   = os.path.getmtime(ep)
    conn = _open_index(calibre_dir)
    if not force and _book_is_current(conn, book.id, mt):
        conn.close()
        return

    def _worker():
        try:
            chapters = _parse_epub(ep)
            _remove_book(conn, book.id)
            _write_paragraphs(conn, book.id, mt, chapters)
            conn.close()
            log.info("FTS: indexed book %s '%s'", book.id, book.title)
        except Exception as e:
            log.error("FTS single index error book %s: %s", book.id, e)
            conn.close()

    threading.Thread(target=_worker, daemon=True,
                     name="fts-single-%s" % book.id).start()


# ═══════════════════════════════════════════════════════════
# SNIPPET & VURGULAMA
# ═══════════════════════════════════════════════════════════

def _make_snippet(text, words, context=140):
    tl  = text.lower()
    pos = next((tl.find(w) for w in words if tl.find(w) != -1), 0)

    start  = max(0, pos - context // 2)
    end    = min(len(text), pos + context)
    chunk  = text[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""

    pattern = "|".join(re.escape(w) for w in words)
    hl      = re.sub(pattern,
                     lambda m: "<mark>" + m.group(0) + "</mark>",
                     chunk, flags=re.IGNORECASE)
    return prefix + hl + suffix


# ═══════════════════════════════════════════════════════════
# ANA ARAMA FONKSİYONU
# ═══════════════════════════════════════════════════════════

def search_in_epubs(term, calibre_dir, calibre_db_instance):
    """
    FTS5 ile tam metin arama.
    • Startup worker indeksi hazırlamışsa: < 100 ms
    • Henüz bitmemişse: eksik kitaplar burada paralel tamamlanır
    """
    if not _BS4_AVAILABLE:
        return [], 0

    from . import db

    conn  = _open_index(calibre_dir)
    books = (calibre_db_instance.session.query(db.Books)
             .join(db.Data)
             .filter(db.Data.format == "EPUB")
             .filter(calibre_db_instance.common_filters())
             .all())
    book_map = {b.id: b for b in books}

    # Startup worker bitmemişse eksik kitapları burada tamamla
    pending = []
    for book in books:
        ep = _get_epub_path(calibre_dir, book)
        if not ep or not os.path.exists(ep):
            continue
        mt = os.path.getmtime(ep)
        if not _book_is_current(conn, book.id, mt):
            pending.append((book.id, mt, ep))
    if pending:
        _index_books(conn, pending, calibre_dir)

    # FTS5 sorgusu
    words = [w.lower() for w in term.strip().split() if w]
    if not words:
        conn.close()
        return [], 0

    fts_query = " AND ".join('"' + w + '"' for w in words)
    try:
        rows = conn.execute("""
            SELECT bp.book_id, bp.chapter_href, bp.chapter_title,
                   bp.para_index, bp.para_text
            FROM   fts5_idx fts
            JOIN   book_paragraphs bp ON fts.rowid = bp.rowid
            WHERE  fts5_idx MATCH ?
            ORDER  BY bp.book_id, bp.para_index
        """, (fts_query,)).fetchall()
    except sqlite3.OperationalError as e:
        log.error("FTS5 query error: %s", e)
        conn.close()
        return [], 0

    conn.close()

    if not rows:
        return [], 0

    grouped = {}
    for book_id, ch_href, ch_title, para_idx, para_text in rows:
        grouped.setdefault(book_id, []).append({
            "chapter_href":  ch_href,
            "chapter_title": ch_title,
            "para_index":    para_idx,
            "snippet":       _make_snippet(para_text, words)
        })

    results, total_hits = [], 0
    for book_id, hits in grouped.items():
        book = book_map.get(book_id)
        if not book:
            continue
        total_hits += len(hits)
        results.append({
            "book":       book,
            "book_id":    book_id,
            "book_title": book.title,
            "authors":    ", ".join(a.name for a in book.authors),
            "hit_count":  len(hits),
            "hits":       hits,
        })

    results.sort(key=lambda r: r["hit_count"], reverse=True)
    return results, total_hits


def rebuild_index(calibre_dir, calibre_db_instance):
    """İndeksi sıfırdan yeniden oluştur."""
    from . import db
    path = _index_path(calibre_dir)
    if os.path.exists(path):
        os.remove(path)
    conn  = _open_index(calibre_dir)
    books = (calibre_db_instance.session.query(db.Books)
             .join(db.Data).filter(db.Data.format == "EPUB").all())
    pending = []
    for b in books:
        ep = _get_epub_path(calibre_dir, b)
        if ep and os.path.exists(ep):
            pending.append((b.id, os.path.getmtime(ep), ep))
    _index_books(conn, pending, calibre_dir)
    conn.close()
    log.info("FTS index rebuilt: %d books", len(pending))