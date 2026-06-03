/**
 * api.js — Shared fetch wrapper for the RedBoard frontend.
 *
 * Every API call goes through `apiFetch`. It:
 *   1. Attaches `credentials: 'include'` so the session cookie is sent automatically.
 *   2. Detects 401 responses and redirects the browser to the login page.
 *   3. Parses JSON error bodies (error_code + message) and throws them as AppError instances.
 */

'use strict';

/**
 * Structured error thrown for non-2xx API responses.
 * @property {string} errorCode  - Machine-readable code from the API (e.g. "FORBIDDEN").
 * @property {string} message    - Human-readable description.
 * @property {number} status     - HTTP status code.
 * @property {object} detail     - Optional field-level detail from the API.
 */
class AppError extends Error {
  /**
   * @param {string} message
   * @param {string} errorCode
   * @param {number} status
   * @param {object} [detail]
   */
  constructor(message, errorCode, status, detail) {
    super(message);
    this.name      = 'AppError';
    this.errorCode = errorCode || 'UNKNOWN_ERROR';
    this.status    = status    || 0;
    this.detail    = detail    || {};
  }
}

/**
 * Make an authenticated API request.
 *
 * @param {string} path     - Path relative to the API root, e.g. '/api/v1/users'.
 * @param {RequestInit} [options] - Standard fetch options (method, body, headers, …).
 * @returns {Promise<any>}  - Parsed JSON body on success (undefined for 204).
 * @throws {AppError}       - On any non-2xx response.
 */
async function apiFetch(path, options) {
  const opts = Object.assign({}, options);

  // Always send the session cookie
  opts.credentials = 'include';

  // Default to JSON content-type when a body is present and no content-type is set
  if (opts.body && typeof opts.body === 'string') {
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  }

  let response;
  try {
    response = await fetch(path, opts);
  } catch (networkError) {
    throw new AppError(
      'Network error — unable to reach the server.',
      'NETWORK_ERROR',
      0,
      { originalError: networkError.message }
    );
  }

  // Session expired or not authenticated → send to login
  if (response.status === 401) {
    sessionStorage.removeItem('currentUser');
    window.location.replace('/index.html');
    // Throw so that any awaiting caller does not continue processing
    throw new AppError('Session expired. Redirecting to login.', 'UNAUTHORIZED', 401);
  }

  // 204 No Content — nothing to parse
  if (response.status === 204) {
    return undefined;
  }

  // Attempt to parse the response body as JSON
  let body;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      body = await response.json();
    } catch (_) {
      body = null;
    }
  }

  // Successful response
  if (response.ok) {
    return body;
  }

  // Error response — turn the JSON error envelope into an AppError
  if (body && (body.error_code || body.message)) {
    throw new AppError(
      body.message || 'An error occurred.',
      body.error_code || 'API_ERROR',
      response.status,
      body.detail || {}
    );
  }

  // Fall-back for non-JSON or unexpected error shapes
  throw new AppError(
    `HTTP ${response.status}: ${response.statusText}`,
    'HTTP_ERROR',
    response.status
  );
}
