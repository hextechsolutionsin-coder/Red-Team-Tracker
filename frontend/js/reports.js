/**
 * reports.js — PDF report download helper for RedBoard.
 *
 * Provides `downloadReport(engagementId, [buttonEl])` which calls the backend
 * report endpoint and triggers a browser file download via a blob URL.
 *
 * Depends on: api.js (must be loaded before this file).
 *
 * Requirements: 9.1, 9.3, 9.4
 */

'use strict';

/**
 * Download the PDF report for a given engagement.
 *
 * Calls GET /api/v1/reports/{engagementId} with credentials included, reads
 * the response as a Blob, creates a temporary object URL, and programmatically
 * clicks a hidden <a> element to trigger the browser's download dialog.
 *
 * @param {string} engagementId - UUID of the engagement to generate a report for.
 * @param {HTMLElement} [buttonEl] - Optional button element to disable during download
 *                                   (prevents double-clicks). Re-enabled on completion.
 * @returns {Promise<void>}
 */
async function downloadReport(engagementId, buttonEl) {
  if (!engagementId) {
    console.error('downloadReport: engagementId is required');
    return;
  }

  // Disable the triggering button to prevent duplicate requests while the
  // server is generating the PDF (can take several seconds for large reports).
  var originalLabel = null;
  if (buttonEl) {
    originalLabel        = buttonEl.innerHTML;
    buttonEl.disabled    = true;
    buttonEl.innerHTML   = '<i class="fa fa-spinner fa-spin"></i> Generating…';
  }

  function restoreButton() {
    if (buttonEl) {
      buttonEl.disabled  = false;
      buttonEl.innerHTML = originalLabel;
    }
  }

  // The report endpoint streams a binary PDF, so we bypass apiFetch (which
  // expects JSON) and call fetch() directly with credentials.
  let response;
  try {
    response = await fetch('/api/v1/reports/' + encodeURIComponent(engagementId), {
      credentials: 'include',
    });
  } catch (networkError) {
    restoreButton();
    alert('Network error while generating report: ' + networkError.message);
    return;
  }

  // Session expired
  if (response.status === 401) {
    sessionStorage.removeItem('currentUser');
    window.location.replace('/index.html');
    return;
  }

  if (!response.ok) {
    restoreButton();
    // Try to read a JSON error body
    let msg = 'Failed to generate report (HTTP ' + response.status + ').';
    try {
      const errorBody = await response.json();
      if (errorBody && errorBody.message) {
        msg = errorBody.message;
      }
    } catch (_) { /* ignore parse errors */ }
    alert(msg);
    return;
  }

  // Derive filename from Content-Disposition header, falling back to a default.
  let filename = 'engagement-report.pdf';
  const contentDisposition = response.headers.get('content-disposition') || '';
  const filenameMatch = contentDisposition.match(/filename[^;=\n]*=([^;\n]*)/i);
  if (filenameMatch && filenameMatch[1]) {
    filename = filenameMatch[1].trim().replace(/['"]/g, '');
  }

  // Read the PDF bytes and trigger a download via a blob URL.
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href          = objectUrl;
  anchor.download      = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();

  // Clean up after the browser has had a chance to initiate the download.
  setTimeout(function () {
    URL.revokeObjectURL(objectUrl);
    document.body.removeChild(anchor);
  }, 100);

  restoreButton();
}
