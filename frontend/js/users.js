/**
 * users.js — Admin-only user management page logic.
 *
 * Requirements: 3.1, 3.5, 3.6, 3.7
 *
 * Depends on: api.js (apiFetch, AppError), auth.js (requireRole, logout, currentUser)
 *
 * Features:
 *   - Redirect non-admins to dashboard.html on page load.
 *   - Paginated user list table (username, role, active status).
 *   - Create-user form (username, password, role).
 *   - Update-role action via modal (dropdown).
 *   - Deactivate user action via confirmation modal.
 */

'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;           // Matches the backend default (Req 3.6)

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentPage   = 1;
let totalUsers    = 0;          // Updated from X-Total-Count header when available
let lastPageItems = 0;          // Track items on last page to detect end

// The user ID targeted by either the role-update or deactivate modal
let targetUserId   = null;
let targetUsername = null;

// ---------------------------------------------------------------------------
// Entry point — guard non-admin access
// ---------------------------------------------------------------------------

(function init() {
  // requireRole redirects to /dashboard.html for non-admin roles
  // and to /index.html when not authenticated at all.
  const user = requireRole('admin');

  // Show the logged-in username in the navbar
  const navUser = document.getElementById('navbar-username');
  if (navUser) navUser.textContent = user.username;

  // Wire logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function (e) {
      e.preventDefault();
      logout();
    });
  }

  // Wire create-user form
  const createForm = document.getElementById('create-user-form');
  if (createForm) createForm.addEventListener('submit', handleCreateUser);

  // Wire refresh button
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', function () {
    loadUsers(currentPage);
  });

  // Wire role-modal save button
  const roleSaveBtn = document.getElementById('role-modal-save');
  if (roleSaveBtn) roleSaveBtn.addEventListener('click', handleUpdateRole);

  // Wire deactivate-modal confirm button
  const deactivateConfirmBtn = document.getElementById('deactivate-modal-confirm');
  if (deactivateConfirmBtn) deactivateConfirmBtn.addEventListener('click', handleDeactivate);

  // Clear modal errors when modals are closed
  $('#role-modal').on('hidden.bs.modal', function () {
    hideModalError('role-modal-error');
  });
  $('#deactivate-modal').on('hidden.bs.modal', function () {
    hideModalError('deactivate-modal-error');
  });

  // Initial load
  loadUsers(1);
})();

// ---------------------------------------------------------------------------
// User list — fetch and render
// ---------------------------------------------------------------------------

/**
 * Fetch and render a page of users.
 *
 * @param {number} page  1-indexed page number.
 */
async function loadUsers(page) {
  currentPage = page;

  showTableLoading(true);
  hidePageMessages();

  try {
    const data = await apiFetch(
      `/api/v1/users?page=${page}&page_size=${PAGE_SIZE}`
    );

    // data is an array of UserResponse objects
    const users = Array.isArray(data) ? data : [];
    lastPageItems = users.length;

    renderUsersTable(users);
    renderPagination(page, users.length);

  } catch (err) {
    showPageError(err.message || 'Failed to load users.');
    renderUsersTable([]);
    renderPagination(page, 0);
  } finally {
    showTableLoading(false);
  }
}

/**
 * Render rows into the user table.
 *
 * @param {Array} users  Array of user objects from the API.
 */
function renderUsersTable(users) {
  const tbody    = document.getElementById('users-tbody');
  const tableWrap = document.getElementById('users-table-wrap');
  const emptyDiv  = document.getElementById('users-empty');

  tbody.innerHTML = '';

  if (!users || users.length === 0) {
    tableWrap.classList.add('hidden');
    emptyDiv.classList.remove('hidden');
    return;
  }

  tableWrap.classList.remove('hidden');
  emptyDiv.classList.add('hidden');

  users.forEach(function (user) {
    const tr = document.createElement('tr');
    if (!user.is_active) tr.classList.add('text-muted');

    // Username cell
    const tdUsername = document.createElement('td');
    tdUsername.textContent = user.username;
    tr.appendChild(tdUsername);

    // Role cell
    const tdRole = document.createElement('td');
    tdRole.appendChild(buildRoleBadge(user.role));
    tr.appendChild(tdRole);

    // Status cell
    const tdStatus = document.createElement('td');
    if (user.is_active) {
      tdStatus.innerHTML = '<span class="label label-success">Active</span>';
    } else {
      tdStatus.innerHTML = '<span class="label label-default">Inactive</span>';
    }
    tr.appendChild(tdStatus);

    // Actions cell
    const tdActions = document.createElement('td');
    tdActions.classList.add('table-actions');

    // Update Role button — always available
    const roleBtn = document.createElement('button');
    roleBtn.className = 'btn btn-xs btn-primary';
    roleBtn.setAttribute('type', 'button');
    roleBtn.setAttribute('title', 'Update role');
    roleBtn.setAttribute('aria-label', 'Update role for ' + user.username);
    roleBtn.innerHTML = '<i class="fa fa-pencil"></i> Role';
    roleBtn.addEventListener('click', function () {
      openRoleModal(user.id, user.username, user.role);
    });
    tdActions.appendChild(roleBtn);

    // Deactivate button — only shown for active users
    if (user.is_active) {
      const deactivateBtn = document.createElement('button');
      deactivateBtn.className = 'btn btn-xs btn-warning';
      deactivateBtn.setAttribute('type', 'button');
      deactivateBtn.setAttribute('title', 'Deactivate user');
      deactivateBtn.setAttribute('aria-label', 'Deactivate ' + user.username);
      deactivateBtn.innerHTML = '<i class="fa fa-ban"></i> Deactivate';
      deactivateBtn.addEventListener('click', function () {
        openDeactivateModal(user.id, user.username);
      });
      tdActions.appendChild(deactivateBtn);
    }

    tr.appendChild(tdActions);
    tbody.appendChild(tr);
  });
}

/**
 * Build a Bootstrap badge element for a role string.
 *
 * @param {string} role
 * @returns {HTMLElement}
 */
function buildRoleBadge(role) {
  const span = document.createElement('span');
  span.textContent = role.charAt(0).toUpperCase() + role.slice(1);

  switch (role) {
    case 'admin':
      span.className = 'label label-danger';
      break;
    case 'lead':
      span.className = 'label label-primary';
      break;
    case 'operator':
      span.className = 'label label-info';
      break;
    default:
      span.className = 'label label-default';
  }

  return span;
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

/**
 * Render pagination controls.
 *
 * Because the API does not return a total-count header in the current
 * implementation, pagination is "load more" style: we show Previous / Next
 * based on whether the current page returned a full page of results.
 *
 * @param {number} page        Current page (1-indexed).
 * @param {number} itemCount   Number of items returned on this page.
 */
function renderPagination(page, itemCount) {
  const controls = document.getElementById('pagination-controls');
  const info     = document.getElementById('pagination-info');

  controls.innerHTML = '';

  const hasPrev = page > 1;
  const hasNext = itemCount === PAGE_SIZE;  // If a full page came back, there may be more

  // Info text
  const startItem = (page - 1) * PAGE_SIZE + 1;
  const endItem   = (page - 1) * PAGE_SIZE + itemCount;
  if (itemCount > 0) {
    info.innerHTML = `<small class="text-muted">Showing ${startItem}–${endItem}</small>`;
  } else {
    info.innerHTML = '';
  }

  // Previous button
  const prevLi = document.createElement('li');
  prevLi.className = hasPrev ? '' : 'disabled';
  const prevA = document.createElement('a');
  prevA.href = '#';
  prevA.setAttribute('aria-label', 'Previous');
  prevA.innerHTML = '<span aria-hidden="true">&laquo;</span>';
  if (hasPrev) {
    prevA.addEventListener('click', function (e) {
      e.preventDefault();
      loadUsers(page - 1);
    });
  }
  prevLi.appendChild(prevA);
  controls.appendChild(prevLi);

  // Current page indicator
  const currentLi = document.createElement('li');
  currentLi.className = 'active';
  currentLi.innerHTML = `<a href="#">${page} <span class="sr-only">(current)</span></a>`;
  controls.appendChild(currentLi);

  // Next button
  const nextLi = document.createElement('li');
  nextLi.className = hasNext ? '' : 'disabled';
  const nextA = document.createElement('a');
  nextA.href = '#';
  nextA.setAttribute('aria-label', 'Next');
  nextA.innerHTML = '<span aria-hidden="true">&raquo;</span>';
  if (hasNext) {
    nextA.addEventListener('click', function (e) {
      e.preventDefault();
      loadUsers(page + 1);
    });
  }
  nextLi.appendChild(nextA);
  controls.appendChild(nextLi);
}

// ---------------------------------------------------------------------------
// Create User
// ---------------------------------------------------------------------------

/**
 * Handle the create-user form submission.
 *
 * @param {Event} e
 */
async function handleCreateUser(e) {
  e.preventDefault();
  hideCreateError();

  const usernameEl = document.getElementById('new-username');
  const passwordEl = document.getElementById('new-password');
  const roleEl     = document.getElementById('new-role');
  const submitBtn  = document.getElementById('create-btn');

  const username = usernameEl.value.trim();
  const password = passwordEl.value;
  const role     = roleEl.value;

  // Client-side validation
  if (!username) {
    showCreateError('Username is required.');
    usernameEl.focus();
    return;
  }

  if (!password || password.length < 8 || password.length > 128) {
    showCreateError('Password must be between 8 and 128 characters.');
    passwordEl.focus();
    return;
  }

  if (!role) {
    showCreateError('Please select a role.');
    roleEl.focus();
    return;
  }

  submitBtn.disabled = true;
  submitBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Creating…';

  try {
    await apiFetch('/api/v1/users', {
      method: 'POST',
      body: JSON.stringify({ username, password, role }),
    });

    // Reset form
    usernameEl.value = '';
    passwordEl.value = '';
    roleEl.value = '';

    showPageSuccess(`User "${username}" created successfully.`);

    // Reload the list to show the new user
    loadUsers(currentPage);

  } catch (err) {
    if (err.status === 409) {
      showCreateError(`Username "${username}" is already taken.`);
    } else {
      showCreateError(err.message || 'Failed to create user.');
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = '<i class="fa fa-plus"></i> Create User';
  }
}

// ---------------------------------------------------------------------------
// Update Role Modal
// ---------------------------------------------------------------------------

/**
 * Open the role-update modal pre-populated with the user's current role.
 *
 * @param {string} userId    UUID of the user to update.
 * @param {string} username  Display name.
 * @param {string} role      Current role value.
 */
function openRoleModal(userId, username, role) {
  targetUserId   = userId;
  targetUsername = username;

  document.getElementById('role-modal-username').textContent = username;
  document.getElementById('role-modal-select').value = role;
  hideModalError('role-modal-error');

  $('#role-modal').modal('show');
}

/**
 * Handle the Save Role button inside the role modal.
 */
async function handleUpdateRole() {
  if (!targetUserId) return;

  const newRole  = document.getElementById('role-modal-select').value;
  const saveBtn  = document.getElementById('role-modal-save');

  hideModalError('role-modal-error');
  saveBtn.disabled = true;
  saveBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Saving…';

  try {
    await apiFetch(`/api/v1/users/${targetUserId}`, {
      method: 'PATCH',
      body: JSON.stringify({ role: newRole }),
    });

    $('#role-modal').modal('hide');
    showPageSuccess(
      `Role for "${targetUsername}" updated to ${capitalize(newRole)}.`
    );
    loadUsers(currentPage);

  } catch (err) {
    showModalError('role-modal-error', 'role-modal-error-msg',
      err.message || 'Failed to update role.');
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = '<i class="fa fa-save"></i> Save Role';
  }
}

// ---------------------------------------------------------------------------
// Deactivate Modal
// ---------------------------------------------------------------------------

/**
 * Open the deactivate-confirmation modal.
 *
 * @param {string} userId    UUID of the user to deactivate.
 * @param {string} username  Display name.
 */
function openDeactivateModal(userId, username) {
  targetUserId   = userId;
  targetUsername = username;

  document.getElementById('deactivate-modal-username').textContent = username;
  hideModalError('deactivate-modal-error');

  $('#deactivate-modal').modal('show');
}

/**
 * Handle the Deactivate confirm button inside the deactivate modal.
 */
async function handleDeactivate() {
  if (!targetUserId) return;

  const confirmBtn = document.getElementById('deactivate-modal-confirm');

  hideModalError('deactivate-modal-error');
  confirmBtn.disabled = true;
  confirmBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Deactivating…';

  try {
    await apiFetch(`/api/v1/users/${targetUserId}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: false }),
    });

    $('#deactivate-modal').modal('hide');
    showPageSuccess(`User "${targetUsername}" has been deactivated.`);
    loadUsers(currentPage);

  } catch (err) {
    showModalError('deactivate-modal-error', 'deactivate-modal-error-msg',
      err.message || 'Failed to deactivate user.');
  } finally {
    confirmBtn.disabled = false;
    confirmBtn.innerHTML = '<i class="fa fa-ban"></i> Deactivate';
  }
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/** Show or hide the table-loading spinner. */
function showTableLoading(visible) {
  const el = document.getElementById('users-loading');
  if (!el) return;
  if (visible) {
    el.classList.remove('hidden');
    const wrap  = document.getElementById('users-table-wrap');
    const empty = document.getElementById('users-empty');
    if (wrap)  wrap.classList.add('hidden');
    if (empty) empty.classList.add('hidden');
  } else {
    el.classList.add('hidden');
  }
}

/** Show a page-level error banner. */
function showPageError(msg) {
  const errDiv = document.getElementById('page-error');
  const errMsg = document.getElementById('page-error-msg');
  if (!errDiv || !errMsg) return;
  errMsg.textContent = msg;
  errDiv.classList.remove('hidden');
  document.getElementById('page-success').classList.add('hidden');
}

/** Show a page-level success banner and auto-hide after 4 s. */
function showPageSuccess(msg) {
  const succDiv = document.getElementById('page-success');
  const succMsg = document.getElementById('page-success-msg');
  if (!succDiv || !succMsg) return;
  succMsg.textContent = msg;
  succDiv.classList.remove('hidden');
  document.getElementById('page-error').classList.add('hidden');

  setTimeout(function () {
    succDiv.classList.add('hidden');
  }, 4000);
}

/** Hide both page-level banners. */
function hidePageMessages() {
  document.getElementById('page-error').classList.add('hidden');
  document.getElementById('page-success').classList.add('hidden');
}

/** Show the inline create-form error. */
function showCreateError(msg) {
  const errDiv = document.getElementById('create-error');
  const errMsg = document.getElementById('create-error-msg');
  if (!errDiv || !errMsg) return;
  errMsg.textContent = msg;
  errDiv.classList.remove('hidden');
}

/** Hide the inline create-form error. */
function hideCreateError() {
  const errDiv = document.getElementById('create-error');
  if (errDiv) errDiv.classList.add('hidden');
}

/**
 * Show an error inside a Bootstrap modal.
 *
 * @param {string} alertId  ID of the alert div.
 * @param {string} msgId    ID of the message span.
 * @param {string} msg      Error message text.
 */
function showModalError(alertId, msgId, msg) {
  const alertEl = document.getElementById(alertId);
  const msgEl   = document.getElementById(msgId);
  if (!alertEl || !msgEl) return;
  msgEl.textContent = msg;
  alertEl.classList.remove('hidden');
}

/**
 * Hide an error alert inside a Bootstrap modal.
 *
 * @param {string} alertId  ID of the alert div.
 */
function hideModalError(alertId) {
  const alertEl = document.getElementById(alertId);
  if (alertEl) alertEl.classList.add('hidden');
}

/**
 * Capitalise the first letter of a string.
 *
 * @param {string} str
 * @returns {string}
 */
function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}
