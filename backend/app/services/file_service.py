"""
File storage service — safe filesystem write and delete helpers for evidence files.

Provides path-traversal prevention by asserting every resolved path is inside
``UPLOAD_DIR`` before performing any filesystem operation.

Requirements: 6.1, 6.6, 6.7
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_within_upload_dir(path: str | Path) -> None:
    """
    Raise ``ValueError`` if *path* resolves to a location outside ``UPLOAD_DIR``.

    Prevents path-traversal attacks where an attacker might supply a filename
    such as ``../../etc/passwd`` that escapes the upload directory.

    Parameters
    ----------
    path:
        The absolute (or relative-to-cwd) filesystem path that will be used.

    Raises
    ------
    ValueError
        If the resolved path does not start with the canonical UPLOAD_DIR.
    """
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(upload_dir)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{resolved}' is not inside UPLOAD_DIR "
            f"'{upload_dir}'."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def safe_write(dest_path: str | Path, data: bytes) -> None:
    """
    Write *data* to *dest_path* inside ``UPLOAD_DIR``.

    Steps
    -----
    1. Assert *dest_path* is inside ``UPLOAD_DIR`` (path-traversal prevention).
    2. Ensure the parent directory exists (``mkdir -p``).
    3. Write *data* atomically by writing to a temporary sibling file and then
       renaming it — avoids partial writes visible to concurrent readers.

    Parameters
    ----------
    dest_path:
        Target file path.  Must be inside ``UPLOAD_DIR``.
    data:
        Raw bytes to write.

    Raises
    ------
    ValueError
        If *dest_path* is outside ``UPLOAD_DIR``.
    OSError
        On any filesystem error.
    """
    _assert_within_upload_dir(dest_path)

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file, then rename for atomicity
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, dest)
    except Exception:
        # Clean up the temp file if rename fails
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def safe_delete(path: str | Path, logger: logging.Logger) -> bool:
    """
    Delete the file at *path* inside ``UPLOAD_DIR``.

    Logs a warning if the file is not found (idempotent: treated as success).
    Logs an error and returns ``False`` on any other filesystem error so the
    caller can decide whether to continue or abort.

    Used by the standalone evidence-delete endpoint (Requirement 6.7): the
    router logs the failure and continues deleting the DB record regardless.
    Used by the finding-delete endpoint where the caller performs its own
    abort-on-failure logic (Requirement 5.9).

    Parameters
    ----------
    path:
        File path to delete.  Must be inside ``UPLOAD_DIR``.
    logger:
        Caller-supplied logger instance.

    Returns
    -------
    bool
        ``True`` if deletion succeeded (or file was already absent),
        ``False`` on unexpected error.

    Raises
    ------
    ValueError
        If *path* is outside ``UPLOAD_DIR`` (always raised; not suppressed).
    """
    _assert_within_upload_dir(path)

    try:
        os.remove(path)
        logger.debug("Deleted file from filesystem: %s", path)
        return True
    except FileNotFoundError:
        logger.warning("File not found during delete (already removed?): %s", path)
        return True  # idempotent — treating as success
    except OSError as exc:
        logger.error("Failed to delete file '%s': %s", path, exc)
        return False
