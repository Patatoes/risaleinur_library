function getCurrentBookId() {
    return parseInt(window.location.pathname.match(/\/read\/(\d+)/)?.[1] || 0);
}

class BookEpubTracker {
    constructor() {
        this.storage = window.createStorage('book-tracker');
        this.bookId = getCurrentBookId();
        this.init();
    }

    async init() {
        this.cfi = await this.getLastCfi();
        await this.storage.init('book-tracker');
        const th = this;
        function checkURLchange() {
            if (window.location.href != oldURL) {
                console.log('change');
                console.log(window.location.href);
                oldURL = window.location.href;
                th.trackCfi()
            }
        }

        var oldURL = window.location.href;
        setInterval(checkURLchange, 50);

        if (this.cfi) {
            this.checkAndResume()
        } else {
            this.trackCfi()
        }

    }

    // Compare current CFI vs stored → resume only if different
    async checkAndResume() {
        // Skip if same position OR no current CFI yet
        if (this.cfi === window.location.hash.match(/epubcfi\((.*?)\)/)?.[1]) {
            console.log(`Book ${this.bookId}: already at correct position`);
            return;
        }

        console.log(`Book ${this.bookId}: not correct position`);
        this.resumeToStoredCfi();
    }

    resumeToStoredCfi() {
        console.log(`Resumed book ${this.bookId}: ${this.cfi.slice(0, 40)}...`);
        window.location.hash = `#epubcfi(${this.cfi})`
    }

    async trackCfi() {
        this.cfi = window.location.hash.match(/epubcfi\((.*?)\)/)?.[1]
        const key = `last_page_${this.bookId}`;
        await this.storage.set(key, this.cfi);
    }

    async getLastCfi() {
        const key = `last_page_${this.bookId}`;
        return await this.storage.get(key);
    }
}

// Auto-init on reader pages
if (window.location.pathname.startsWith('/read/')) {
    // TODO add check for extension
    window.bookTracker = new BookEpubTracker();
}
