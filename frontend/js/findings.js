/**
 * findings.js — Findings list page logic for RedBoard.
 *
 * Responsibilities
 * ----------------
 * - Require authentication on load; redirect to login if not authenticated.
 * - Read ?severity= from the URL and pre-populate the severity filter.
 * - Fetch paginated findings from GET /api/v1/findings with
 *   severity / status / MITRE filters and sort parameter.
 * - Render findings table with severity badges and links to finding-detail.html.
 * - Provide a "New Finding" form that POSTs to /api/v1/findings.
 * - Handle pagination (previous / next page buttons).
 *
 * Requirements: 5.1, 5.5, 5.7, 5.8
 */

'use strict';

(function () {

  // ── Auth guard ────────────────────────────────────────────────────────────
  const user = requireAuth();

  // Hide admin-only nav items for non-admin users
  if (user.role !== 'admin') {
    const adminLinks = document.getElementById('nav-admin-links');
    if (adminLinks) adminLinks.classList.add('hidden');
  }

  // Operators cannot create findings from the global list (no engagement context),
  // so hide the button — they should create from within an engagement.
  // Lead/admin can create from here by choosing an engagement in the modal.
  if (user.role === 'operator') {
    const btnWrap = document.getElementById('create-finding-btn-wrap');
    if (btnWrap) btnWrap.classList.add('hidden');
  }

  // Wire logout
  document.getElementById('nav-logout').addEventListener('click', function (e) {
    e.preventDefault();
    logout();
  });

  // ── State ─────────────────────────────────────────────────────────────────
  let currentPage = 1;
  const PAGE_SIZE = 25;

  // ── Pre-populate filters from URL params ──────────────────────────────────
  (function seedFiltersFromUrl() {
    const params = new URLSearchParams(window.location.search);

    // ?severity= — pre-select severity filter
    const sev = params.get('severity');
    if (sev) {
      const sel = document.getElementById('filter-severity');
      const opt = sel ? sel.querySelector('option[value="' + sev + '"]') : null;
      if (opt) sel.value = sev;
    }

    // ?engagement_id= — filter findings by engagement (Requirement 4.7)
    const engId = params.get('engagement_id');
    if (engId) {
      const hiddenInput = document.getElementById('filter-engagement-id');
      if (hiddenInput) hiddenInput.value = engId;

      // Show a banner indicating we're filtering by engagement and fetch its name
      const banner = document.getElementById('engagement-context-banner');
      if (banner) {
        banner.classList.remove('hidden');
        // Fetch engagement name for the banner
        apiFetch('/api/v1/engagements/' + encodeURIComponent(engId))
          .then(function (eng) {
            const nameEl = document.getElementById('engagement-context-name');
            if (nameEl && eng && eng.name) nameEl.textContent = eng.name;
            const backLink = banner.querySelector('a.alert-link');
            if (backLink) backLink.href = 'engagement-detail.html?id=' + encodeURIComponent(engId);
          })
          .catch(function () { /* banner remains with fallback '—' */ });
      }
    }
  })();

  // ── Helpers ───────────────────────────────────────────────────────────────

  function showPageError(msg) {
    document.getElementById('page-error-msg').textContent = msg || 'An error occurred.';
    document.getElementById('page-error').classList.remove('hidden');
  }

  function hidePageError() {
    document.getElementById('page-error').classList.add('hidden');
  }

  function severityBadge(severity) {
    const cls = {
      'Critical': 'badge-critical',
      'High':     'badge-high',
      'Medium':   'badge-medium',
      'Low':      'badge-low',
      'Info':     'badge-info',
    }[severity] || '';
    return `<span class="badge ${cls}">${escapeHtml(severity)}</span>`;
  }

  function statusLabel(status) {
    const labels = {
      'open':        'default',
      'in-progress': 'warning',
      'remediated':  'success',
      'verified':    'primary',
    };
    const bs = labels[status] || 'default';
    return `<span class="label label-${bs}">${escapeHtml(status)}</span>`;
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString();
    } catch (_) {
      return iso;
    }
  }

  // ── Read filter values ────────────────────────────────────────────────────

  function getFilters() {
    const engInput = document.getElementById('filter-engagement-id');
    return {
      severity:      document.getElementById('filter-severity').value  || null,
      status:        document.getElementById('filter-status').value    || null,
      mitre_id:      document.getElementById('filter-mitre').value.trim() || null,
      sort:          document.getElementById('filter-sort').value      || 'created_at',
      engagement_id: engInput ? (engInput.value.trim() || null) : null,
    };
  }

  // ── Fetch and render findings ─────────────────────────────────────────────

  async function loadFindings(page) {
    hidePageError();
    currentPage = page;

    const tbody    = document.getElementById('findings-tbody');
    const table    = document.getElementById('findings-table');
    const emptyDiv = document.getElementById('findings-empty');
    const loading  = document.getElementById('findings-loading');
    const paginNav = document.getElementById('pagination-nav');

    loading.style.display = 'block';
    table.style.display   = 'none';
    emptyDiv.classList.add('hidden');
    paginNav.classList.add('hidden');

    const filters = getFilters();

    const params = new URLSearchParams();
    params.set('page', page);
    params.set('page_size', PAGE_SIZE);
    if (filters.severity)      params.set('severity',      filters.severity);
    if (filters.status)        params.set('status',        filters.status);
    if (filters.mitre_id)      params.set('mitre_id',      filters.mitre_id);
    if (filters.sort)          params.set('sort',          filters.sort);
    if (filters.engagement_id) params.set('engagement_id', filters.engagement_id);

    let findings;
    try {
      findings = await apiFetch(`/api/v1/findings?${params.toString()}`);
    } catch (err) {
      showPageError(err.message || 'Failed to load findings.');
      loading.style.display = 'none';
      return;
    }

    loading.style.display = 'none';

    if (!findings || findings.length === 0) {
      emptyDiv.classList.remove('hidden');
      // Update pagination: disable next if no results
      updatePagination(findings ? findings.length : 0);
      return;
    }

    // Render rows
    tbody.innerHTML = findings.map(function (f) {
      return `<tr>
        <td>
          <a href="finding-detail.html?id=${encodeURIComponent(f.id)}">
            ${escapeHtml(f.title)}
          </a>
        </td>
        <td>${severityBadge(f.severity)}</td>
        <td>${statusLabel(f.status)}</td>
        <td>${f.mitre_id ? escapeHtml(f.mitre_id) : '<span class="text-muted">—</span>'}</td>
        <td>${formatDate(f.created_at)}</td>
        <td class="table-actions">
          <a href="finding-detail.html?id=${encodeURIComponent(f.id)}" class="btn btn-xs btn-default">
            <i class="fa fa-eye"></i> View
          </a>
        </td>
      </tr>`;
    }).join('');

    table.style.display = '';
    updatePagination(findings.length);
  }

  function updatePagination(count) {
    const paginNav = document.getElementById('pagination-nav');
    const prevLi   = document.getElementById('pager-prev');
    const nextLi   = document.getElementById('pager-next');

    paginNav.classList.remove('hidden');

    // Disable Prev on first page
    if (currentPage <= 1) {
      prevLi.classList.add('disabled');
    } else {
      prevLi.classList.remove('disabled');
    }

    // Disable Next if fewer results than page size
    if (count < PAGE_SIZE) {
      nextLi.classList.add('disabled');
    } else {
      nextLi.classList.remove('disabled');
    }
  }

  // ── Pagination events ─────────────────────────────────────────────────────

  document.getElementById('btn-prev').addEventListener('click', function (e) {
    e.preventDefault();
    if (currentPage > 1) {
      loadFindings(currentPage - 1);
    }
  });

  document.getElementById('btn-next').addEventListener('click', function (e) {
    e.preventDefault();
    loadFindings(currentPage + 1);
  });

  // ── Filter form ───────────────────────────────────────────────────────────

  document.getElementById('filter-form').addEventListener('submit', function (e) {
    e.preventDefault();
    loadFindings(1);
  });

  document.getElementById('btn-reset-filters').addEventListener('click', function () {
    document.getElementById('filter-severity').value = '';
    document.getElementById('filter-status').value   = '';
    document.getElementById('filter-mitre').value    = '';
    document.getElementById('filter-sort').value     = 'created_at';
    const engInput = document.getElementById('filter-engagement-id');
    if (engInput) engInput.value = '';
    // Also hide the engagement context banner when resetting
    const banner = document.getElementById('engagement-context-banner');
    if (banner) banner.classList.add('hidden');
    loadFindings(1);
  });

  // ── MITRE ATT&CK searchable dropdown ─────────────────────────────────────

  // Cached technique list: [{ id: 'T1059', name: 'Command and Scripting Interpreter' }, ...]
  let _mitreCache = null;

  async function loadMitreTechniques() {
    if (_mitreCache) return _mitreCache;
    try {
      // Use the MITRE ATT&CK STIX/TAXII v2.1 API — enterprise techniques
      const resp = await fetch(
        'https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json'
      );
      const data = await resp.json();
      const techniques = [];
      (data.objects || []).forEach(function (obj) {
        if (obj.type !== 'attack-pattern' || obj.revoked || obj.x_mitre_deprecated) return;
        const extRefs = obj.external_references || [];
        const mitreRef = extRefs.find(function (r) { return r.source_name === 'mitre-attack'; });
        if (!mitreRef) return;
        const techId = mitreRef.external_id; // e.g. T1059 or T1059.001
        // Only include top-level techniques (T + 4-5 digits, no dot) per system validation
        if (!/^T\d{4,5}$/.test(techId)) return;
        techniques.push({ id: techId, name: obj.name });
      });
      // Sort by ID numerically
      techniques.sort(function (a, b) { return a.id.localeCompare(b.id, undefined, { numeric: true }); });
      _mitreCache = techniques;
      return techniques;
    } catch (_) {
      return [];
    }
  }

  function initMitreSearch() {
    const searchInput = document.getElementById('cf-mitre-search');
    const dropdown    = document.getElementById('cf-mitre-dropdown');
    const hiddenId    = document.getElementById('cf-mitre-id');
    const nameInput   = document.getElementById('cf-mitre-name');

    if (!searchInput) return;

    // Load techniques in background when page loads
    loadMitreTechniques();

    searchInput.addEventListener('input', async function () {
      const query = this.value.trim().toLowerCase();
      // Clear selection when user types
      hiddenId.value  = '';
      nameInput.value = '';

      if (!query || query.length < 2) {
        dropdown.style.display = 'none';
        return;
      }

      const techniques = await loadMitreTechniques();
      const matches = techniques.filter(function (t) {
        return t.id.toLowerCase().includes(query) || t.name.toLowerCase().includes(query);
      }).slice(0, 50); // cap at 50 results

      if (matches.length === 0) {
        dropdown.style.display = 'none';
        return;
      }

      dropdown.innerHTML = matches.map(function (t) {
        return '<div class="mitre-option" data-id="' + escapeHtml(t.id) + '" data-name="' + escapeHtml(t.name) + '" ' +
          'style="padding:6px 12px;cursor:pointer;font-size:13px;border-bottom:1px solid #f0f0f0;">' +
          '<strong>' + escapeHtml(t.id) + '</strong> — ' + escapeHtml(t.name) +
          '</div>';
      }).join('');
      dropdown.style.display = 'block';

      // Click handler for each option
      dropdown.querySelectorAll('.mitre-option').forEach(function (el) {
        el.addEventListener('mousedown', function (e) {
          e.preventDefault(); // prevent blur firing before click
          const id   = el.getAttribute('data-id');
          const name = el.getAttribute('data-name');
          searchInput.value = id + ' — ' + name;
          hiddenId.value    = id;
          nameInput.value   = name;
          dropdown.style.display = 'none';
        });
        el.addEventListener('mouseover', function () {
          el.style.backgroundColor = '#f5f5f5';
        });
        el.addEventListener('mouseout', function () {
          el.style.backgroundColor = '';
        });
      });
    });

    // Hide dropdown when focus leaves
    searchInput.addEventListener('blur', function () {
      setTimeout(function () { dropdown.style.display = 'none'; }, 150);
    });
    searchInput.addEventListener('focus', function () {
      if (dropdown.children.length > 0) dropdown.style.display = 'block';
    });
  }

  initMitreSearch();

  // ── Create Finding form ───────────────────────────────────────────────────

  // Load engagement list into the select (for lead/admin creating from findings page)
  async function loadEngagementsForSelect() {
    const sel = document.getElementById('cf-engagement');
    if (!sel) return;
    // Clear existing options except the first placeholder
    while (sel.options.length > 1) sel.remove(1);
    try {
      const engagements = await apiFetch('/api/v1/engagements?page_size=100');
      (engagements || []).forEach(function (eng) {
        const opt = document.createElement('option');
        opt.value       = eng.id;
        opt.textContent = eng.name;
        sel.appendChild(opt);
      });
    } catch (_) {
      // Non-critical
    }
  }

  // Populate engagements on page load and also when modal opens
  loadEngagementsForSelect();
  $('#modal-create-finding').on('show.bs.modal', function () {
    loadEngagementsForSelect();
  });

  document.getElementById('create-finding-form').addEventListener('submit', async function (e) {
    e.preventDefault();

    const errorDiv = document.getElementById('create-finding-error');
    const errorMsg = document.getElementById('create-finding-error-msg');
    const btn      = document.getElementById('cf-submit-btn');

    errorDiv.classList.add('hidden');

    const title         = document.getElementById('cf-title').value.trim();
    const engagementId  = document.getElementById('cf-engagement').value;
    const severity      = document.getElementById('cf-severity').value;
    const status        = document.getElementById('cf-status').value;
    const mitreId       = document.getElementById('cf-mitre-id').value.trim() || null;
    const mitreName     = document.getElementById('cf-mitre-name').value.trim() || null;
    const repro         = document.getElementById('cf-repro').value.trim() || null;
    const remediation   = document.getElementById('cf-remediation').value.trim() || null;

    if (!title || !engagementId || !severity || !status) {
      errorMsg.textContent = 'Title, Engagement, Severity, and Status are required.';
      errorDiv.classList.remove('hidden');
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating…';

    try {
      await apiFetch('/api/v1/findings', {
        method: 'POST',
        body: JSON.stringify({
          title,
          engagement_id:       engagementId,
          severity,
          status,
          mitre_id:            mitreId,
          mitre_name:          mitreName,
          reproduction_steps:  repro,
          remediation_recs:    remediation,
        }),
      });

      // Success — close modal, reset form, reload list
      $('#modal-create-finding').modal('hide');
      document.getElementById('create-finding-form').reset();
      // Also reset MITRE search field and hidden input
      const mitreSearch = document.getElementById('cf-mitre-search');
      if (mitreSearch) mitreSearch.value = '';
      loadFindings(1);
    } catch (err) {
      errorMsg.textContent = err.message || 'Failed to create finding.';
      errorDiv.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="fa fa-save"></i> Create Finding';
    }
  });

  // ── Initial load ──────────────────────────────────────────────────────────
  loadFindings(1);

})();
