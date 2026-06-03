/**
 * evidence.js — Evidence file management helpers for RedBoard.
 *
 * Provides three functions consumed by finding-detail.html:
 *   - uploadEvidence(findingId, file)    → POST /api/v1/evidence/{finding_id}/upload
 *   - downloadEvidence(evidenceId)       → GET  /api/v1/evidence/{evidence_id}/download
 *   - deleteEvidence(evidenceId)         → DELETE /api/v1/evidence/{evidence_id}
 *
 * Depends on: api.js (must be loaded before this file).
 *
 * Requirements: 6.1, 6.3, 6.5
 */

'use strict';

/**
 * Upload a file as evidence for a finding.
 *
 * Uses multipart/form-data so the file bytes are transmitted directly.
 * apiFetch is bypassed here because the request body is FormData, not JSON.
 *
 * @param {string} findingId - UUID of the finding to attach evidence to.
 * @param {File}   file      - The File object selected by the user.
 * @returns {Promise<object>} The EvidenceResponse JSON from the API.
 * @throws {AppError} On any non-2xx response.
 */
async function uploadEvidence(findingId, file) {
  if (!findingId) throw new AppError('findingId is required.', 'BAD_CALL', 0);
  if (!file)     throw new AppError('file is required.',     'BAD_CALL', 0);

  const formData = new FormData();
  formData.append('file', file, file.name);

  let response;
  try {
    response = await fetch(
      '/api/v1/evidence/' + encodeURIComponent(findingId) + '/upload',
      {
        method:      'POST',
        credentials: 'include',
        body:        formData,
        // Do NOT set Content-Type — the browser sets multipart/form-data with boundary automatically
      }
    );
  } catch (networkError) {
    throw new AppError(
      'Network error — unable to upload evidence file.',
      'NETWORK_ERROR',
      0,
      { originalError: networkError.message }
    );
  }

  // Session expired
  if (response.status === 401) {
    sessionStorage.removeItem('currentUser');
    window.location.replace('/index.html');
    throw new AppError('Session expired. Redirecting to login.', 'UNAUTHORIZED', 401);
  }

  // Parse body (success or error)
  let body = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try { body = await response.json(); } catch (_) { body = null; }
  }

  if (response.ok) {
    return body;
  }

  if (body && (body.error_code || body.message)) {
    throw new AppError(
      body.message || 'Upload failed.',
      body.error_code || 'UPLOAD_ERROR',
      response.status,
      body.detail || {}
    );
  }

  throw new AppError(
    'HTTP ' + response.status + ': ' + response.statusText,
    'HTTP_ERROR',
    response.status
  );
}

/**
 * Trigger a browser download for an evidence file.
 *
 * Fetches the binary content from the download endpoint, creates a
 * temporary blob URL, and programmatically clicks a hidden anchor to
 * initiate the browser's save-file dialog.
 *
 * @param {string} evidenceId - UUID of the evidence file to download.
 * @returns {Promise<void>}
 */
async function downloadEvidence(evidenceId) {
  if (!evidenceId) {
    console.error('downloadEvidence: evidenceId is required');
    return;
  }

  let response;
  try {
    response = await fetch(
      '/api/v1/evidence/' + encodeURIComponent(evidenceId) + '/download',
      { credentials: 'include' }
    );
  } catch (networkError) {
    alert('Network error while downloading evidence: ' + networkError.message);
    return;
  }

  // Session expired
  if (response.status === 401) {
    sessionStorage.removeItem('currentUser');
    window.location.replace('/index.html');
    return;
  }

  if (!response.ok) {
    let msg = 'Failed to download evidence (HTTP ' + response.status + ').';
    try {
      const err = await response.json();
      if (err && err.message) msg = err.message;
    } catch (_) { /* ignore */ }
    alert(msg);
    return;
  }

  // Derive filename from Content-Disposition header, falling back to the evidenceId
  let filename = 'evidence-' + evidenceId;
  const contentDisposition = response.headers.get('content-disposition') || '';
  const filenameMatch = contentDisposition.match(/filename[^;=\n]*=([^;\n]*)/i);
  if (filenameMatch && filenameMatch[1]) {
    filename = filenameMatch[1].trim().replace(/['"]/g, '');
  }

  // Read the file bytes and trigger a browser download via blob URL
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href        = objectUrl;
  anchor.download    = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();

  // Clean up after the browser has initiated the download
  setTimeout(function () {
    URL.revokeObjectURL(objectUrl);
    document.body.removeChild(anchor);
  }, 100);
}

/**
 * Delete an evidence file by its ID.
 *
 * Calls DELETE /api/v1/evidence/{evidence_id}.  Returns undefined on
 * success (204 No Content).
 *
 * @param {string} evidenceId - UUID of the evidence file to delete.
 * @returns {Promise<void>}
 * @throws {AppError} On any non-2xx response.
 */
async function deleteEvidence(evidenceId) {
  if (!evidenceId) throw new AppError('evidenceId is required.', 'BAD_CALL', 0);

  return apiFetch('/api/v1/evidence/' + encodeURIComponent(evidenceId), {
    method: 'DELETE',
  });
}
