"""
Pydantic schemas for engagement management endpoints.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EngagementCreate(BaseModel):
    """
    Request body for POST /api/v1/engagements.

    Validates:
    - name: 1–200 chars (Requirement 4.1)
    - description: optional, max 2000 chars
    - scope: optional, max 5000 chars
    - end_date >= start_date (Requirement 4.2)
    - status is always set to "planned" regardless of input (Requirement 4.1)
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Engagement name (1–200 characters)",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional engagement description (max 2000 characters)",
    )
    scope: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional scope definition (max 5000 characters)",
    )
    start_date: date = Field(
        ...,
        description="Engagement start date (ISO 8601)",
    )
    end_date: date = Field(
        ...,
        description="Engagement end date (ISO 8601); must be >= start_date",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "EngagementCreate":
        if self.end_date < self.start_date:
            raise ValueError(
                "end_date must be on or after start_date."
            )
        return self


class EngagementUpdate(BaseModel):
    """
    Request body for PATCH /api/v1/engagements/{id}.

    All fields are optional.  The router enforces:
    - At least one field supplied.
    - Status transitions via engagement_service.validate_transition.
    - Non-status fields rejected for completed/archived engagements (Req 4.9).
    - end_date >= start_date when both or either date is changed.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Engagement name (1–200 characters)",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional engagement description (max 2000 characters)",
    )
    scope: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional scope definition (max 5000 characters)",
    )
    start_date: date | None = Field(
        default=None,
        description="Updated start date",
    )
    end_date: date | None = Field(
        default=None,
        description="Updated end date (must be >= start_date when both supplied)",
    )
    status: str | None = Field(
        default=None,
        description="New status (forward-only transition enforced by service)",
    )


class AssignOperatorsRequest(BaseModel):
    """
    Request body for POST /api/v1/engagements/{id}/operators.

    Validates:
    - operator_ids: non-empty list of user UUIDs to assign
    """

    operator_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        description="List of user IDs to assign as operators to this engagement",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EngagementResponse(BaseModel):
    """
    Outgoing JSON representation of an engagement.

    Includes all engagement fields except internal implementation details.
    """

    id: uuid.UUID
    name: str
    description: str | None
    scope: str | None
    start_date: date
    end_date: date
    status: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
