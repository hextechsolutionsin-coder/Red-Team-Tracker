"""
Operator log router — read-only access to the audit trail.

Routes
------
GET /api/v1/logs   — paginated log query (lead/admin only)

Security
--------
- Only ``lead`` and ``admin`` roles may query logs (Requirement 7.5).
- Operators receive a 403 Forbidden response.
- No PUT, PATCH, or DELETE routes exist here; the log is append-only
  (Requirement 7.4, Property 23).

Query parameters
----------------
engagement_id : UUID  — filter by engagement (optional)
actor         : str   — filter by actor username (exact match, optional)
action_type   : str   — filter by action type (optional)
sort          : "asc" | "desc"  — sort direction for occurred_at (default "desc")
page          : int   — 1-indexed page number (default 1)
page_size     : int   — results per page (default 50, max 200)

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session_db, require_role
from app.models.log import OperatorLog
from app.models.user import User
from app.schemas.log import OperatorLogResponse

logger = logging.getLogger("redboard.logs")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/logs", tags=["logs"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------------
# GET /logs — paginated, filterable, sortable (lead/admin only)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[OperatorLogResponse],
    summary="List operator log entries (lead/admin only)",
    responses={
        200: {"description": "Paginated list of operator log entries"},
        400: {"description": "Invalid pagination parameters"},
        401: {"description": "Not authenticated"},
        403: {"description": "Lead or admin role required"},
    },
)
async def list_logs(
    engagement_id: uuid.UUID | None = None,
    actor: str | None = None,
    action_type: str | None = None,
    sort: Literal["asc", "desc"] = "desc",
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> list[OperatorLog]:
    """
    Return a paginated list of operator log entries.

    Query params
    ------------
    engagement_id : Filter to entries associated with this engagement UUID.
    actor         : Filter by actor username (exact, case-sensitive match).
    action_type   : Filter by machine-readable action type (e.g. ``finding_created``).
    sort          : Sort direction for ``occurred_at`` — ``"desc"`` (default) or ``"asc"``.
    page          : 1-indexed page number (default 1).
    page_size     : Results per page (default 50, max 200).

    Rejects ``page_size > 200`` with 400 (Requirement 7.5, Property 7).
    Returns 403 for operators (Requirement 7.5, Property 3).
    Satisfies Requirements 7.5, 7.6 and Design Properties 23, 24.
    """
    # ------------------------------------------------------------------
    # Validate pagination parameters
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Build query
    # ------------------------------------------------------------------
    stmt = select(OperatorLog)

    if engagement_id is not None:
        stmt = stmt.where(OperatorLog.engagement_id == engagement_id)
    if actor is not None:
        stmt = stmt.where(OperatorLog.actor_username == actor)
    if action_type is not None:
        stmt = stmt.where(OperatorLog.action_type == action_type)

    # Sort by occurred_at (default: descending — newest first)
    if sort == "asc":
        stmt = stmt.order_by(OperatorLog.occurred_at.asc())
    else:
        stmt = stmt.order_by(OperatorLog.occurred_at.desc())

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    entries = list(result.scalars().all())

    logger.debug(
        "Log query by '%s': engagement_id=%s actor=%s action_type=%s sort=%s "
        "page=%d page_size=%d → %d result(s)",
        current_user.username,
        engagement_id,
        actor,
        action_type,
        sort,
        page,
        page_size,
        len(entries),
    )
    return entries
