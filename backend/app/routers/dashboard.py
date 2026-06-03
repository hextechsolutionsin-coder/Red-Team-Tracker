"""
Dashboard router — aggregated statistics and recent activity.

Routes
------
GET /api/v1/dashboard/stats        — live counts for the dashboard overview
GET /api/v1/dashboard/recent-logs  — 10 most recent operator log entries

Security
--------
Any authenticated user may access the dashboard (no role restriction beyond
requiring a valid session).

Requirements: 8.1, 8.2
Design Properties: 25, 26
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_session_db
from app.models.engagement import Engagement
from app.models.finding import Finding
from app.models.log import OperatorLog
from app.models.user import User
from app.schemas.dashboard import DashboardStatsResponse, RecentLogEntry, SeverityBreakdown

logger = logging.getLogger("redboard.dashboard")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECENT_LOG_LIMIT = 10
_SEVERITY_VALUES = ("Critical", "High", "Medium", "Low", "Info")


# ---------------------------------------------------------------------------
# GET /dashboard/stats — live aggregated counts (Property 25)
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Get aggregated dashboard statistics",
    responses={
        200: {"description": "Live aggregated counts"},
        401: {"description": "Not authenticated"},
    },
)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> DashboardStatsResponse:
    """
    Return live counts that reflect current database state.

    - ``active_engagements``: number of engagements with status = ``"active"``.
    - ``open_findings``: number of findings with status = ``"open"``.
    - ``findings_by_severity``: finding count for each of the 5 severity values.

    All counts are derived from fresh DB queries on each request (Property 25,
    Requirement 8.1).
    """
    # ------------------------------------------------------------------
    # Active engagement count
    # ------------------------------------------------------------------
    active_stmt = select(func.count()).select_from(Engagement).where(
        Engagement.status == "active"
    )
    active_result = await db.execute(active_stmt)
    active_count: int = active_result.scalar_one()

    # ------------------------------------------------------------------
    # Open finding count
    # ------------------------------------------------------------------
    open_stmt = select(func.count()).select_from(Finding).where(
        Finding.status == "open"
    )
    open_result = await db.execute(open_stmt)
    open_count: int = open_result.scalar_one()

    # ------------------------------------------------------------------
    # Finding counts grouped by severity
    # ------------------------------------------------------------------
    severity_stmt = (
        select(Finding.severity, func.count().label("cnt"))
        .group_by(Finding.severity)
    )
    severity_result = await db.execute(severity_stmt)
    severity_rows = severity_result.all()

    # Build a mapping with defaults of 0 for any severity that has no findings
    severity_map: dict[str, int] = {sev: 0 for sev in _SEVERITY_VALUES}
    for row in severity_rows:
        if row.severity in severity_map:
            severity_map[row.severity] = row.cnt

    breakdown = SeverityBreakdown(
        Critical=severity_map["Critical"],
        High=severity_map["High"],
        Medium=severity_map["Medium"],
        Low=severity_map["Low"],
        Info=severity_map["Info"],
    )

    logger.debug(
        "Dashboard stats requested by '%s': active=%d open=%d severity=%s",
        current_user.username,
        active_count,
        open_count,
        severity_map,
    )

    return DashboardStatsResponse(
        active_engagements=active_count,
        open_findings=open_count,
        findings_by_severity=breakdown,
    )


# ---------------------------------------------------------------------------
# GET /dashboard/recent-logs — 10 most recent log entries (Property 26)
# ---------------------------------------------------------------------------


@router.get(
    "/recent-logs",
    response_model=list[RecentLogEntry],
    summary="Get the 10 most recent operator log entries",
    responses={
        200: {"description": "10 most recent operator log entries"},
        401: {"description": "Not authenticated"},
    },
)
async def get_recent_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session_db),
) -> list[OperatorLog]:
    """
    Return the 10 most recent ``operator_log`` rows ordered by
    ``occurred_at`` descending.

    Each entry contains: ``action_type``, ``actor_username``,
    ``description``, ``occurred_at`` (Property 26, Requirement 8.2).
    """
    stmt = (
        select(OperatorLog)
        .order_by(OperatorLog.occurred_at.desc())
        .limit(_RECENT_LOG_LIMIT)
    )
    result = await db.execute(stmt)
    entries = list(result.scalars().all())

    logger.debug(
        "Recent logs requested by '%s': %d entries returned",
        current_user.username,
        len(entries),
    )

    return entries
