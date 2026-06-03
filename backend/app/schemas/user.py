"""
Pydantic schemas for user management endpoints.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Allowed roles
# ---------------------------------------------------------------------------

VALID_ROLES = {"admin", "lead", "operator"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """
    Request body for POST /api/v1/users.

    Validates:
    - username: 1–64 chars (unique enforced at DB level, 409 raised in router)
    - password: 8–128 chars (Requirement 3.4)
    - role: one of admin / lead / operator (Requirement 3.1)
    """

    username: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique account username (1–64 characters)",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password (8–128 characters); stored as bcrypt hash",
    )
    role: str = Field(
        ...,
        description="User role: admin, lead, or operator",
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{value}'. Must be one of: {', '.join(sorted(VALID_ROLES))}."
            )
        return value


class UserUpdate(BaseModel):
    """
    Request body for PATCH /api/v1/users/{user_id}.

    All fields are optional; at least one must be supplied (enforced in router).

    Allows updating:
    - role: change the user's role (Requirement 3.7)
    - is_active: deactivate the user (Requirement 3.5)
    """

    role: str | None = Field(
        default=None,
        description="New role for the user: admin, lead, or operator",
    )
    is_active: bool | None = Field(
        default=None,
        description="Set to false to deactivate the user account",
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{value}'. Must be one of: {', '.join(sorted(VALID_ROLES))}."
            )
        return value


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """
    Outgoing JSON representation of a user account.

    Excludes password_hash and other sensitive fields (Requirement 3.6).
    """

    id: uuid.UUID
    username: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}
