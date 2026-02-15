#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2022 OzzieIsaacs
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# ─────────────────────────────────────────────────────────────────────────────
#  PATCH: Navbar dil seçici için session/cookie desteği eklendi.
#  Tüm orijinal export'lar korundu:
#    babel, get_locale, get_available_locale,
#    get_available_translations, get_user_locale_language
# ─────────────────────────────────────────────────────────────────────────────

import os

from flask import request, session as flask_session
from flask_babel import Babel

from . import logger

log = logger.create()

# ── babel nesnesi — __init__.py tarafından import edilir ──────────────────────
babel = Babel()

# Navbar dil seçicisinin kabul ettiği locale kodları
_NAV_LOCALES = {"en", "tr", "ru", "uk"}

# translations/ dizini
_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), "translations")


# ── Locale seçici ─────────────────────────────────────────────────────────────
def get_locale():
    """
    Flask-Babel locale selector.
    Öncelik: DB > session > cookie > Accept-Language > site varsayılanı
    """
    from .cw_login import current_user
    from . import config

    # 1. Giriş yapmış kullanıcının DB tercihi
    try:
        if current_user and current_user.is_authenticated and not current_user.is_anonymous:
            lc = getattr(current_user, "locale", None)
            if lc:
                return lc
    except Exception:
        pass

    # 2. Navbar dil seçicisinden gelen session [PATCH]
    lc = flask_session.get("locale")
    if lc and lc in _NAV_LOCALES:
        return lc

    # 3. Cookie (anonim kullanıcı kalıcı tercihi) [PATCH]
    lc = request.cookies.get("locale")
    if lc and lc in _NAV_LOCALES:
        return lc

    # 4. Tarayıcı Accept-Language
    best = request.accept_languages.best_match(
        [str(loc) for loc in get_available_locale()]
    )
    if best:
        return best

    # 5. Site varsayılan locale
    try:
        return config.config_default_locale
    except Exception:
        return "en"


# ── Mevcut çeviri dosyalarını listele (Locale nesneleri) ──────────────────────
def get_available_locale():
    """
    translations/ içindeki .mo dosyalarını tarar.
    web.py ve profil sayfası tarafından kullanılır.
    Döner: [babel.Locale, ...]
    """
    from babel import Locale, UnknownLocaleError

    locales = []
    if os.path.isdir(_TRANSLATIONS_DIR):
        for name in sorted(os.listdir(_TRANSLATIONS_DIR)):
            mo_file = os.path.join(
                _TRANSLATIONS_DIR, name, "LC_MESSAGES", "messages.mo"
            )
            if os.path.isfile(mo_file):
                try:
                    locales.append(Locale.parse(name))
                except (UnknownLocaleError, ValueError):
                    pass

    # İngilizce kaynak dil her zaman dahil
    if not any(str(lc) == "en" for lc in locales):
        try:
            locales.insert(0, Locale.parse("en"))
        except Exception:
            pass

    return locales


# ── Mevcut çevirileri dict olarak döndür ──────────────────────────────────────
def get_available_translations():
    """
    admin.py tarafından kullanılır.
    translations/ içindeki her dil için {'locale': str, 'name': str} dict'i döner.
    Döner: [{'locale': 'en', 'name': 'English'}, ...]
    """
    from babel import Locale, UnknownLocaleError

    translations = []
    if os.path.isdir(_TRANSLATIONS_DIR):
        for name in sorted(os.listdir(_TRANSLATIONS_DIR)):
            mo_file = os.path.join(
                _TRANSLATIONS_DIR, name, "LC_MESSAGES", "messages.mo"
            )
            if os.path.isfile(mo_file):
                try:
                    loc  = Locale.parse(name)
                    translations.append({
                        "locale": str(loc),
                        "name":   loc.get_display_name(loc)
                    })
                except (UnknownLocaleError, ValueError):
                    pass

    # İngilizce her zaman dahil
    if not any(t["locale"] == "en" for t in translations):
        try:
            loc = Locale.parse("en")
            translations.insert(0, {
                "locale": "en",
                "name":   loc.get_display_name(loc)
            })
        except Exception:
            pass

    return translations


# ── Kullanıcının mevcut locale'ini insan okunabilir ad olarak döndür ──────────
def get_user_locale_language(user_locale):
    """
    admin.py tarafından kullanılır.
    Verilen locale kodunun o dildeki adını döndürür.
    Örnek: 'tr' → 'Türkçe', 'ru' → 'Русский', 'uk' → 'Українська'
    Locale bulunamazsa locale kodunu olduğu gibi döndürür.
    """
    from babel import Locale, UnknownLocaleError

    if not user_locale:
        return "English"
    try:
        loc = Locale.parse(user_locale)
        return loc.get_display_name(loc)
    except (UnknownLocaleError, ValueError):
        return user_locale