"""
Finding management router — full CRUD with severity filtering and sorting.

Routes
------
GET    /api/v1/findings                        — paginated list, filter by severity/status/mitre_id
POST   /api/v1/findings                        — create finding (operator for assigned eng, lead/admin any)
GET    /api/v1/findings/{id}                   — get single finding
PATCH  /api/v1/findings/{id}                   — update finding (operators cannot delete)
DELETE /api/v1/findings/{id}  (lead/admin)     — two-phase evidence deletion + finding delete

Security
--------
- All routes require authentication (get_current_user).
- DELETE requires lead or admin role (Requirement 2.6, 2.7).
- Operators may only create/update findings in engagements they are assigned to (Requirement 2.7).

Business rules enforced
-----------------------
- Required fields: title, severity, status, engagement_id (Requirement 5.1).
- severity must be one of Critical/High/Medium/Low/Info (Requirement 5.2).
- status must be one of open/in-progress/remediated/verified (Requirement 5.3).
- MITRE ID pattern: ^T\\d{4,5}$ if supplied (Requirement 5.6).
- page_size max 200 (Requirement 5.8); default 25.
- Finding deletion uses two-phase approach: collect evidence paths → try each FS
  delete → abort entire DB transaction on first failure and return 500 (Requirement 5.9).
- All write actions logged via log_service (Requirement 5.4).

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_session_db, require_role
from app.models.engagement import Engagement, EngagementOperator
from app.models.evidence import EvidenceFile
from app.models.finding import Finding
from app.models.user import User
from app.schemas.finding import (
    VALID_SEVERITIES,
    VALID_STATUSES,
    FindingCreate,
    FindingResponse,
    FindingUpdate,
)
from app.services.finding_service import SEVERITY_ORDER, validate_mitre_id
from app.services.log_service import record_log
from app.services.risk_service import (
    VALID_AFFECTED_ASSET_TYPES,
    VALID_ISO_CONTROLS,
    VALID_NIST_CSF_FUNCTIONS,
    calculate_risk_score,
)

logger = logging.getLogger("redboard.findings")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/findings", tags=["findings"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 200

# SQLAlchemy CASE expression for severity ordering (Critical=1 … Info=5)
_SEVERITY_CASE = case(
    *[
        (Finding.severity == label, weight)
        for label, weight in SEVERITY_ORDER.items()
    ],
    else_=len(SEVERITY_ORDER) + 1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_finding_or_404(
    finding_id: uuid.UUID,
    db: AsyncSession,
) -> Finding:
    """Fetch a finding by ID or raise 404."""
    result = await db.execute(
        select(Finding).where(Finding.id == finding_id)
    )
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


async def _assert_operator_assigned(
    user: User,
    engagement_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Raise 403 if an operator is not assigned to the given engagement.
    Lead and admin users are always allowed through.
    """
    if user.role in ("lead", "admin"):
        return

    result = await db.execute(
        select(EngagementOperator).where(
            EngagementOperator.engagement_id == engagement_id,
            EngagementOperator.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "NOT_ASSIGNED_TO_ENGAGEMENT",
                "message": (
                    "You are not assigned to this engagement and cannot create "
                    "or modify its findings."
                ),
            },
        )


def _validate_severity(severity: str) -> None:
    """Raise 400 if severity is not a valid enum value."""
    if severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_SEVERITY",
                "message": (
                    f"Invalid severity '{severity}'. "
                    f"Must be one of: {', '.join(sorted(VALID_SEVERITIES))}."
                ),
                "detail": {
                    "field": "severity",
                    "valid_values": sorted(VALID_SEVERITIES),
                },
            },
        )


def _validate_status(status: str) -> None:
    """Raise 400 if finding status is not a valid enum value."""
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": (
                    f"Invalid status '{status}'. "
                    f"Must be one of: {', '.join(sorted(VALID_STATUSES))}."
                ),
                "detail": {
                    "field": "status",
                    "valid_values": sorted(VALID_STATUSES),
                },
            },
        )


def _validate_risk_fields(
    likelihood: int | None,
    impact: int | None,
    asset_criticality: int | None,
    affected_asset_type: str | None,
    nist_csf_function: str | None,
    iso_control: str | None,
) -> None:
    """Validate risk scoring fields. Raises 400 on invalid values."""
    for field_name, value in [
        ("likelihood", likelihood),
        ("impact", impact),
        ("asset_criticality", asset_criticality),
    ]:
        if value is not None and (value < 1 or value > 5):
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "INVALID_RISK_FIELD",
                    "message": (
                        f"Invalid {field_name} '{value}'. Must be an integer between 1 and 5."
                    ),
                    "detail": {"field": field_name, "min": 1, "max": 5},
                },
            )

    if affected_asset_type is not None and affected_asset_type not in VALID_AFFECTED_ASSET_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_RISK_FIELD",
                "message": (
                    f"Invalid affected_asset_type '{affected_asset_type}'. "
                    f"Must be one of: {', '.join(sorted(VALID_AFFECTED_ASSET_TYPES))}."
                ),
                "detail": {
                    "field": "affected_asset_type",
                    "valid_values": sorted(VALID_AFFECTED_ASSET_TYPES),
                },
            },
        )

    if nist_csf_function is not None and nist_csf_function not in VALID_NIST_CSF_FUNCTIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_RISK_FIELD",
                "message": (
                    f"Invalid nist_csf_function '{nist_csf_function}'. "
                    f"Must be one of: {', '.join(sorted(VALID_NIST_CSF_FUNCTIONS))}."
                ),
                "detail": {
                    "field": "nist_csf_function",
                    "valid_values": sorted(VALID_NIST_CSF_FUNCTIONS),
                },
            },
        )

    if iso_control is not None and iso_control not in VALID_ISO_CONTROLS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_RISK_FIELD",
                "message": (
                    f"Invalid iso_control '{iso_control}'. "
                    f"Must be one of: {', '.join(sorted(VALID_ISO_CONTROLS))}."
                ),
                "detail": {
                    "field": "iso_control",
                    "valid_values": sorted(VALID_ISO_CONTROLS),
                },
            },
        )


# ---------------------------------------------------------------------------
# GET /findings — paginated list with filtering and sorting
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[FindingResponse],
    summary="List findings (paginated, filterable, sortable)",
    responses={
        200: {"description": "Paginated list of findings"},
        400: {"description": "Invalid pagination or filter parameters"},
        401: {"description": "Not authenticated"},
    },
)
async def list_findings(
    engagement_id: uuid.UUID | None = None,
    severity: str | None = None,
    status: str | None = None,
    mitre_id: str | None = None,
    sort: Literal["severity", "created_at"] = "created_at",
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> list[Finding]:
    """
    Return a paginated list of findings.

    Query params
    ------------
    engagement_id: Filter by engagement UUID.
    severity:      Filter by severity (Critical/High/Medium/Low/Info).
    status:        Filter by status (open/in-progress/remediated/verified).
    mitre_id:      Filter by MITRE technique ID (exact match).
    sort:          "severity" (Critical first) or "created_at" (desc, default).
    page:          1-indexed page number.
    page_size:     Results per page (default 25, max 200).

    Satisfies Requirements 5.8, Property 17.
    """
    # Validate page_size
    if page_size > _MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PAGE_SIZE_TOO_LARGE",
                "message": (
                    f"page_size must not exceed {_MAX_PAGE_SIZE}. "
                    f"Received: {page_size}."
                ),
                "detail": {"field": "page_size", "max": _MAX_PAGE_SIZE},
            },
        )
    if page_size < 1:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "page_size must be at least 1.",
                "detail": {"field": "page_size"},
            },
        )
    if page < 1:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "page must be at least 1.",
                "detail": {"field": "page"},
            },
        )

    # Validate enum filters if supplied
    if severity is not None:
        _validate_severity(severity)
    if status is not None:
        _validate_status(status)

    stmt = select(Finding)

    if engagement_id is not None:
        stmt = stmt.where(Finding.engagement_id == engagement_id)
    if severity is not None:
        stmt = stmt.where(Finding.severity == severity)
    if status is not None:
        stmt = stmt.where(Finding.status == status)
    if mitre_id is not None:
        stmt = stmt.where(Finding.mitre_id == mitre_id)

    # Sorting
    if sort == "severity":
        stmt = stmt.order_by(_SEVERITY_CASE.asc())
    else:
        # Default: created_at descending
        stmt = stmt.order_by(Finding.created_at.desc())

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# POST /findings — create a new finding
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=FindingResponse,
    status_code=201,
    summary="Create a new finding",
    responses={
        201: {"description": "Finding created"},
        400: {"description": "Invalid input (missing fields, invalid enums, bad MITRE ID, engagement not found)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Operator not assigned to engagement"},
    },
)
async def create_finding(
    body: FindingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> Finding:
    """
    Create a new finding.

    Business rules
    --------------
    - All required fields must be present (Requirement 5.1).
    - severity must be a valid enum value (Requirement 5.2).
    - status must be a valid enum value (Requirement 5.3).
    - engagement_id must reference an existing engagement (Requirement 5.1).
    - mitre_id, if supplied, must match ^T\\d{4,5}$ (Requirement 5.6).
    - Operators may only create findings in their assigned engagements (Req 2.7).
    - Logs a ``finding_created`` audit entry (Requirement 5.4).
    """
    # Validate enums
    _validate_severity(body.severity)
    _validate_status(body.status)

    # Validate MITRE ID if supplied
    if body.mitre_id is not None:
        validate_mitre_id(body.mitre_id)

    # Validate risk scoring fields
    _validate_risk_fields(
        body.likelihood,
        body.impact,
        body.asset_criticality,
        body.affected_asset_type,
        body.nist_csf_function,
        body.iso_control,
    )

    # Compute risk score and rating
    risk_score, risk_rating = calculate_risk_score(
        body.likelihood, body.impact, body.asset_criticality
    )

    # Verify engagement exists (Requirement 5.1)
    eng_result = await db.execute(
        select(Engagement).where(Engagement.id == body.engagement_id)
    )
    engagement = eng_result.scalar_one_or_none()
    if engagement is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ENGAGEMENT_NOT_FOUND",
                "message": (
                    f"No engagement found with ID '{body.engagement_id}'. "
                    "A valid engagement_id is required."
                ),
                "detail": {"field": "engagement_id"},
            },
        )

    # Verify operator is assigned to this engagement (Requirement 2.7)
    await _assert_operator_assigned(current_user, body.engagement_id, db)

    finding = Finding(
        engagement_id=body.engagement_id,
        title=body.title,
        severity=body.severity,
        status=body.status,
        mitre_id=body.mitre_id,
        mitre_name=body.mitre_name,
        reproduction_steps=body.reproduction_steps,
        remediation_recs=body.remediation_recs,
        likelihood=body.likelihood,
        impact=body.impact,
        asset_criticality=body.asset_criticality,
        risk_score=risk_score,
        risk_rating=risk_rating,
        affected_asset_type=body.affected_asset_type,
        nist_csf_function=body.nist_csf_function,
        iso_control=body.iso_control,
        created_by=current_user.id,
    )
    db.add(finding)
    await db.flush()
    await db.refresh(finding)

    # Audit log (Requirement 5.4)
    await record_log(
        db=db,
        action_type="finding_created",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' created finding '{finding.title}' "
            f"(severity={finding.severity}) in engagement '{body.engagement_id}'."
        ),
        engagement_id=finding.engagement_id,
        target_entity_type="finding",
        target_entity_id=finding.id,
    )

    await db.commit()
    await db.refresh(finding)
    logger.info(
        "Finding '%s' (%s) created by '%s' in engagement '%s'",
        finding.title,
        finding.id,
        current_user.username,
        finding.engagement_id,
    )
    return finding


# ---------------------------------------------------------------------------
# GET /findings/{id} — get a single finding
# ---------------------------------------------------------------------------


@router.get(
    "/{finding_id}",
    response_model=FindingResponse,
    summary="Get a single finding by ID",
    responses={
        200: {"description": "Finding detail"},
        401: {"description": "Not authenticated"},
        404: {"description": "Finding not found"},
    },
)
async def get_finding(
    finding_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> Finding:
    """
    Retrieve a single finding by its UUID.

    Returns 404 if the finding does not exist.
    """
    return await _get_finding_or_404(finding_id, db)


# ---------------------------------------------------------------------------
# PATCH /findings/{id} — update finding
# ---------------------------------------------------------------------------


@router.patch(
    "/{finding_id}",
    response_model=FindingResponse,
    summary="Update a finding",
    responses={
        200: {"description": "Finding updated"},
        400: {"description": "Invalid input (invalid enums or MITRE ID)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Operator not assigned to engagement"},
        404: {"description": "Finding not found"},
    },
)
async def update_finding(
    finding_id: uuid.UUID,
    body: FindingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> Finding:
    """
    Update a finding.

    Business rules
    --------------
    - At least one field must be supplied.
    - Operators may only update findings in their assigned engagements (Req 2.7).
    - Operators cannot delete findings — that is enforced at the DELETE endpoint.
    - severity, if supplied, must be a valid enum value (Requirement 5.2).
    - status, if supplied, must be a valid enum value (Requirement 5.3).
    - mitre_id, if supplied and non-null, must match ^T\\d{4,5}$ (Requirement 5.6).
    - Logs a ``finding_updated`` audit entry (Requirement 5.4).
    """
    finding = await _get_finding_or_404(finding_id, db)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "At least one field must be supplied.",
            },
        )

    # Verify operator is assigned to the finding's engagement (Requirement 2.7)
    await _assert_operator_assigned(current_user, finding.engagement_id, db)

    # Validate enums if supplied
    if "severity" in update_data:
        _validate_severity(update_data["severity"])
    if "status" in update_data:
        _validate_status(update_data["status"])

    # Validate MITRE ID if supplied and not being explicitly cleared
    if "mitre_id" in update_data and update_data["mitre_id"] is not None:
        validate_mitre_id(update_data["mitre_id"])

    # Validate risk scoring fields if supplied
    _validate_risk_fields(
        update_data.get("likelihood"),
        update_data.get("impact"),
        update_data.get("asset_criticality"),
        update_data.get("affected_asset_type"),
        update_data.get("nist_csf_function"),
        update_data.get("iso_control"),
    )

    # Apply updates
    for field, value in update_data.items():
        setattr(finding, field, value)

    # Recompute risk score if any risk input field was updated or is present
    new_likelihood = finding.likelihood
    new_impact = finding.impact
    new_asset_criticality = finding.asset_criticality
    risk_score, risk_rating = calculate_risk_score(
        new_likelihood, new_impact, new_asset_criticality
    )
    finding.risk_score = risk_score
    finding.risk_rating = risk_rating

    # Update the updated_at timestamp
    finding.updated_at = datetime.now(tz=timezone.utc)

    await db.flush()

    # Audit log (Requirement 5.4)
    await record_log(
        db=db,
        action_type="finding_updated",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' updated finding '{finding.title}' "
            f"({finding_id}) in engagement '{finding.engagement_id}'."
        ),
        engagement_id=finding.engagement_id,
        target_entity_type="finding",
        target_entity_id=finding.id,
    )

    await db.commit()
    await db.refresh(finding)
    logger.info(
        "Finding '%s' (%s) updated by '%s'",
        finding.title,
        finding.id,
        current_user.username,
    )
    return finding


# ---------------------------------------------------------------------------
# DELETE /findings/{id} — delete finding (lead/admin only)
# ---------------------------------------------------------------------------


@router.delete(
    "/{finding_id}",
    status_code=204,
    response_model=None,
    summary="Delete a finding (lead/admin only)",
)
async def delete_finding(
    finding_id: uuid.UUID,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> None:
    """
    Delete a finding and all its evidence files.

    Two-phase evidence deletion (Requirement 5.9, Property 18):
    1. Collect all evidence file records and their filesystem paths from the DB.
    2. Attempt each filesystem deletion.  On the FIRST failure, abort the entire
       DB transaction (finding and all evidence records remain intact) and return 500.
    3. Only if all filesystem deletes succeed, delete evidence DB records, then the
       finding record, and commit.

    Logs ``finding_deleted`` on success (Requirement 5.4).
    """
    finding = await _get_finding_or_404(finding_id, db)

    # -----------------------------------------------------------------------
    # Phase 1: collect all evidence file records for this finding
    # -----------------------------------------------------------------------
    ev_result = await db.execute(
        select(EvidenceFile).where(EvidenceFile.finding_id == finding_id)
    )
    evidence_files: list[EvidenceFile] = list(ev_result.scalars().all())

    # Build full filesystem paths
    evidence_paths: list[tuple[EvidenceFile, str]] = [
        (ev, os.path.join(settings.UPLOAD_DIR, ev.stored_filename))
        for ev in evidence_files
    ]

    # -----------------------------------------------------------------------
    # Phase 2: attempt each filesystem delete — abort entire operation on failure
    # -----------------------------------------------------------------------
    for ev, path in evidence_paths:
        try:
            os.remove(path)
            logger.debug("Deleted evidence file from filesystem: %s", path)
        except OSError as exc:
            # Pre-capture attributes before rollback invalidates the ORM object state
            ev_filename = ev.original_filename
            ev_id = str(ev.id)
            # Filesystem delete failed — do NOT commit; transaction will be rolled back
            logger.error(
                "Failed to delete evidence file '%s' (finding %s): %s",
                path,
                finding_id,
                exc,
            )
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "EVIDENCE_DELETE_FAILED",
                    "message": (
                        f"Failed to delete evidence file '{ev_filename}' "
                        "from the filesystem. The finding and all evidence records "
                        "have been preserved. Please investigate and retry."
                    ),
                    "detail": {
                        "evidence_id": ev_id,
                        "filename": ev_filename,
                        "error": str(exc),
                    },
                },
            )

    # -----------------------------------------------------------------------
    # All filesystem deletes succeeded — now delete DB records and commit
    # -----------------------------------------------------------------------

    # Log before deletion so we can still reference the entity (Requirement 5.4)
    finding_title = finding.title
    finding_engagement_id = finding.engagement_id

    await record_log(
        db=db,
        action_type="finding_deleted",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' deleted finding '{finding_title}' "
            f"({finding_id}) from engagement '{finding_engagement_id}'."
        ),
        engagement_id=finding_engagement_id,
        target_entity_type="finding",
        target_entity_id=finding_id,
    )

    # Delete evidence DB records (finding has RESTRICT constraint, so do these first)
    for ev in evidence_files:
        await db.delete(ev)
    await db.flush()

    # Delete the finding
    await db.delete(finding)
    await db.commit()

    logger.info(
        "Finding '%s' (%s) deleted by '%s' (removed %d evidence file(s))",
        finding_title,
        finding_id,
        current_user.username,
        len(evidence_files),
    )
