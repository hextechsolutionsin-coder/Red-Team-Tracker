"""
Standardised error response format for the Red Team Operations Tracker API.

All error responses use a consistent JSON structure:

    {
        "error_code": "SCREAMING_SNAKE_CASE",
        "message": "Human-readable description.",
        "detail": {}
    }

Satisfies Requirement 2.9 and Design Property 4.
"""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# AppError — the canonical error response body
# ---------------------------------------------------------------------------


class AppError(BaseModel):
    """
    Machine- and human-readable error payload returned by all error responses.

    Attributes:
        error_code: SCREAMING_SNAKE_CASE identifier for programmatic handling.
        message:    Human-readable explanation of the error.
        detail:     Optional supplementary data (e.g. field-level validation
                    errors).  Defaults to an empty dict.
    """

    error_code: str
    message: str
    detail: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Mapping from HTTP status codes to default error codes
# ---------------------------------------------------------------------------

_STATUS_CODE_MAP: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    500: "INTERNAL_SERVER_ERROR",
}


def _error_code_for_status(status_code: int) -> str:
    """Return a default SCREAMING_SNAKE_CASE error code for an HTTP status."""
    return _STATUS_CODE_MAP.get(status_code, f"HTTP_{status_code}")


# ---------------------------------------------------------------------------
# FastAPI exception handler
# ---------------------------------------------------------------------------


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Serialise any FastAPI/Starlette ``HTTPException`` into the standardised
    ``AppError`` JSON format.

    The handler inspects ``exc.detail``:
    - If it is already an ``AppError`` instance, use it directly.
    - If it is a ``dict`` that contains an ``"error_code"`` key, treat it as
      a pre-built AppError payload.
    - Otherwise use the detail value as the human-readable ``message`` and
      derive a default ``error_code`` from the HTTP status code.
    """
    if isinstance(exc.detail, AppError):
        # Caller raised HTTPException with a fully constructed AppError.
        body = exc.detail
    elif isinstance(exc.detail, dict) and "error_code" in exc.detail:
        # Caller passed a dict with at least an error_code key.
        body = AppError(
            error_code=exc.detail.get("error_code", _error_code_for_status(exc.status_code)),
            message=exc.detail.get("message", str(exc.status_code)),
            detail=exc.detail.get("detail", {}),
        )
    else:
        # Fall back: treat exc.detail (string, None, …) as the message.
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        body = AppError(
            error_code=_error_code_for_status(exc.status_code),
            message=message,
            detail={},
        )

    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=getattr(exc, "headers", None),
    )
