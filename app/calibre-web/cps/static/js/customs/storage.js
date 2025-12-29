// storage.js - Prefix-aware IndexedDB service
class CalibreStorage {
    constructor() {
        this.dbName = 'calibre-reader';
        this.version = 3;
        this.storeName = 'reader-state';
        this.db = null;
        this.prefix = null;  // Set during init('prefix')
    }

    // Initialize with prefix (e.g. 'book-tracker', 'user-settings')
    async init(storagePrefix = 'default') {
        this.prefix = storagePrefix;

        if (this.db) return this.db;

        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.version);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                this.db = request.result;
                resolve(this.db);
            };

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                let store;
                if (!db.objectStoreNames.contains(this.storeName)) {
                    store = db.createObjectStore(this.storeName, { keyPath: 'key' });
                } else {
                    store = event.target.transaction.objectStore(this.storeName);
                }
                if (!store.indexNames.contains('bookId')) {
                    store.createIndex('bookId', 'bookId', { unique: false });
                }
            };
        });
    }

    // Generate prefixed key
    getPrefixedKey(baseKey) {
        return `${this.prefix}:${baseKey}`;
    }

    // Store with prefix (e.g. "book-tracker:last_page_123")
    async set(key, value) {
        await this.init();

        const prefixedKey = this.getPrefixedKey(key);
        const record = {
            key: prefixedKey,
            value: value,
            timestamp: Date.now()
        };

        const tx = this.db.transaction([this.storeName], 'readwrite');
        const store = tx.objectStore(this.storeName);
        const request = store.put(record);

        return new Promise((resolve, reject) => {
            request.onsuccess = () => resolve(record);
            request.onerror = () => reject(request.error);
        });
    }

    // Get with prefix
    async get(key) {
        await this.init();

        const prefixedKey = this.getPrefixedKey(key);
        const tx = this.db.transaction([this.storeName], 'readonly');
        const store = tx.objectStore(this.storeName);
        const request = store.get(prefixedKey);

        return new Promise((resolve) => {
            request.onsuccess = () => resolve(request.result?.value || null);
            request.onerror = () => resolve(null);
        });
    }

    // Get all keys for prefix (for debugging)
    async getAllForPrefix() {
        await this.init();
        const tx = this.db.transaction([this.storeName], 'readonly');
        const store = tx.objectStore(this.storeName);
        const request = store.getAll();

        return new Promise((resolve) => {
            request.onsuccess = () => {
                resolve(request.result
                    .filter(item => item.key.startsWith(`${this.prefix}:`))
                    .map(item => ({ key: item.key.replace(`${this.prefix}:`, ''), value: item.value })));
            };
        });
    }
}

// Factory function creates isolated instances
window.createStorage = (prefix) => {
    const storage = new CalibreStorage();
    storage.init(prefix);  // Auto-init with prefix
    return storage;
};
