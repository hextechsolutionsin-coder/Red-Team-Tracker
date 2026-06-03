"""
Pydantic schemas for the dashboard endpoints.

Requirements: 8.1, 8.2
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SeverityBreakdown(BaseModel):
    """Finding counts keyed by each of the five severity values."""

    Critical: int
    High: int
    Medium: int
    Low: int
    Info: int


class DashboardStatsResponse(BaseModel):
    """
    Aggregated statistics returned by GET /api/v1/dashboard/stats.

    All counts reflect the live database state at the time of the request
    (Requirement 8.1, Property 25).
    """

    active_engagements: int
    open_findings: int
    findings_by_severity: SeverityBreakdown

    model_config = {"from_attributes": True}


class RecentLogEntry(BaseModel):
    """
    A single recent operator log entry returned by
    GET /api/v1/dashboard/recent-logs.

    Contains only the fields required by Requirement 8.2:
    action_type, actor_username, description, and occurred_at.
    """

    action_type: str
    actor_username: str
    description: str
    occurred_at: datetime

    model_config = {"from_attributes": True}
