/**
 * dashboard.js — Dashboard page logic for RedBoard.
 *
 * Depends on: api.js, auth.js (both loaded before this file).
 *
 * Responsibilities
 * ----------------
 * 1. Guard the page — redirect to login if the user is not authenticated.
 * 2. On page load, fetch GET /api/v1/dashboard/stats and
 *    GET /api/v1/dashboard/recent-logs concurrently.
 * 3. Render stat panels (active engagements, open findings, severity counts).
 * 4. Render a donut chart of findings-by-severity using Chart.js.
 * 5. Wire severity-count clicks to navigate to findings.html?severity=<value>.
 * 6. Render the 10 most recent log entries in a table.
 * 7. Show an inline error banner (no navigation) on API failure.
 * 8. Wire the "Refresh" button to re-fetch both endpoints.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
 */

'use strict';

(function () {

  // ── Auth guard ────────────────────────────────────────────────────────────

  const user = requireAuth();   // redirects to /index.html if not authenticated

  // Show username in navbar
  const usernameEl = document.getElementById('navbar-username-text');
  if (usernameEl) {
    usernameEl.textContent = user.username;
  }

  // Show "Users" nav link for admins only
  if (user.role === 'admin') {
    const navUsers = document.getElementById('nav-users');
    if (navUsers) {
      navUsers.classList.remove('hidden');
    }
  }

  // Logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function (e) {
      e.preventDefault();
      logout();
    });
  }

  // ── DOM references ────────────────────────────────────────────────────────

  const errorDiv     = document.getElementById('dashboard-error');
  const errorMsgEl   = document.getElementById('dashboard-error-msg');
  const refreshBtn   = document.getElementById('refresh-btn');
  const refreshIcon  = document.getElementById('refresh-icon');

  const statActive   = document.getElementById('stat-active-engagements');
  const statOpen     = document.getElementById('stat-open-findings');

  const sevIds = ['Critical', 'High', 'Medium', 'Low', 'Info'];

  const logsBody     = document.getElementById('recent-logs-tbody');
  const logCount     = document.getElementById('recent-log-count');

  const chartCanvas  = document.getElementById('severity-chart');
  const chartNoData  = document.getElementById('chart-no-data');

  // Chart.js instance (kept so we can destroy/recreate on refresh)
  let severityChart = null;

  // ── Severity colours (matching app.css badge classes) ─────────────────────

  const SEVERITY_COLORS = {
    Critical: '#7b241c',
    High:     '#c0392b',
    Medium:   '#e67e22',
    Low:      '#f1c40f',
    Info:     '#3498db',
  };

  // ── Error helpers ─────────────────────────────────────────────────────────

  /**
   * Show the inline error banner with a given message.
   * Does NOT navigate away from the page (Requirement 8.6).
   *
   * @param {string} msg
   */
  function showError(msg) {
    errorMsgEl.textContent = msg || 'An unexpected error occurred. Please try again.';
    errorDiv.classList.remove('hidden');
  }

  function hideError() {
    errorDiv.classList.add('hidden');
  }

  // ── Refresh button spinner helper ─────────────────────────────────────────

  function setRefreshing(active) {
    refreshBtn.disabled = active;
    if (active) {
      refreshIcon.classList.add('fa-spin');
    } else {
      refreshIcon.classList.remove('fa-spin');
    }
  }

  // ── Stat panel renderers ──────────────────────────────────────────────────

  /**
   * Populate the stat panels from the /stats response.
   *
   * @param {{ active_engagements: number, open_findings: number,
   *           findings_by_severity: { Critical: number, High: number,
   *                                   Medium: number, Low: number, Info: number } }} stats
   */
  /**
   * Animate a numeric value from start to end over duration milliseconds.
   *
   * @param {HTMLElement} element
   * @param {number} start
   * @param {number} end
   * @param {number} duration
   */
  function animateValue(element, start, end, duration) {
    if (start === end) return;
    var range = end - start;
    var startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      element.textContent = Math.floor(progress * range + start);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function renderStats(stats) {
    statActive.textContent = stats.active_engagements;
    statOpen.textContent   = stats.open_findings;

    // Animate stat values from 0 to their final value
    animateValue(statActive, 0, stats.active_engagements, 800);
    animateValue(statOpen, 0, stats.open_findings, 800);

    const sev = stats.findings_by_severity;
    sevIds.forEach(function (s) {
      const el = document.getElementById('sev-' + s);
      if (el) {
        var val = sev[s] != null ? sev[s] : 0;
        el.textContent = val;
        animateValue(el, 0, val, 800);
      }
    });

    renderChart(sev);
  }

  // ── Chart renderer ────────────────────────────────────────────────────────

  /**
   * Render (or re-render) the donut chart of findings by severity.
   * Uses Chart.js loaded from vendor/chartjs/Chart.min.js.
   *
   * @param {{ Critical: number, High: number, Medium: number, Low: number, Info: number }} sev
   */
  function renderChart(sev) {
    const labels = sevIds;
    const data   = labels.map(function (s) { return sev[s] || 0; });
    const total  = data.reduce(function (a, b) { return a + b; }, 0);

    // Destroy previous instance to avoid canvas reuse warnings
    if (severityChart) {
      severityChart.destroy();
      severityChart = null;
    }

    if (total === 0) {
      // No findings — hide canvas, show placeholder message
      chartCanvas.classList.add('hidden');
      chartNoData.classList.remove('hidden');
      return;
    }

    chartCanvas.classList.remove('hidden');
    chartNoData.classList.add('hidden');

    const colors = labels.map(function (s) { return SEVERITY_COLORS[s]; });

    severityChart = new Chart(chartCanvas, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: colors,
          borderColor: '#ffffff',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: false,
        legend: {
          position: 'bottom',
        },
        tooltips: {
          callbacks: {
            label: function (item, chartData) {
              var label = chartData.labels[item.index] || '';
              var value = chartData.datasets[0].data[item.index];
              return ' ' + label + ': ' + value;
            },
          },
        },
      },
    });
  }

  // ── Recent logs renderer ──────────────────────────────────────────────────

  /**
   * Render the 10 most recent log entries into the table.
   *
   * @param {Array<{ action_type: string, actor_username: string,
   *                  description: string, occurred_at: string }>} logs
   */
  function renderLogs(logs) {
    logCount.textContent = logs.length;

    if (logs.length === 0) {
      logsBody.innerHTML =
        '<tr><td colspan="4" class="text-center text-muted">No activity recorded yet.</td></tr>';
      return;
    }

    var rows = logs.map(function (entry) {
      var timeStr = formatUtcTimestamp(entry.occurred_at);
      var actionLabel = formatActionType(entry.action_type);
      return '<tr>' +
        '<td><small class="text-muted">' + escapeHtml(timeStr) + '</small></td>' +
        '<td><code>' + escapeHtml(actionLabel) + '</code></td>' +
        '<td><strong>' + escapeHtml(entry.actor_username) + '</strong></td>' +
        '<td>' + escapeHtml(entry.description) + '</td>' +
        '</tr>';
    });

    logsBody.innerHTML = rows.join('');
  }

  // ── Risk overview renderer ────────────────────────────────────────────────

  /**
   * Render the risk overview panel with org-level and per-engagement risk scores.
   *
   * @param {{ org_risk_score: number|null, org_risk_rating: string|null,
   *           engagements: Array<{ id: string, name: string, risk_score: number|null,
   *                                 risk_rating: string|null, finding_count: number,
   *                                 scored_finding_count: number }> }} risk
   */
  function renderRiskOverview(risk) {
    var orgScoreEl  = document.getElementById('org-risk-score');
    var orgRatingEl = document.getElementById('org-risk-rating');
    var table       = document.getElementById('risk-engagements-table');
    var tbody       = document.getElementById('risk-engagements-tbody');
    var emptyEl     = document.getElementById('risk-engagements-empty');

    // Org-level risk
    if (risk.org_risk_score != null) {
      orgScoreEl.textContent  = risk.org_risk_score;
      orgRatingEl.textContent = risk.org_risk_rating || '—';
      orgRatingEl.className   = 'label ' + riskRatingLabelClass(risk.org_risk_rating);
      // Animate the org risk score number
      animateValue(orgScoreEl, 0, Math.round(risk.org_risk_score), 800);
    } else {
      orgScoreEl.textContent  = '—';
      orgRatingEl.textContent = 'No data';
      orgRatingEl.className   = 'label label-default';
    }

    // Engagement risk table
    if (!risk.engagements || risk.engagements.length === 0) {
      table.style.display = 'none';
      emptyEl.style.display = 'block';
      return;
    }

    var hasScored = risk.engagements.some(function (e) { return e.risk_score != null; });
    if (!hasScored) {
      table.style.display = 'none';
      emptyEl.style.display = 'block';
      return;
    }

    emptyEl.style.display = 'none';
    table.style.display = '';

    tbody.innerHTML = risk.engagements.map(function (eng) {
      var scoreDisplay  = eng.risk_score != null ? eng.risk_score : '—';
      var ratingDisplay = eng.risk_rating || '—';
      var ratingClass   = riskRatingLabelClass(eng.risk_rating);
      return '<tr>' +
        '<td><a href="engagement-detail.html?id=' + encodeURIComponent(eng.id) + '">' + escapeHtml(eng.name) + '</a></td>' +
        '<td>' + escapeHtml(String(scoreDisplay)) + '</td>' +
        '<td><span class="label ' + ratingClass + '">' + escapeHtml(ratingDisplay) + '</span></td>' +
        '<td>' + eng.finding_count + '</td>' +
        '<td>' + eng.scored_finding_count + '</td>' +
        '</tr>';
    }).join('');
  }

  /**
   * Return Bootstrap label class for a risk rating.
   * @param {string|null} rating
   * @returns {string}
   */
  function riskRatingLabelClass(rating) {
    switch (rating) {
      case 'Critical': return 'label-danger';
      case 'High':     return 'label-warning';
      case 'Medium':   return 'label-info';
      case 'Low':      return 'label-primary';
      default:         return 'label-default';
    }
  }

  // ── Formatting helpers ────────────────────────────────────────────────────

  /**
   * Format an ISO 8601 UTC timestamp to a human-readable string.
   *
   * @param {string} isoString
   * @returns {string}
   */
  function formatUtcTimestamp(isoString) {
    if (!isoString) return '—';
    try {
      var d = new Date(isoString);
      // Produce "YYYY-MM-DD HH:MM UTC"
      var pad = function (n) { return String(n).padStart(2, '0'); };
      return d.getUTCFullYear() + '-' +
             pad(d.getUTCMonth() + 1) + '-' +
             pad(d.getUTCDate()) + ' ' +
             pad(d.getUTCHours()) + ':' +
             pad(d.getUTCMinutes()) + ' UTC';
    } catch (_) {
      return isoString;
    }
  }

  /**
   * Turn a snake_case action_type string into a readable label.
   * e.g. "finding_created" → "finding created"
   *
   * @param {string} actionType
   * @returns {string}
   */
  function formatActionType(actionType) {
    return (actionType || '').replace(/_/g, ' ');
  }

  /**
   * Escape HTML special characters to prevent XSS when inserting
   * API-sourced content via innerHTML.
   *
   * @param {string} str
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

  // ── Data loading ──────────────────────────────────────────────────────────

  /**
   * Fetch both dashboard endpoints concurrently.
   * On any failure, show an inline error — do NOT navigate away (Req. 8.6).
   * No automatic polling; called on load and on "Refresh" click (Req. 8.4).
   */
  async function loadDashboard() {
    hideError();
    setRefreshing(true);

    // Reset stats to "—" while loading
    statActive.textContent = '—';
    statOpen.textContent   = '—';
    sevIds.forEach(function (s) {
      var el = document.getElementById('sev-' + s);
      if (el) el.textContent = '—';
    });
    logCount.textContent = '—';
    logsBody.innerHTML =
      '<tr id="logs-placeholder"><td colspan="4" class="text-center text-muted">' +
      '<i class="fa fa-spinner fa-spin"></i> Loading…</td></tr>';

    try {
      // Fire all requests concurrently (Req. 8.4 — on page load)
      const [stats, logs, risk] = await Promise.all([
        apiFetch('/api/v1/dashboard/stats'),
        apiFetch('/api/v1/dashboard/recent-logs'),
        apiFetch('/api/v1/dashboard/risk'),
      ]);

      renderStats(stats);
      renderLogs(logs);
      renderRiskOverview(risk);

    } catch (err) {
      // Display inline error; never navigate away (Req. 8.6)
      var msg = (err && err.message) ? err.message : 'Failed to load dashboard data.';
      showError(msg);

      // Reset stats to a neutral state so stale numbers don't mislead
      statActive.textContent = '—';
      statOpen.textContent   = '—';
      sevIds.forEach(function (s) {
        var el = document.getElementById('sev-' + s);
        if (el) el.textContent = '—';
      });
      logCount.textContent = '—';
      logsBody.innerHTML =
        '<tr><td colspan="4" class="text-center text-muted">Could not load activity log.</td></tr>';
    } finally {
      setRefreshing(false);
    }
  }

  // ── Severity count click → findings.html?severity=<value> (Req. 8.5) ─────

  var severityLinks = document.querySelectorAll('.severity-link');
  Array.prototype.forEach.call(severityLinks, function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      var severity = link.getAttribute('data-severity');
      if (severity) {
        window.location.href = 'findings.html?severity=' + encodeURIComponent(severity);
      }
    });
  });

  // ── Refresh button (Req. 8.4) ─────────────────────────────────────────────

  if (refreshBtn) {
    refreshBtn.addEventListener('click', function () {
      loadDashboard();
    });
  }

  // ── Initial load on page load ─────────────────────────────────────────────

  loadDashboard();

})();
