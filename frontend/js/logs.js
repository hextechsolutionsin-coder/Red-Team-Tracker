/**
 * logs.js — Operator log page logic for RedBoard.
 *
 * Renders a paginated, filterable table of operator audit-log entries.
 *
 * Features
 * --------
 * - Paginated table: action_type, actor, description, timestamp columns.
 * - Filter inputs: engagement_id (UUID), actor username, action_type (select).
 * - Default sort: newest-first (desc). Ascending toggle button.
 * - "Apply Filters" button triggers a fresh fetch from page 1.
 * - "Clear" button resets filters and re-fetches.
 *
 * API: GET /api/v1/logs?engagement_id=&actor=&action_type=&sort=asc|desc&page=&page_size=
 *
 * Requirements: 7.5, 7.6
 *
 * Depends on: api.js (apiFetch, AppError), auth.js (requireRole)
 */

'use strict';

(function () {

  // ── Constants ───────────────────────────────────────────────────────────
  const PAGE_SIZE = 50;

  // ── State ───────────────────────────────────────────────────────────────
  let currentPage  = 1;
  let sortDir      = 'desc';   // 'asc' | 'desc'
  let activeFilter = {};       // { engagement_id?, actor?, action_type? }

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const filterForm        = document.getElementById('filter-form');
  const filterEngagement  = document.getElementById('filter-engagement');
  const filterActor       = document.getElementById('filter-actor');
  const filterActionType  = document.getElementById('filter-action-type');
  const applyFiltersBtn   = document.getElementById('apply-filters-btn');
  const clearFiltersBtn   = document.getElementById('clear-filters-btn');
  const sortToggleBtn     = document.getElementById('sort-toggle-btn');
  const sortIcon          = document.getElementById('sort-icon');
  const sortLabel         = document.getElementById('sort-label');

  const errorRow   = document.getElementById('error-row');
  const errorMsg   = document.getElementById('error-msg');
  const loadingRow = document.getElementById('loading-row');
  const emptyRow   = document.getElementById('empty-row');
  const tableWrapper = document.getElementById('table-wrapper');
  const logTbody   = document.getElementById('log-tbody');
  const resultCount = document.getElementById('result-count');

  const pageInfo      = document.getElementById('page-info');
  const paginationUl  = document.getElementById('pagination-ul');

  const usernameDisplay = document.getElementById('username-display');
  const navUsers        = document.getElementById('nav-users');
  const logoutBtn       = document.getElementById('logout-btn');

  // ── Boot ─────────────────────────────────────────────────────────────────

  /**
   * Initialise the page: enforce auth (lead/admin only), populate the username
   * in the navbar, hide the Users link for non-admins, and load the first page.
   */
  function init() {
    const user = requireRole('lead', 'admin');

    // Navbar decoration
    usernameDisplay.textContent = user.username;
    if (user.role !== 'admin') {
      navUsers.classList.add('hidden');
    }

    // Logout
    logoutBtn.addEventListener('click', function (e) {
      e.preventDefault();
      logout();
    });

    // Filter form — "Apply Filters" button
    filterForm.addEventListener('submit', function (e) {
      e.preventDefault();
      applyFilters();
    });

    // Clear button
    clearFiltersBtn.addEventListener('click', function () {
      filterEngagement.value = '';
      filterActor.value      = '';
      filterActionType.value = '';
      applyFilters();
    });

    // Sort toggle
    sortToggleBtn.addEventListener('click', function () {
      sortDir = (sortDir === 'desc') ? 'asc' : 'desc';
      updateSortUI();
      // Re-fetch current filters with new sort direction from page 1
      currentPage = 1;
      fetchLogs();
    });

    // Load initial data
    fetchLogs();
  }

  // ── Filter helpers ────────────────────────────────────────────────────────

  /**
   * Read filter inputs, reset to page 1, and fetch.
   */
  function applyFilters() {
    activeFilter = buildFilter();
    currentPage  = 1;
    fetchLogs();
  }

  /**
   * Read current filter input values and return a filter object.
   * @returns {{ engagement_id?: string, actor?: string, action_type?: string }}
   */
  function buildFilter() {
    const f = {};
    const engId = filterEngagement.value.trim();
    const actor = filterActor.value.trim();
    const atype = filterActionType.value;

    if (engId)  f.engagement_id = engId;
    if (actor)  f.actor         = actor;
    if (atype)  f.action_type   = atype;

    return f;
  }

  // ── Sort UI ───────────────────────────────────────────────────────────────

  function updateSortUI() {
    if (sortDir === 'desc') {
      sortIcon.className  = 'fa fa-sort-desc';
      sortLabel.textContent = 'Newest first';
    } else {
      sortIcon.className  = 'fa fa-sort-asc';
      sortLabel.textContent = 'Oldest first';
    }
  }

  // ── API fetch ─────────────────────────────────────────────────────────────

  /**
   * Build the query string from current state and fetch log entries.
   */
  async function fetchLogs() {
    showLoading();

    const params = new URLSearchParams();
    params.set('page',      String(currentPage));
    params.set('page_size', String(PAGE_SIZE));
    params.set('sort',      sortDir);

    if (activeFilter.engagement_id) params.set('engagement_id', activeFilter.engagement_id);
    if (activeFilter.actor)         params.set('actor',          activeFilter.actor);
    if (activeFilter.action_type)   params.set('action_type',    activeFilter.action_type);

    try {
      const entries = await apiFetch('/api/v1/logs?' + params.toString());
      hideError();
      renderTable(entries);
      renderPagination(entries.length);
    } catch (err) {
      showError(err.message || 'Failed to load log entries.');
      hideLoading();
    }
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  /**
   * Show the loading spinner and hide the table/empty state.
   */
  function showLoading() {
    loadingRow.classList.remove('hidden');
    emptyRow.classList.add('hidden');
    tableWrapper.classList.add('hidden');
    resultCount.textContent = '';
  }

  /**
   * Hide the loading spinner.
   */
  function hideLoading() {
    loadingRow.classList.add('hidden');
  }

  /**
   * Display an error banner.
   * @param {string} msg
   */
  function showError(msg) {
    errorMsg.textContent = msg;
    errorRow.classList.remove('hidden');
  }

  /**
   * Hide the error banner.
   */
  function hideError() {
    errorRow.classList.add('hidden');
  }

  /**
   * Render the log entries into the table body.
   * @param {Array<Object>} entries
   */
  function renderTable(entries) {
    hideLoading();
    logTbody.innerHTML = '';

    if (!entries || entries.length === 0) {
      emptyRow.classList.remove('hidden');
      tableWrapper.classList.add('hidden');
      resultCount.textContent = '';
      return;
    }

    emptyRow.classList.add('hidden');
    tableWrapper.classList.remove('hidden');
    resultCount.textContent = entries.length + ' result' + (entries.length === 1 ? '' : 's');

    entries.forEach(function (entry) {
      const tr = document.createElement('tr');

      // action_type — styled as a label/badge
      const tdAction = document.createElement('td');
      const badge = document.createElement('code');
      badge.textContent = escapeHtml(entry.action_type || '');
      tdAction.appendChild(badge);

      // actor
      const tdActor = document.createElement('td');
      tdActor.textContent = entry.actor_username || '—';

      // description
      const tdDesc = document.createElement('td');
      tdDesc.textContent = entry.description || '';

      // timestamp — formatted as local datetime
      const tdTs = document.createElement('td');
      tdTs.textContent = formatTimestamp(entry.occurred_at);
      tdTs.style.whiteSpace = 'nowrap';

      tr.appendChild(tdAction);
      tr.appendChild(tdActor);
      tr.appendChild(tdDesc);
      tr.appendChild(tdTs);

      logTbody.appendChild(tr);
    });
  }

  /**
   * Render the pagination footer.
   * @param {number} returnedCount  Number of items in the current page response.
   */
  function renderPagination(returnedCount) {
    paginationUl.innerHTML = '';

    const isFirstPage = (currentPage === 1);
    const hasNextPage = (returnedCount === PAGE_SIZE);  // if we got a full page, there may be more

    const startItem = ((currentPage - 1) * PAGE_SIZE) + 1;
    const endItem   = ((currentPage - 1) * PAGE_SIZE) + returnedCount;
    pageInfo.textContent = returnedCount > 0
      ? 'Showing ' + startItem + '–' + endItem
      : '';

    // Previous button
    const prevLi = document.createElement('li');
    prevLi.className = isFirstPage ? 'disabled' : '';
    prevLi.innerHTML = '<a href="#" aria-label="Previous"><span aria-hidden="true">&laquo;</span></a>';
    if (!isFirstPage) {
      prevLi.querySelector('a').addEventListener('click', function (e) {
        e.preventDefault();
        currentPage--;
        fetchLogs();
      });
    }
    paginationUl.appendChild(prevLi);

    // Current page number
    const curLi = document.createElement('li');
    curLi.className = 'active';
    curLi.innerHTML = '<a href="#">' + currentPage + ' <span class="sr-only">(current)</span></a>';
    paginationUl.appendChild(curLi);

    // Next button
    const nextLi = document.createElement('li');
    nextLi.className = hasNextPage ? '' : 'disabled';
    nextLi.innerHTML = '<a href="#" aria-label="Next"><span aria-hidden="true">&raquo;</span></a>';
    if (hasNextPage) {
      nextLi.querySelector('a').addEventListener('click', function (e) {
        e.preventDefault();
        currentPage++;
        fetchLogs();
      });
    }
    paginationUl.appendChild(nextLi);
  }

  // ── Utility helpers ───────────────────────────────────────────────────────

  /**
   * Format an ISO 8601 / RFC 3339 timestamp string for display.
   * Falls back to the raw string when parsing fails.
   * @param {string} raw
   * @returns {string}
   */
  function formatTimestamp(raw) {
    if (!raw) return '—';
    try {
      const d = new Date(raw);
      if (isNaN(d.getTime())) return raw;
      return d.toLocaleString(undefined, {
        year:   'numeric',
        month:  'short',
        day:    'numeric',
        hour:   '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch (_) {
      return raw;
    }
  }

  /**
   * Escape HTML special characters to prevent XSS when inserting text into HTML.
   * @param {string} str
   * @returns {string}
   */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ── Start ─────────────────────────────────────────────────────────────────
  init();

})();
