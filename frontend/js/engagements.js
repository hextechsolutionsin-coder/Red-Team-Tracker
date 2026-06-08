/**
 * engagements.js — Engagements list and detail page logic for RedBoard.
 *
 * Depends on: api.js, auth.js (must be loaded before this file).
 *
 * Exports two page controllers via global objects:
 *   - EngagementsListPage  (used by engagements.html)
 *   - EngagementDetailPage (used by engagement-detail.html)
 *
 * Requirements: 4.1, 4.3, 4.6, 4.7, 4.8
 */

'use strict';

/* ─────────────────────────────────────────────────────────────────────────────
 * Shared helpers
 * ───────────────────────────────────────────────────────────────────────────── */

/**
 * Status order for the engagement lifecycle (Requirement 4.3).
 * planned → active → on-hold → remediation → completed → reopened → archived
 */
var STATUS_ORDER = ['planned', 'active', 'on-hold', 'remediation', 'completed', 'reopened', 'archived'];

/**
 * Valid transitions map: current status → array of allowed next statuses.
 */
var VALID_TRANSITIONS = {
  'planned':     ['active'],
  'active':      ['on-hold', 'remediation', 'completed'],
  'on-hold':     ['active'],
  'remediation': ['active', 'completed'],
  'completed':   ['archived', 'reopened'],
  'reopened':    ['active'],
  'archived':    [],
};

/**
 * Return the list of valid next statuses for a given current status,
 * or an empty array if at a final state.
 *
 * @param {string} current
 * @returns {string[]}
 */
function getValidTransitions(current) {
  return VALID_TRANSITIONS[current] || [];
}

/**
 * Return the next valid status for a given current status, or null if already
 * at the final state (archived). Returns the first valid transition.
 *
 * @param {string} current
 * @returns {string|null}
 */
function nextStatus(current) {
  var transitions = getValidTransitions(current);
  return transitions.length > 0 ? transitions[0] : null;
}

/**
 * Render a Bootstrap label for an engagement status.
 *
 * @param {string} status
 * @returns {string} HTML string
 */
function statusLabel(status) {
  var cls = {
    planned:     'label-planned',
    active:      'label-active',
    'on-hold':   'label-warning',
    remediation: 'label-info',
    completed:   'label-completed',
    reopened:    'label-danger',
    archived:    'label-archived',
  }[status] || 'label-default';
  return '<span class="label ' + cls + '">' + escapeHtml(status) + '</span>';
}

/**
 * Minimal HTML-escape helper.
 *
 * @param {string|null|undefined} str
 * @returns {string}
 */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Format an ISO date string (YYYY-MM-DD or datetime) as YYYY-MM-DD.
 *
 * @param {string} isoDate
 * @returns {string}
 */
function formatDate(isoDate) {
  if (!isoDate) return '—';
  return String(isoDate).slice(0, 10);
}

/**
 * Show or hide an element by ID using the Bootstrap `hidden` utility class.
 *
 * @param {string} id  - Element ID (without #)
 * @param {boolean} visible
 */
function setVisible(id, visible) {
  var el = document.getElementById(id);
  if (!el) return;
  if (visible) {
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

/**
 * Display an error banner.
 *
 * @param {string} msgId   - ID of the <span> that holds the message text.
 * @param {string} wrapId  - ID of the wrapper alert div.
 * @param {string} msg     - Message to display.
 */
function showError(msgId, wrapId, msg) {
  var el = document.getElementById(msgId);
  if (el) el.textContent = msg || 'An error occurred.';
  setVisible(wrapId, true);
}

/** Hide an error banner. */
function hideError(wrapId) {
  setVisible(wrapId, false);
}

/**
 * Display a success banner.
 *
 * @param {string} msgId  - ID of the <span> that holds the message text.
 * @param {string} wrapId - ID of the wrapper alert div.
 * @param {string} msg    - Message to display.
 */
function showSuccess(msgId, wrapId, msg) {
  var el = document.getElementById(msgId);
  if (el) el.textContent = msg || 'Success.';
  setVisible(wrapId, true);
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Shared navbar wiring
 * ───────────────────────────────────────────────────────────────────────────── */

/**
 * Wire the navbar: show username, set up logout, conditionally show
 * admin/lead-only nav items.
 *
 * @param {{ username: string, role: string }} user
 */
function initNavbar(user) {
  var navUsername = document.getElementById('nav-username');
  if (navUsername) {
    navUsername.innerHTML = '<i class="fa fa-user-circle"></i> ' + escapeHtml(user.username);
  }

  // Show Logs nav for lead/admin
  if (user.role === 'lead' || user.role === 'admin') {
    setVisible('nav-logs', true);
  }

  // Show Users nav for admin only
  if (user.role === 'admin') {
    setVisible('nav-users', true);
  }

  var logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function (e) {
      e.preventDefault();
      logout();
    });
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
 * EngagementsListPage
 * Requirements: 4.1, 4.6
 * ═══════════════════════════════════════════════════════════════════════════ */

var EngagementsListPage = (function () {
  'use strict';

  var _user     = null;
  var _page     = 1;
  var _pageSize = 20;
  var _status   = '';

  /** Initialise the engagements list page. */
  function init() {
    _user = requireAuth();
    initNavbar(_user);

    // Show "New Engagement" button for lead/admin only (Requirement 4.1)
    if (_user.role === 'lead' || _user.role === 'admin') {
      setVisible('btn-create', true);
    }

    // Status filter change triggers reload from page 1
    document.getElementById('status-filter').addEventListener('change', function () {
      _status = this.value;
      _page   = 1;
      loadEngagements();
    });

    // "New Engagement" button opens the create modal
    var btnCreate = document.getElementById('btn-create');
    if (btnCreate) {
      btnCreate.addEventListener('click', function () {
        resetCreateForm();
        $('#create-modal').modal('show');
      });
    }

    // Submit button inside the create modal
    document.getElementById('btn-create-submit').addEventListener('click', submitCreate);

    // Allow Enter key to submit the modal form
    document.getElementById('create-form').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitCreate();
      }
    });

    loadEngagements();
  }

  /** Fetch and render the engagements list (Requirement 4.6). */
  function loadEngagements() {
    var tbody = document.getElementById('engagements-tbody');
    tbody.innerHTML =
      '<tr><td colspan="5" class="text-center text-muted">' +
      '<i class="fa fa-spinner fa-spin"></i> Loading…</td></tr>';

    hideError('page-error');

    var params = new URLSearchParams({
      page:      _page,
      page_size: _pageSize,
    });
    if (_status) params.set('status', _status);

    apiFetch('/api/v1/engagements?' + params.toString())
      .then(function (data) {
        renderTable(data || []);
        renderPagination(data ? data.length : 0);
      })
      .catch(function (err) {
        tbody.innerHTML =
          '<tr><td colspan="5" class="text-center text-danger">' +
          '<i class="fa fa-exclamation-circle"></i> Failed to load engagements.</td></tr>';
        showError('page-error-msg', 'page-error', err.message || 'Failed to load engagements.');
      });
  }

  /**
   * Render the table rows from an array of engagement objects.
   * Operators see only the "View" action; management actions are hidden (Req 4.6).
   */
  function renderTable(engagements) {
    var tbody = document.getElementById('engagements-tbody');

    if (!engagements.length) {
      tbody.innerHTML =
        '<tr><td colspan="5" class="text-center text-muted">' +
        '<i class="fa fa-info-circle"></i> No engagements found.</td></tr>';
      return;
    }

    var rows = engagements.map(function (eng) {
      var detailUrl = 'engagement-detail.html?id=' + encodeURIComponent(eng.id);

      // All roles can view; no management actions exposed here for operators
      var actions =
        '<a href="' + detailUrl + '" class="btn btn-xs btn-default">' +
        '<i class="fa fa-eye"></i> View</a>';

      return '<tr>' +
        '<td><a href="' + detailUrl + '">' + escapeHtml(eng.name) + '</a></td>' +
        '<td>' + statusLabel(eng.status) + '</td>' +
        '<td>' + formatDate(eng.start_date) + '</td>' +
        '<td>' + formatDate(eng.end_date) + '</td>' +
        '<td class="table-actions">' + actions + '</td>' +
        '</tr>';
    });

    tbody.innerHTML = rows.join('');
  }

  /** Render simple prev/next pagination controls. */
  function renderPagination(count) {
    var wrap = document.getElementById('pagination-wrap');
    var ul   = document.getElementById('pagination');

    var isFirstPage = _page === 1;
    var isLastPage  = count < _pageSize;

    if (isFirstPage && isLastPage) {
      wrap.classList.add('hidden');
      return;
    }

    wrap.classList.remove('hidden');

    var prevDisabled = isFirstPage ? 'disabled' : '';
    var nextDisabled = isLastPage  ? 'disabled' : '';

    ul.innerHTML =
      '<li class="' + prevDisabled + '">' +
        '<a href="#" id="btn-prev" aria-label="Previous">&laquo; Prev</a>' +
      '</li>' +
      '<li class="disabled"><a href="#">Page ' + _page + '</a></li>' +
      '<li class="' + nextDisabled + '">' +
        '<a href="#" id="btn-next" aria-label="Next">Next &raquo;</a>' +
      '</li>';

    if (!isFirstPage) {
      document.getElementById('btn-prev').addEventListener('click', function (e) {
        e.preventDefault();
        _page--;
        loadEngagements();
      });
    }

    if (!isLastPage) {
      document.getElementById('btn-next').addEventListener('click', function (e) {
        e.preventDefault();
        _page++;
        loadEngagements();
      });
    }
  }

  /** Reset and prepare the create engagement modal. */
  function resetCreateForm() {
    document.getElementById('create-form').reset();
    hideError('create-error');
    var btn = document.getElementById('btn-create-submit');
    btn.disabled = false;
    btn.innerHTML = '<i class="fa fa-save"></i> Create';
  }

  /** Submit the create engagement form (Requirement 4.1). */
  function submitCreate() {
    hideError('create-error');

    var name      = document.getElementById('f-name').value.trim();
    var desc      = document.getElementById('f-description').value.trim();
    var scope     = document.getElementById('f-scope').value.trim();
    var startDate = document.getElementById('f-start-date').value;
    var endDate   = document.getElementById('f-end-date').value;

    if (!name) {
      return showError('create-error-msg', 'create-error', 'Engagement name is required.');
    }
    if (!startDate || !endDate) {
      return showError('create-error-msg', 'create-error', 'Start date and end date are required.');
    }
    if (endDate < startDate) {
      return showError('create-error-msg', 'create-error', 'End date must be on or after start date.');
    }

    var btn = document.getElementById('btn-create-submit');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating…';

    var body = { name: name, start_date: startDate, end_date: endDate };
    if (desc)  body.description = desc;
    if (scope) body.scope       = scope;

    apiFetch('/api/v1/engagements', {
      method: 'POST',
      body:   JSON.stringify(body),
    })
      .then(function (eng) {
        $('#create-modal').modal('hide');
        // Navigate to the newly created engagement's detail page
        window.location.href = 'engagement-detail.html?id=' + eng.id;
      })
      .catch(function (err) {
        showError('create-error-msg', 'create-error', err.message || 'Failed to create engagement.');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa fa-save"></i> Create';
      });
  }

  return { init: init };

})();

/* ═══════════════════════════════════════════════════════════════════════════
 * EngagementDetailPage
 * Requirements: 4.1, 4.3, 4.7, 4.8
 * ═══════════════════════════════════════════════════════════════════════════ */

var EngagementDetailPage = (function () {
  'use strict';

  var _user         = null;
  var _engagementId = null;
  var _engagement   = null;

  /** List of operator IDs shown in the panel (populated on each assign). */
  var _assignedOperatorIds = [];

  /** Initialise the engagement detail page. */
  function init() {
    _user = requireAuth();
    initNavbar(_user);

    // Read engagement ID from the URL query string
    var params = new URLSearchParams(window.location.search);
    _engagementId = params.get('id');

    if (!_engagementId) {
      showError('page-error-msg', 'page-error', 'No engagement ID specified in the URL.');
      setVisible('detail-loading', false);
      return;
    }

    // Show assign-operator section for lead/admin (Requirement 4.8)
    if (_user.role === 'lead' || _user.role === 'admin') {
      setVisible('assign-operator-section', true);
      document.getElementById('btn-assign').addEventListener('click', submitAssignOperator);
    }

    // Wire advance-status button (Requirement 4.3)
    // Click handling is now done dynamically in renderAdvanceButton()

    // Wire generate-report button (Requirement 9.x — reports.js provides downloadReport)
    document.getElementById('btn-report').addEventListener('click', function () {
      if (typeof downloadReport === 'function') {
        downloadReport(_engagementId);
      }
    });

    loadEngagement();
  }

  /** Fetch the engagement from the API and render the page. */
  function loadEngagement() {
    setVisible('detail-loading', true);
    setVisible('detail-content', false);
    hideError('page-error');

    apiFetch('/api/v1/engagements/' + encodeURIComponent(_engagementId))
      .then(function (eng) {
        _engagement = eng;
        renderDetail(eng);
        setVisible('detail-loading', false);
        setVisible('detail-content', true);
      })
      .catch(function (err) {
        setVisible('detail-loading', false);
        showError('page-error-msg', 'page-error', err.message || 'Failed to load engagement.');
      });
  }

  /**
   * Populate the detail page with data from an engagement object.
   *
   * @param {object} eng - Engagement response from the API.
   */
  function renderDetail(eng) {
    // Breadcrumb
    var bc = document.getElementById('breadcrumb-name');
    if (bc) bc.textContent = eng.name;

    // Page title
    document.getElementById('eng-name').textContent = eng.name;

    // Status badge
    document.getElementById('eng-status').innerHTML = statusLabel(eng.status);

    // Dates
    document.getElementById('eng-start-date').textContent = formatDate(eng.start_date);
    document.getElementById('eng-end-date').textContent   = formatDate(eng.end_date);

    // Description (optional)
    var descEl = document.getElementById('eng-description');
    if (eng.description) {
      descEl.textContent = eng.description;
      descEl.classList.remove('text-muted');
    } else {
      descEl.textContent = '—';
      descEl.classList.add('text-muted');
    }

    // Scope (optional)
    var scopeEl = document.getElementById('eng-scope');
    if (eng.scope) {
      scopeEl.textContent = eng.scope;
      scopeEl.classList.remove('text-muted');
    } else {
      scopeEl.textContent = '—';
      scopeEl.classList.add('text-muted');
    }

    // Findings link filtered by this engagement (Requirement 4.7)
    var findingsLink = document.getElementById('findings-link');
    if (findingsLink) {
      findingsLink.href = 'findings.html?engagement_id=' + encodeURIComponent(eng.id);
    }

    // Advance-status button (Requirement 4.3 — forward-only, lead/admin only)
    renderAdvanceButton(eng);

    // Report button (lead/admin only)
    if (_user.role === 'lead' || _user.role === 'admin') {
      setVisible('btn-report', true);
    }
  }

  /**
   * Show or hide the advance-status dropdown depending on the current status
   * and the user's role.  Only lead/admin may advance status (Req 4.3).
   *
   * Renders a Bootstrap dropdown button showing all valid transitions.
   *
   * @param {object} eng
   */
  function renderAdvanceButton(eng) {
    var transitions = getValidTransitions(eng.status);
    var canAdvance  = transitions.length > 0 && (_user.role === 'lead' || _user.role === 'admin');

    var btnContainer = document.getElementById('btn-advance-status');

    if (canAdvance) {
      if (transitions.length === 1) {
        // Single transition — render as a simple button
        var target = transitions[0];
        var capitalised = target.charAt(0).toUpperCase() + target.slice(1);
        btnContainer.className = 'btn btn-warning';
        btnContainer.style.display = 'inline-block';
        btnContainer.innerHTML = '<i class="fa fa-arrow-right"></i> <span id="btn-advance-label">Advance to ' + capitalised + '</span>';
        btnContainer.onclick = function () { submitAdvanceStatus(target); };
        btnContainer.classList.remove('hidden');
      } else {
        // Multiple transitions — render as a dropdown button group
        var html = '<div class="btn-group">' +
          '<button type="button" class="btn btn-warning dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">' +
          '<i class="fa fa-arrow-right"></i> Transition Status <span class="caret"></span>' +
          '</button>' +
          '<ul class="dropdown-menu">';
        for (var i = 0; i < transitions.length; i++) {
          var t = transitions[i];
          var cap = t.charAt(0).toUpperCase() + t.slice(1);
          html += '<li><a href="#" class="advance-option" data-status="' + escapeHtml(t) + '">' + escapeHtml(cap) + '</a></li>';
        }
        html += '</ul></div>';

        // We need to replace the button with a wrapper div
        btnContainer.className = '';
        btnContainer.style.display = 'inline-block';
        btnContainer.innerHTML = html;
        btnContainer.onclick = null;
        btnContainer.classList.remove('hidden');

        // Attach click handlers to dropdown items
        var options = btnContainer.querySelectorAll('.advance-option');
        for (var j = 0; j < options.length; j++) {
          (function (option) {
            option.addEventListener('click', function (e) {
              e.preventDefault();
              submitAdvanceStatus(option.getAttribute('data-status'));
            });
          })(options[j]);
        }
      }
    } else {
      btnContainer.classList.add('hidden');
    }
  }

  /**
   * Submit a status transition PATCH request.
   *
   * @param {string} targetStatus - The status to transition to.
   */
  function submitAdvanceStatus(targetStatus) {
    if (!_engagement) return;
    if (!targetStatus) return;

    hideError('status-error');
    setVisible('status-success', false);

    var btnContainer = document.getElementById('btn-advance-status');
    var btn = btnContainer.querySelector('.btn') || btnContainer;
    btn.disabled = true;
    var origHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Updating…';

    apiFetch('/api/v1/engagements/' + encodeURIComponent(_engagementId), {
      method: 'PATCH',
      body:   JSON.stringify({ status: targetStatus }),
    })
      .then(function (eng) {
        _engagement = eng;
        renderDetail(eng);

        var capitalised = targetStatus.charAt(0).toUpperCase() + targetStatus.slice(1);
        showSuccess(
          'status-success-msg',
          'status-success',
          'Status changed to "' + capitalised + '".'
        );
      })
      .catch(function (err) {
        showError('status-error-msg', 'status-error', err.message || 'Failed to change status.');
        btn.disabled = false;
        btn.innerHTML = origHtml;
      });
  }

  /**
   * Assign an operator by UUID to the current engagement (Requirement 4.8).
   * POSTs to POST /api/v1/engagements/{id}/operators with { operator_ids: [uuid] }.
   */
  function submitAssignOperator() {
    hideError('assign-error');
    setVisible('assign-success', false);

    var input      = document.getElementById('assign-operator-id');
    var operatorId = input ? input.value.trim() : '';

    if (!operatorId) {
      return showError('assign-error-msg', 'assign-error', 'Please enter an operator User ID.');
    }

    // Basic UUID format check (client-side only; the server validates definitively)
    var uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidPattern.test(operatorId)) {
      return showError('assign-error-msg', 'assign-error', 'That does not look like a valid UUID.');
    }

    var btn = document.getElementById('btn-assign');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Assigning…';

    apiFetch('/api/v1/engagements/' + encodeURIComponent(_engagementId) + '/operators', {
      method: 'POST',
      body:   JSON.stringify({ operator_ids: [operatorId] }),
    })
      .then(function () {
        if (input) input.value = '';
        btn.disabled = false;
        btn.innerHTML = '<i class="fa fa-plus"></i> Assign';

        // Add to the displayed operator list if not already shown
        if (_assignedOperatorIds.indexOf(operatorId) === -1) {
          _assignedOperatorIds.push(operatorId);
          renderOperatorItem(operatorId);
        }

        showSuccess(
          'assign-success-msg',
          'assign-success',
          'Operator assigned successfully.'
        );
      })
      .catch(function (err) {
        showError('assign-error-msg', 'assign-error', err.message || 'Failed to assign operator.');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa fa-plus"></i> Assign';
      });
  }

  /**
   * Append an operator entry to the operators list in the UI.
   *
   * @param {string} operatorId - UUID string
   */
  function renderOperatorItem(operatorId) {
    var list  = document.getElementById('operators-list');
    var noMsg = document.getElementById('no-operators-msg');

    // Hide the "no operators" message once we have at least one
    if (noMsg) noMsg.classList.add('hidden');

    if (list) {
      var li = document.createElement('li');
      li.className = 'text-muted';
      li.style.padding = '2px 0';
      li.innerHTML = '<i class="fa fa-user"></i> <code style="font-size:11px;">' +
        escapeHtml(operatorId) + '</code>';
      list.appendChild(li);
    }
  }

  return { init: init };

})();
