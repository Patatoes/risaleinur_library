/**
 * Calibre-Web Guest Reading Tracker
 * 
 * This module handles reading history for anonymous (guest) users using browser localStorage.
 * It tracks recently opened books and displays them on the index page.
 * 
 * Features:
 * - Automatically saves book metadata when a guest user opens a book
 * - Displays up to 10 most recently read books on the homepage
 * - Deduplicates entries (same book moves to top)
 * - Works independently of server-side bookmark system
 * - Gracefully degrades if localStorage is unavailable
 * 
 * Usage:
 * 1. Include this script in read.html to track book opens
 * 2. Include this script in index.html to display recent books
 * 
 * localStorage key: 'calibre_guest_recent_books'
 * Data format: Array of {id, title, author, timestamp}
 */

(function() {
  'use strict';

  var STORAGE_KEY = 'calibre_guest_recent_books';
  var MAX_BOOKS = 10;

  /**
   * Check if user is authenticated
   * @returns {boolean}
   */
  function isGuest() {
    // This will be replaced by template engine: {{ 'true' if not current_user.is_authenticated else 'false' }}
    return window.CALIBRE_IS_GUEST === true;
  }

  /**
   * Safely get data from localStorage
   * @returns {Array}
   */
  function getStoredBooks() {
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch (e) {
      console.warn('Failed to read from localStorage:', e);
      return [];
    }
  }

  /**
   * Safely save data to localStorage
   * @param {Array} books
   */
  function saveBooks(books) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(books));
    } catch (e) {
      console.warn('Failed to save to localStorage:', e);
    }
  }

  /**
   * Track a book when user opens it
   * Called from read.html
   * @param {Object} bookData - {id, title, author}
   */
  function trackBookOpen(bookData) {
    if (!isGuest()) return;
    if (!bookData || !bookData.id) return;

    var recentBooks = getStoredBooks();

    // Add timestamp
    bookData.timestamp = Date.now();

    // Remove if already exists (to move to top)
    recentBooks = recentBooks.filter(function(b) { 
      return b.id !== bookData.id; 
    });

    // Add to beginning
    recentBooks.unshift(bookData);

    // Keep only max books
    if (recentBooks.length > MAX_BOOKS) {
      recentBooks = recentBooks.slice(0, MAX_BOOKS);
    }

    saveBooks(recentBooks);
  }

  /**
   * Display recent books on index page
   * Called from index.html
   */
  function displayRecentBooks() {
    if (!isGuest()) return;

    var recentBooks = getStoredBooks();
    if (recentBooks.length === 0) return;

    var container = document.getElementById('guest-books-container');
    if (!container) return;

    // Show the section
    var section = document.getElementById('guest-last-read');
    if (section) {
      section.style.display = 'block';
    }

    // Clear existing content
    container.innerHTML = '';

    // Create book cards
    recentBooks.forEach(function(book) {
      var div = document.createElement('div');
      div.className = 'col-sm-3 col-lg-2 col-xs-6 book session';
      
      var title = book.title || 'Unknown';
      var titleShort = title.length > 40 ? title.substring(0, 40) + '...' : title;
      var author = book.author || '';
      
      div.innerHTML = 
        '<div class="cover">' +
          '<a href="/book/' + book.id + '">' +
            '<span class="img" title="' + escapeHtml(title) + '">' +
              '<img src="/cover/' + book.id + '" alt="' + escapeHtml(title) + '">' +
            '</span>' +
          '</a>' +
        '</div>' +
        '<div class="meta">' +
          '<a href="/book/' + book.id + '">' +
            '<p title="' + escapeHtml(title) + '" class="title">' + escapeHtml(titleShort) + '</p>' +
          '</a>' +
          '<p class="author">' + escapeHtml(author) + '</p>' +
        '</div>';
      
      container.appendChild(div);
    });
  }

  /**
   * Escape HTML to prevent XSS
   * @param {string} text
   * @returns {string}
   */
  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Clear all guest reading history
   * Useful for privacy/testing
   */
  function clearHistory() {
    try {
      localStorage.removeItem(STORAGE_KEY);
      console.log('Guest reading history cleared');
    } catch (e) {
      console.warn('Failed to clear history:', e);
    }
  }

  // Public API
  window.CalibreGuestTracker = {
    trackBookOpen: trackBookOpen,
    displayRecentBooks: displayRecentBooks,
    clearHistory: clearHistory,
    getStoredBooks: getStoredBooks
  };

  // Auto-initialize display if on index page
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', displayRecentBooks);
  } else {
    displayRecentBooks();
  }

})();
