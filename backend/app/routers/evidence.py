"""
Evidence file router — upload, download, and delete evidence attached to findings.

Routes
------
POST   /api/v1/evidence/{finding_id}/upload    — upload a file to a finding
GET    /api/v1/evidence/{evidence_id}/download  — download an evidence file
DELETE /api/v1/evidence/{evidence_id}           — delete an evidence file

Security
--------
- All routes require authentication (get_current_user).
- Upload: authenticated users with access to the parent finding's engagement
  (lead/admin always; operator only if assigned to the engagement).
- Download: authenticated users with access to the parent finding's engagement
  (same rules as upload).
- Delete: lead/admin always; operators only if assigned to the engagement.

Business rules enforced
-----------------------
- Maximum 25 evidence files per finding — 400 if exceeded (Requirement 6.1).
- Maximum 50 MB per file — 413 if exceeded (Requirement 6.2).
- MIME type whitelist — 415 if not permitted (Requirement 6.3, 6.4).
- Stored filename format: {evidence_id}_{original_filename} (Requirement 6.1).
- Path-traversal prevention via file_service.safe_write (Requirement 6.6).
- Standalone delete: log filesystem failure but continue deleting the DB
  record (Requirement 6.7).
- Download: serve with Content-Type + Content-Disposition attachment (Req 6.5).
- Download: 404 if file is not on the filesystem (Requirement 6.5).
- All write actions logged via log_service (Requirement 7.1).

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_session_db
from app.models.engagement import EngagementOperator
from app.models.evidence import EvidenceFile
from app.models.finding import Finding
from app.models.user import User
from app.schemas.evidence import EvidenceResponse
from app.services.file_service import safe_delete, safe_write
from app.services.log_service import record_log

logger = logging.getLogger("redboard.evidence")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/evidence", tags=["evidence"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_MAX_FILES_PER_FINDING = 25
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Permitted MIME types (Requirement 6.3)
_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "application/pdf",
        "text/plain",
        "application/octet-stream",
    }
)


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------


async def _get_finding_or_404(
    finding_id: uuid.UUID,
    db: AsyncSession,
) -> Finding:
    """Fetch a finding by ID or raise 404."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if finding is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "FINDING_NOT_FOUND",
                "message": f"No finding found with ID '{finding_id}'.",
            },
        )
    return finding


async def _get_evidence_or_404(
    evidence_id: uuid.UUID,
    db: AsyncSession,
) -> EvidenceFile:
    """Fetch an evidence record by ID or raise 404."""
    result = await db.execute(
        select(EvidenceFile).where(EvidenceFile.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    if evidence is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "EVIDENCE_NOT_FOUND",
                "message": f"No evidence file found with ID '{evidence_id}'.",
            },
        )
    return evidence


async def _assert_authorized_for_finding(
    user: User,
    finding: Finding,
    db: AsyncSession,
) -> None:
    """
    Raise 403 if *user* is not authorised to access the given finding.

    Authorization rules (Requirement 6.5, Requirement 2.5, 2.6, 2.7):
    - admin:    always authorized.
    - lead:     always authorized.
    - operator: only if assigned to the finding's parent engagement.
    """
    if user.role in ("lead", "admin"):
        return

    # Operator: must be assigned to the engagement
    result = await db.execute(
        select(EngagementOperator).where(
            EngagementOperator.engagement_id == finding.engagement_id,
            EngagementOperator.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "message": (
                    "You are not assigned to the engagement that contains this "
                    "finding and cannot access its evidence files."
                ),
            },
        )


# ---------------------------------------------------------------------------
# GET /evidence/{finding_id}/files — list evidence for a finding
# ---------------------------------------------------------------------------


@router.get(
    "/{finding_id}/files",
    response_model=list[EvidenceResponse],
    summary="List evidence files for a finding",
    responses={
        200: {"description": "List of evidence file metadata for the finding"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized to access this finding"},
        404: {"description": "Finding not found"},
    },
)
async def list_evidence_files(
    finding_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> list[EvidenceFile]:
    """
    Return all evidence files attached to a finding.

    Authorization rules match the upload/download endpoints: admin and lead
    users are always authorised; operators must be assigned to the finding's
    parent engagement.
    """
    finding = await _get_finding_or_404(finding_id, db)
    await _assert_authorized_for_finding(current_user, finding, db)

    result = await db.execute(
        select(EvidenceFile)
        .where(EvidenceFile.finding_id == finding_id)
        .order_by(EvidenceFile.uploaded_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# POST /evidence/{finding_id}/upload
# ---------------------------------------------------------------------------


@router.post(
    "/{finding_id}/upload",
    response_model=EvidenceResponse,
    status_code=201,
    summary="Upload an evidence file to a finding",
    responses={
        201: {"description": "Evidence file uploaded and metadata persisted"},
        400: {"description": "Finding already has 25 evidence files"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized to access this finding"},
        404: {"description": "Finding not found"},
        413: {"description": "File exceeds the 50 MB size limit"},
        415: {"description": "MIME type not in permitted list"},
    },
)
async def upload_evidence(
    finding_id: uuid.UUID,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> EvidenceFile:
    """
    Upload an evidence file and attach it to an existing finding.

    Enforces
    --------
    - Max 25 files per finding (400) — Requirement 6.1.
    - Max 50 MB per file (413) — Requirement 6.2.
    - MIME whitelist (415) — Requirements 6.3, 6.4.
    - Path-traversal prevention — Requirement 6.6.
    - Stored filename: ``{evidence_id}_{original_filename}``.
    - Logs ``evidence_uploaded`` — Requirement 7.1.
    """
    finding = await _get_finding_or_404(finding_id, db)

    # Authorization check (Requirement 6.5 / 2.7)
    await _assert_authorized_for_finding(current_user, finding, db)

    # ------------------------------------------------------------------
    # Check 25-file limit (Requirement 6.1)
    # ------------------------------------------------------------------
    count_result = await db.execute(
        select(func.count()).select_from(EvidenceFile).where(
            EvidenceFile.finding_id == finding_id
        )
    )
    current_count: int = count_result.scalar_one()
    if current_count >= _MAX_FILES_PER_FINDING:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EVIDENCE_LIMIT_EXCEEDED",
                "message": (
                    f"This finding already has {_MAX_FILES_PER_FINDING} evidence "
                    f"files (the maximum). Delete an existing file before uploading."
                ),
                "detail": {
                    "finding_id": str(finding_id),
                    "limit": _MAX_FILES_PER_FINDING,
                    "current_count": current_count,
                },
            },
        )

    # ------------------------------------------------------------------
    # MIME type check (Requirements 6.3, 6.4)
    # ------------------------------------------------------------------
    content_type: str = file.content_type or "application/octet-stream"
    # Normalise: strip parameters (e.g. "text/plain; charset=utf-8" → "text/plain")
    mime_base = content_type.split(";")[0].strip().lower()
    if mime_base not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail={
                "error_code": "UNSUPPORTED_MEDIA_TYPE",
                "message": (
                    f"MIME type '{mime_base}' is not permitted. "
                    f"Allowed types: {', '.join(sorted(_ALLOWED_MIME_TYPES))}."
                ),
                "detail": {
                    "received_mime_type": mime_base,
                    "allowed_mime_types": sorted(_ALLOWED_MIME_TYPES),
                },
            },
        )

    # ------------------------------------------------------------------
    # Read file content and enforce 50 MB limit (Requirement 6.2)
    # ------------------------------------------------------------------
    file_data: bytes = await file.read()
    file_size = len(file_data)

    if file_size > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error_code": "PAYLOAD_TOO_LARGE",
                "message": (
                    f"File size {file_size:,} bytes exceeds the 50 MB limit "
                    f"({_MAX_FILE_SIZE_BYTES:,} bytes)."
                ),
                "detail": {
                    "file_size_bytes": file_size,
                    "max_size_bytes": _MAX_FILE_SIZE_BYTES,
                },
            },
        )

    # ------------------------------------------------------------------
    # Persist DB record first so we have the evidence UUID for the filename
    # ------------------------------------------------------------------
    original_filename = file.filename or "unknown"

    # Sanitise filename — strip path components to avoid traversal in the
    # original_filename field itself (the stored_filename uses UUID prefix)
    original_filename = Path(original_filename).name or "unknown"

    evidence = EvidenceFile(
        finding_id=finding_id,
        original_filename=original_filename,
        stored_filename="",  # filled in after flush gives us the UUID
        file_size_bytes=file_size,
        mime_type=mime_base,
        uploaded_by=current_user.id,
    )
    db.add(evidence)
    await db.flush()          # populates evidence.id
    await db.refresh(evidence)

    # ------------------------------------------------------------------
    # Construct stored filename: {evidence_id}_{original_filename}
    # (Requirement 6.1 / design doc)
    # ------------------------------------------------------------------
    stored_filename = f"{evidence.id}_{original_filename}"
    evidence.stored_filename = stored_filename
    await db.flush()

    # ------------------------------------------------------------------
    # Write file to UPLOAD_DIR (path-traversal check inside safe_write)
    # ------------------------------------------------------------------
    dest_path = os.path.join(settings.UPLOAD_DIR, stored_filename)
    try:
        safe_write(dest_path, file_data)
    except (ValueError, OSError) as exc:
        logger.error(
            "Failed to write evidence file '%s': %s",
            dest_path,
            exc,
        )
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "STORAGE_ERROR",
                "message": "Failed to write the evidence file to storage.",
                "detail": {"error": str(exc)},
            },
        )

    # ------------------------------------------------------------------
    # Audit log (Requirement 7.1)
    # ------------------------------------------------------------------
    await record_log(
        db=db,
        action_type="evidence_uploaded",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' uploaded evidence file "
            f"'{original_filename}' ({file_size:,} bytes) to finding '{finding_id}'."
        ),
        engagement_id=finding.engagement_id,
        target_entity_type="evidence",
        target_entity_id=evidence.id,
    )

    await db.commit()
    await db.refresh(evidence)

    logger.info(
        "Evidence '%s' (%s) uploaded by '%s' to finding '%s'",
        original_filename,
        evidence.id,
        current_user.username,
        finding_id,
    )
    return evidence


# ---------------------------------------------------------------------------
# GET /evidence/{evidence_id}/download
# ---------------------------------------------------------------------------


@router.get(
    "/{evidence_id}/download",
    summary="Download an evidence file",
    responses={
        200: {
            "description": "File content with Content-Type and Content-Disposition headers"
        },
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized to access this finding's evidence"},
        404: {"description": "Evidence record not found or file not on filesystem"},
    },
)
async def download_evidence(
    evidence_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> FileResponse:
    """
    Download an evidence file.

    - Verifies the requesting user is authenticated and authorised to access
      the parent finding (Requirement 6.5).
    - Serves the file with ``Content-Type`` and
      ``Content-Disposition: attachment; filename=<original_filename>`` headers.
    - Returns 404 if the DB record exists but the file is absent from the
      filesystem (Requirement 6.5).
    """
    evidence = await _get_evidence_or_404(evidence_id, db)

    # Fetch parent finding for authorization check
    finding = await _get_finding_or_404(evidence.finding_id, db)

    # Authorization check (Requirement 6.5)
    await _assert_authorized_for_finding(current_user, finding, db)

    # Resolve the physical path
    file_path = os.path.join(settings.UPLOAD_DIR, evidence.stored_filename)

    if not os.path.isfile(file_path):
        logger.warning(
            "Evidence file not found on filesystem: %s (evidence_id=%s)",
            file_path,
            evidence_id,
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "FILE_NOT_FOUND",
                "message": (
                    f"Evidence file '{evidence.original_filename}' is not available "
                    "on the server filesystem."
                ),
                "detail": {"evidence_id": str(evidence_id)},
            },
        )

    logger.info(
        "Evidence '%s' (%s) downloaded by '%s'",
        evidence.original_filename,
        evidence_id,
        current_user.username,
    )

    return FileResponse(
        path=file_path,
        media_type=evidence.mime_type,
        filename=evidence.original_filename,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{evidence.original_filename}"'
            ),
        },
    )


# ---------------------------------------------------------------------------
# DELETE /evidence/{evidence_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{evidence_id}",
    status_code=204,
    response_model=None,
    summary="Delete an evidence file",
)
async def delete_evidence(
    evidence_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> None:
    """
    Delete an evidence file.

    Requirement 6.7 (standalone delete, not via finding-delete):
    - Attempt to delete the file from the filesystem.
    - If the filesystem deletion fails, **log the failure and continue** —
      the DB record is still deleted.
    - This differs from finding-delete (Requirement 5.9), which aborts on
      filesystem failure.
    - Logs ``evidence_deleted`` (Requirement 7.1).
    """
    evidence = await _get_evidence_or_404(evidence_id, db)

    # Fetch parent finding for authorization check
    finding = await _get_finding_or_404(evidence.finding_id, db)

    # Authorization check
    await _assert_authorized_for_finding(current_user, finding, db)

    # Capture metadata before deletion for logging
    original_filename = evidence.original_filename
    finding_id = evidence.finding_id
    engagement_id = finding.engagement_id

    # ------------------------------------------------------------------
    # Filesystem delete — log failure and continue (Requirement 6.7)
    # ------------------------------------------------------------------
    file_path = os.path.join(settings.UPLOAD_DIR, evidence.stored_filename)
    fs_ok = safe_delete(file_path, logger)
    if not fs_ok:
        logger.warning(
            "Filesystem delete failed for evidence '%s' (%s); "
            "proceeding with DB record deletion per Requirement 6.7.",
            original_filename,
            evidence_id,
        )

    # ------------------------------------------------------------------
    # Delete DB record regardless of filesystem outcome (Requirement 6.7)
    # ------------------------------------------------------------------
    await db.delete(evidence)

    # Audit log (Requirement 7.1)
    await record_log(
        db=db,
        action_type="evidence_deleted",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' deleted evidence file "
            f"'{original_filename}' from finding '{finding_id}'."
        ),
        engagement_id=engagement_id,
        target_entity_type="evidence",
        target_entity_id=evidence_id,
    )

    await db.commit()

    logger.info(
        "Evidence '%s' (%s) deleted by '%s' (filesystem_ok=%s)",
        original_filename,
        evidence_id,
        current_user.username,
        fs_ok,
    )
