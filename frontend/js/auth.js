/**
 * auth.js — Authentication helpers for the RedBoard frontend.
 *
 * Depends on api.js being loaded first (uses `apiFetch` and `AppError`).
 *
 * Session-storage key: 'currentUser'
 *   Stores: { username: string, role: 'admin'|'lead'|'operator' }
 */

'use strict';

const AUTH_SESSION_KEY = 'currentUser';

/**
 * Log in with username and password.
 *
 * Calls POST /api/v1/auth/login.
 * On success, caches the returned user info (username + role) in sessionStorage
 * so subsequent pages can read the role without an extra round-trip.
 *
 * @param {string} username
 * @param {string} password
 * @returns {Promise<{username: string, role: string}>} The logged-in user object.
 * @throws {AppError} On invalid credentials or network error.
 */
async function login(username, password) {
  const data = await apiFetch('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });

  // Cache the role so pages can gate UI elements without an extra request
  const user = {
    username: data.username || username,
    role:     data.role,
  };
  sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(user));

  return user;
}

/**
 * Log out the current user.
 *
 * Calls POST /api/v1/auth/logout, then clears the local session-storage cache
 * and redirects the browser to the login page.
 *
 * @returns {Promise<void>}
 */
async function logout() {
  try {
    await apiFetch('/api/v1/auth/logout', { method: 'POST' });
  } finally {
    // Always clear the local cache and redirect, even if the network call fails
    sessionStorage.removeItem(AUTH_SESSION_KEY);
    window.location.replace('/index.html');
  }
}

/**
 * Return the cached current user from sessionStorage, or null if not logged in.
 *
 * This is a synchronous read — no network call is made.
 * The session-storage value is populated by `login()` and cleared by `logout()`.
 *
 * @returns {{ username: string, role: string }|null}
 */
function currentUser() {
  const raw = sessionStorage.getItem(AUTH_SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    sessionStorage.removeItem(AUTH_SESSION_KEY);
    return null;
  }
}

/**
 * Require an authenticated session; redirect to login if not present.
 *
 * Call this at the top of every protected page's inline script:
 *
 *   requireAuth();
 *
 * @returns {{ username: string, role: string }} The current user (never null when it returns).
 */
function requireAuth() {
  const user = currentUser();
  if (!user) {
    window.location.replace('/index.html');
    throw new Error('Not authenticated');
  }
  return user;
}

/**
 * Require a specific role (or one of several roles); redirect to dashboard if not permitted.
 *
 * @param {...string} roles  - Allowed role strings, e.g. requireRole('admin', 'lead').
 * @returns {{ username: string, role: string }}
 */
function requireRole(...roles) {
  const user = requireAuth();
  if (!roles.includes(user.role)) {
    window.location.replace('/dashboard.html');
    throw new Error('Insufficient role');
  }
  return user;
}
