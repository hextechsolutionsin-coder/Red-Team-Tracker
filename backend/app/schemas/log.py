"""
Pydantic schemas for the operator log endpoints.

Requirements: 7.1, 7.2, 7.3, 7.5, 7.6
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class OperatorLogResponse(BaseModel):
    """
    Outgoing JSON representation of a single operator log entry.

    All fields are read-only — the log is append-only and no mutation
    endpoints are exposed (Requirement 7.4).
    """

    id: uuid.UUID
    action_type: str
    actor_username: str
    engagement_id: uuid.UUID | None
    target_entity_type: str | None
    target_entity_id: uuid.UUID | None
    description: str
    occurred_at: datetime

    model_config = {"from_attributes": True}
