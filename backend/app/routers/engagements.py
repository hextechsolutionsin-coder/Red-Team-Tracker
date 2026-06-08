"""
Engagement management router — full CRUD plus operator assignment.

Routes
------
GET    /api/v1/engagements                       — paginated list, filter by status
POST   /api/v1/engagements        (lead/admin)   — create engagement
GET    /api/v1/engagements/{id}                  — get single engagement
PATCH  /api/v1/engagements/{id}   (lead/admin)   — update engagement
DELETE /api/v1/engagements/{id}   (admin only)   — delete engagement (cascade)
POST   /api/v1/engagements/{id}/operators        — assign operator(s)
                                  (lead/admin)

Security
--------
- Create / PATCH requires lead or admin role.
- DELETE requires admin role only.
- Operator assignment requires lead or admin role.

Business rules enforced
-----------------------
- Status transitions are strictly forward-only (engagement_service).
- Non-status fields are frozen for completed/archived engagements (Req 4.9).
- end_date must be >= start_date (Req 4.2).
- New engagements always persist with status "planned" (Req 4.1).
- Only users with role "operator" may be assigned as operators (Req 4.8).
- All write actions are logged via log_service.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_session_db, require_role
from app.models.engagement import Engagement, EngagementOperator
from app.models.user import User
from app.schemas.engagement import (
    AssignOperatorsRequest,
    EngagementCreate,
    EngagementResponse,
    EngagementUpdate,
)
from app.services.engagement_service import is_editable_status, validate_transition
from app.services.log_service import record_log

logger = logging.getLogger("redboard.engagements")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/engagements", tags=["engagements"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100

# Valid engagement statuses
_VALID_STATUSES = {"planned", "active", "on-hold", "remediation", "completed", "reopened", "archived"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_engagement_or_404(
    engagement_id: uuid.UUID,
    db: AsyncSession,
) -> Engagement:
    """Fetch an engagement by ID or raise 404."""
    result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id)
    )
    engagement = result.scalar_one_or_none()
    if engagement is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ENGAGEMENT_NOT_FOUND",
                "message": f"No engagement found with ID '{engagement_id}'.",
            },
        )
    return engagement


# ---------------------------------------------------------------------------
# GET /engagements — paginated list, filter by status, sorted by start_date asc
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[EngagementResponse],
    summary="List engagements (paginated, filterable by status)",
    responses={
        200: {"description": "Paginated list of engagements sorted by start_date asc"},
        400: {"description": "Invalid pagination or filter parameters"},
        401: {"description": "Not authenticated"},
    },
)
async def list_engagements(
    status: str | None = None,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> list[Engagement]:
    """
    Return a paginated list of engagements sorted by start_date ascending.

    Query params
    ------------
    status:    Optional status filter (planned / active / completed / archived).
    page:      Page number (1-indexed, default 1).
    page_size: Number of results per page (default 20, max 100).

    Satisfies Requirements 4.6, Property 12.
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

    # Validate status filter
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": (
                    f"Invalid status filter '{status}'. "
                    f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}."
                ),
                "detail": {"field": "status", "valid_values": sorted(_VALID_STATUSES)},
            },
        )

    stmt = select(Engagement).order_by(Engagement.start_date.asc())
    if status is not None:
        stmt = stmt.where(Engagement.status == status)

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# POST /engagements — create a new engagement (lead/admin)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=EngagementResponse,
    status_code=201,
    summary="Create a new engagement (lead/admin only)",
    responses={
        201: {"description": "Engagement created with status 'planned'"},
        400: {"description": "Invalid input (e.g. end_date before start_date)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Lead or admin role required"},
    },
)
async def create_engagement(
    body: EngagementCreate,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> Engagement:
    """
    Create a new engagement.

    - Status is always set to ``"planned"`` regardless of any status field in
      the request body (Requirement 4.1, Property 8).
    - end_date must be >= start_date (Requirement 4.2, Property 9).
    - Records an ``engagement_created`` audit log entry (Requirement 4.4).
    """
    engagement = Engagement(
        name=body.name,
        description=body.description,
        scope=body.scope,
        start_date=body.start_date,
        end_date=body.end_date,
        status="planned",  # always planned on creation (Requirement 4.1)
        created_by=current_user.id,
    )
    db.add(engagement)
    await db.flush()
    await db.refresh(engagement)

    # Audit log — Requirement 4.4
    await record_log(
        db=db,
        action_type="engagement_created",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' created engagement '{engagement.name}'."
        ),
        engagement_id=engagement.id,
        target_entity_type="engagement",
        target_entity_id=engagement.id,
    )

    await db.commit()
    await db.refresh(engagement)
    logger.info(
        "Engagement '%s' (%s) created by '%s'",
        engagement.name,
        engagement.id,
        current_user.username,
    )
    return engagement


# ---------------------------------------------------------------------------
# GET /engagements/{id} — fetch a single engagement
# ---------------------------------------------------------------------------


@router.get(
    "/{engagement_id}",
    response_model=EngagementResponse,
    summary="Get a single engagement by ID",
    responses={
        200: {"description": "Engagement detail"},
        401: {"description": "Not authenticated"},
        404: {"description": "Engagement not found"},
    },
)
async def get_engagement(
    engagement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> Engagement:
    """
    Retrieve a single engagement by its UUID.

    Returns 404 if the engagement does not exist (Requirement 4.7).
    """
    return await _get_engagement_or_404(engagement_id, db)


# ---------------------------------------------------------------------------
# PATCH /engagements/{id} — update engagement (lead/admin)
# ---------------------------------------------------------------------------


@router.patch(
    "/{engagement_id}",
    response_model=EngagementResponse,
    summary="Update an engagement (lead/admin only)",
    responses={
        200: {"description": "Engagement updated"},
        400: {"description": "Invalid input, invalid status transition, or frozen fields"},
        401: {"description": "Not authenticated"},
        403: {"description": "Lead or admin role required"},
        404: {"description": "Engagement not found"},
    },
)
async def update_engagement(
    engagement_id: uuid.UUID,
    body: EngagementUpdate,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> Engagement:
    """
    Update an engagement.

    Business rules
    --------------
    - Status transitions must be strictly forward-only (Req 4.3, Property 10).
    - Non-status fields are frozen for completed/archived engagements (Req 4.9,
      Property 13).
    - end_date must remain >= start_date after any date update (Req 4.2).
    - Logs ``engagement_status_changed`` when status changes (Req 4.4).
    """
    engagement = await _get_engagement_or_404(engagement_id, db)

    # Check at least one field is provided
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "At least one field must be supplied.",
            },
        )

    # Separate status from non-status fields
    non_status_fields = {k for k in update_data if k != "status"}
    status_change = "status" in update_data

    # Reject non-status edits on completed/archived engagements (Req 4.9)
    if non_status_fields and not is_editable_status(engagement.status):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ENGAGEMENT_NOT_EDITABLE",
                "message": (
                    f"Engagement with status '{engagement.status}' cannot be edited. "
                    "Only status transitions are permitted."
                ),
                "detail": {"field": "status", "current_status": engagement.status},
            },
        )

    # Validate status transition if status is being changed
    if status_change:
        validate_transition(engagement.status, body.status)  # raises 400 on invalid

    # Validate date constraint when dates are being updated
    new_start = body.start_date if body.start_date is not None else engagement.start_date
    new_end = body.end_date if body.end_date is not None else engagement.end_date
    if new_end < new_start:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_DATE_RANGE",
                "message": "end_date must be on or after start_date.",
                "detail": {
                    "field": "end_date",
                    "issue": "must be on or after start_date",
                },
            },
        )

    # Apply updates
    old_status = engagement.status
    for field, value in update_data.items():
        setattr(engagement, field, value)

    await db.flush()

    # Audit log for status change
    if status_change and body.status != old_status:
        await record_log(
            db=db,
            action_type="engagement_status_changed",
            actor_username=current_user.username,
            description=(
                f"User '{current_user.username}' changed engagement "
                f"'{engagement.name}' status from '{old_status}' to '{body.status}'."
            ),
            engagement_id=engagement.id,
            target_entity_type="engagement",
            target_entity_id=engagement.id,
        )

    await db.commit()
    await db.refresh(engagement)
    logger.info(
        "Engagement '%s' (%s) updated by '%s'",
        engagement.name,
        engagement.id,
        current_user.username,
    )
    return engagement


# ---------------------------------------------------------------------------
# DELETE /engagements/{id} — delete engagement (admin only, cascade)
# ---------------------------------------------------------------------------


@router.delete(
    "/{engagement_id}",
    status_code=204,
    response_model=None,
    summary="Delete an engagement (admin only, cascade)",
)
async def delete_engagement(
    engagement_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session_db),
) -> None:
    """
    Delete an engagement and all its child records.

    Cascade delete is handled by the DB schema (ON DELETE CASCADE on findings,
    engagement_operators, and eventually evidence_files via findings).

    Records an ``engagement_deleted`` audit log entry (Requirement 4.4, 4.5).
    """
    engagement = await _get_engagement_or_404(engagement_id, db)

    engagement_name = engagement.name  # capture before deletion

    # Log before deletion so we still have the engagement reference
    await record_log(
        db=db,
        action_type="engagement_deleted",
        actor_username=current_user.username,
        description=(
            f"Admin '{current_user.username}' deleted engagement '{engagement_name}'."
        ),
        engagement_id=engagement.id,
        target_entity_type="engagement",
        target_entity_id=engagement.id,
    )

    await db.delete(engagement)
    await db.commit()

    logger.info(
        "Engagement '%s' (%s) deleted by admin '%s'",
        engagement_name,
        engagement_id,
        current_user.username,
    )


# ---------------------------------------------------------------------------
# POST /engagements/{id}/operators — assign operators (lead/admin)
# ---------------------------------------------------------------------------


@router.post(
    "/{engagement_id}/operators",
    response_model=EngagementResponse,
    summary="Assign operator(s) to an engagement (lead/admin only)",
    responses={
        200: {"description": "Operators assigned; returns updated engagement"},
        400: {"description": "User is not an operator role"},
        401: {"description": "Not authenticated"},
        403: {"description": "Lead or admin role required"},
        404: {"description": "Engagement or user not found"},
    },
)
async def assign_operators(
    engagement_id: uuid.UUID,
    body: AssignOperatorsRequest,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> Engagement:
    """
    Assign one or more operators to an engagement.

    - All supplied user IDs must exist and have role ``"operator"`` (Req 4.8).
    - Returns 400 if any user does not have the ``"operator"`` role.
    - Returns 404 if any user ID is not found.
    - Already-assigned operators are silently skipped (idempotent).
    - Logs an ``operator_assigned`` entry for each newly assigned operator.

    Satisfies Requirements 4.7, 4.8, Property 3 (RBAC on assignment target).
    """
    engagement = await _get_engagement_or_404(engagement_id, db)

    # Fetch all target users in one query
    result = await db.execute(
        select(User).where(User.id.in_(body.operator_ids))
    )
    found_users: list[User] = list(result.scalars().all())
    found_ids = {u.id for u in found_users}

    # Check all requested IDs exist
    missing_ids = [oid for oid in body.operator_ids if oid not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "message": (
                    f"The following user IDs were not found: "
                    f"{', '.join(str(i) for i in missing_ids)}."
                ),
                "detail": {"missing_ids": [str(i) for i in missing_ids]},
            },
        )

    # Check all users have the "operator" role (Requirement 4.8)
    non_operators = [u for u in found_users if u.role != "operator"]
    if non_operators:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "NOT_AN_OPERATOR",
                "message": (
                    "One or more users do not have the 'operator' role and cannot "
                    "be assigned to an engagement: "
                    + ", ".join(
                        f"'{u.username}' (role={u.role})" for u in non_operators
                    )
                    + "."
                ),
                "detail": {
                    "invalid_users": [
                        {"id": str(u.id), "username": u.username, "role": u.role}
                        for u in non_operators
                    ]
                },
            },
        )

    # Fetch existing assignments to avoid duplicates
    existing_result = await db.execute(
        select(EngagementOperator.user_id).where(
            EngagementOperator.engagement_id == engagement.id
        )
    )
    already_assigned: set[uuid.UUID] = set(existing_result.scalars().all())

    # Assign new operators
    newly_assigned: list[User] = []
    for user in found_users:
        if user.id not in already_assigned:
            db.add(
                EngagementOperator(
                    engagement_id=engagement.id,
                    user_id=user.id,
                )
            )
            newly_assigned.append(user)

    await db.flush()

    # Audit log for each newly assigned operator (Requirement 4.4)
    for user in newly_assigned:
        await record_log(
            db=db,
            action_type="operator_assigned",
            actor_username=current_user.username,
            description=(
                f"User '{current_user.username}' assigned operator '{user.username}' "
                f"to engagement '{engagement.name}'."
            ),
            engagement_id=engagement.id,
            target_entity_type="user",
            target_entity_id=user.id,
        )

    await db.commit()
    await db.refresh(engagement)
    logger.info(
        "Assigned %d operator(s) to engagement '%s' (%s) by '%s'",
        len(newly_assigned),
        engagement.name,
        engagement.id,
        current_user.username,
    )
    return engagement
