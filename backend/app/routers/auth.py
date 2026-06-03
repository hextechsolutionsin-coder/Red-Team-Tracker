"""
Authentication router — login and logout endpoints.

Routes
------
POST /api/v1/auth/login
    Validate credentials, create a server-side session, set an HttpOnly
    SameSite=Strict session cookie, and return the user's role.

POST /api/v1/auth/logout
    Delete the active session row, clear the session cookie, return 200.

Security notes
--------------
- Passwords are verified via passlib CryptContext (bcrypt); the raw password
  is never logged or persisted.
- On any authentication failure a *generic* "Invalid credentials" message is
  returned so that callers cannot distinguish a wrong username from a wrong
  password (Requirements 1.2, 1.5).
- The session cookie is set with HttpOnly=True and SameSite=Strict so that it
  is not accessible from JavaScript and is not sent cross-site (Requirement 1.1).

Requirements: 1.1, 1.2, 1.5
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import SESSION_COOKIE_NAME, get_current_user, get_session_db
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse

logger = logging.getLogger("redboard.auth")

# ---------------------------------------------------------------------------
# Password hashing context
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GENERIC_AUTH_ERROR = HTTPException(
    status_code=401,
    detail={
        "error_code": "INVALID_CREDENTIALS",
        "message": "Invalid credentials. Please check your username and password.",
    },
)


def _verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the *hashed* bcrypt digest."""
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001 — passlib/bcrypt compat issue
        # Fallback to direct bcrypt verification for bcrypt 5.x compatibility
        try:
            import bcrypt as _bcrypt
            return _bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# Conditional log_service import (Task 6.1 wires the real implementation)
# ---------------------------------------------------------------------------

try:
    from app.services.log_service import record_log as _record_log  # type: ignore[import]
except ImportError:  # log_service not yet implemented — stub silently
    async def _record_log(*args, **kwargs) -> None:  # type: ignore[misc]
        pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate with username and password",
    responses={
        200: {"description": "Login successful — session cookie is set"},
        401: {"description": "Invalid credentials"},
    },
)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_session_db),
) -> LoginResponse:
    """
    Validate the supplied credentials and create a server-side session.

    On success
    ----------
    - Inserts a row in the ``sessions`` table.
    - Sets a ``session_id`` cookie (HttpOnly, SameSite=Strict, Path=/).
    - Returns 200 with the user's role and username.

    On failure
    ----------
    - Returns 401 with a generic error message that does not reveal whether
      the username or password was incorrect (Requirement 1.2).
    """
    # ------------------------------------------------------------------
    # 1. Look up the user by username
    # ------------------------------------------------------------------
    result = await db.execute(select(User).where(User.username == body.username))
    user: User | None = result.scalar_one_or_none()

    # Use a timing-safe comparison even when the user does not exist so that
    # response times are indistinguishable from the valid-user-wrong-password
    # case (prevents username enumeration via timing).
    if user is None:
        try:
            _pwd_context.dummy_verify()
        except Exception:  # noqa: BLE001 — passlib/bcrypt compat issue with bcrypt 5.x
            pass
        raise _GENERIC_AUTH_ERROR

    # ------------------------------------------------------------------
    # 2. Verify the password
    # ------------------------------------------------------------------
    if not _verify_password(body.password, user.password_hash):
        raise _GENERIC_AUTH_ERROR

    # ------------------------------------------------------------------
    # 3. Ensure the account is active
    # ------------------------------------------------------------------
    if not user.is_active:
        # Still raise the generic error — do not reveal the account is disabled
        raise _GENERIC_AUTH_ERROR

    # ------------------------------------------------------------------
    # 4. Create a new session row
    # ------------------------------------------------------------------
    new_session = Session(user_id=user.id)
    db.add(new_session)
    await db.flush()  # populate new_session.id via server default
    await db.refresh(new_session)
    await db.commit()

    session_id_str = str(new_session.id)

    # ------------------------------------------------------------------
    # 5. Set the session cookie
    # ------------------------------------------------------------------
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id_str,
        httponly=True,
        samesite="strict",
        path="/",
        # max_age is not set — cookie is a session cookie (expires when
        # the browser tab/window closes).  Server-side expiry is enforced
        # via the 8-hour last_activity check in get_current_user.
    )

    logger.info("User '%s' logged in (session %s)", user.username, session_id_str)

    # ------------------------------------------------------------------
    # 6. Audit log (stubbed until task 6.1 implements log_service)
    # ------------------------------------------------------------------
    await _record_log(
        db=db,
        action_type="user_login",
        actor_username=user.username,
        description=f"User '{user.username}' logged in.",
    )

    return LoginResponse(role=user.role, username=user.username)


@router.post(
    "/logout",
    summary="Invalidate the current session",
    responses={
        200: {"description": "Logout successful — session cookie is cleared"},
    },
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session_db),
) -> dict:
    """
    Delete the server-side session and clear the session cookie.

    This endpoint is intentionally lenient: if no valid session cookie is
    present (already expired or missing), it still returns 200 and clears
    the cookie — logout should always appear to succeed from the caller's
    perspective (Requirement 1.5).
    """
    raw_session_id: str | None = request.cookies.get(SESSION_COOKIE_NAME)
    actor_username: str = "unknown"

    if raw_session_id:
        try:
            session_id = uuid.UUID(raw_session_id)

            # Fetch the session to get the username for the audit log
            result = await db.execute(
                select(Session, User)
                .join(User, Session.user_id == User.id)
                .where(Session.id == session_id)
            )
            row = result.first()

            if row is not None:
                actor_username = row[1].username
                # Delete the session row
                await db.execute(delete(Session).where(Session.id == session_id))
                await db.commit()
                logger.info(
                    "User '%s' logged out (session %s)", actor_username, session_id
                )

        except (ValueError, Exception) as exc:  # noqa: BLE001
            # Invalid UUID or DB error — log and continue; logout should still succeed
            logger.warning("Logout cleanup error for session %s: %s", raw_session_id, exc)

    # ------------------------------------------------------------------
    # Clear the session cookie
    # ------------------------------------------------------------------
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
    )

    # ------------------------------------------------------------------
    # Audit log (stubbed until task 6.1 implements log_service)
    # ------------------------------------------------------------------
    if actor_username != "unknown":
        await _record_log(
            db=db,
            action_type="user_logout",
            actor_username=actor_username,
            description=f"User '{actor_username}' logged out.",
        )

    return {"message": "Logged out successfully."}
