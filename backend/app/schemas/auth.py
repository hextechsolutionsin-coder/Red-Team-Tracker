"""
Pydantic schemas for the authentication endpoints.

Requirements: 1.1, 1.2, 1.5
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Request body for POST /api/v1/auth/login."""

    username: str = Field(..., min_length=1, max_length=64, description="Account username")
    password: str = Field(..., min_length=1, max_length=128, description="Account password")


class LoginResponse(BaseModel):
    """
    Response body returned on a successful login.

    The session cookie is set separately via the ``Set-Cookie`` header;
    this body carries only the data the frontend needs to personalise the UI.
    """

    role: str = Field(..., description="The authenticated user's role (admin/lead/operator)")
    username: str = Field(..., description="The authenticated user's username")
