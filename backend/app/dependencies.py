"""
Shared FastAPI dependencies for session authentication and RBAC.

Two key building blocks used by every protected router:

- ``get_current_user``  — reads the session cookie, validates the session in
  PostgreSQL, enforces the 8-hour inactivity window, and returns the active
  ``User`` row.  Raises ``HTTPException(401)`` on any authentication failure.

- ``require_role(*roles)``  — dependency factory that wraps
  ``get_current_user`` and additionally asserts the caller's role is in the
  provided set.  Raises ``HTTPException(403)`` with the standardised error
  body on role mismatch.

Requirements: 1.4, 1.6, 1.7, 2.9
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.session import Session
from app.models.user import User

logger = logging.getLogger("redboard.dependencies")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "session_id"
SESSION_MAX_AGE = timedelta(hours=8)


# ---------------------------------------------------------------------------
# Database session dependency
# ---------------------------------------------------------------------------


async def get_session_db() -> AsyncSession:
    """
    Yields an :class:`~sqlalchemy.ext.asyncio.AsyncSession` for each request.

    Usage::

        async def my_endpoint(db: AsyncSession = Depends(get_session_db)):
            ...
    """
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session_db),
) -> User:
    """
    Resolve the authenticated user for the current request.

    Steps
    -----
    1. Read the ``session_id`` cookie from the request.
    2. Query the ``sessions`` table for a matching row.
    3. Check that ``last_activity >= now() - 8 h``.
    4. On success, update ``last_activity`` to ``now()`` and return the
       associated ``User`` record.
    5. On any failure (missing cookie, unknown session, expired session,
       inactive user), delete the session record if one was found and raise
       ``HTTPException(401)``.

    Satisfies Requirements 1.4, 1.6, 1.7.
    """
    # ------------------------------------------------------------------
    # 1. Read session cookie
    # ------------------------------------------------------------------
    raw_session_id: str | None = request.cookies.get(SESSION_COOKIE_NAME)

    if not raw_session_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "NOT_AUTHENTICATED",
                "message": "Authentication required. Please log in.",
            },
        )

    # Parse as UUID to guard against obviously invalid values
    try:
        session_id = uuid.UUID(raw_session_id)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "NOT_AUTHENTICATED",
                "message": "Invalid session token.",
            },
        )

    # ------------------------------------------------------------------
    # 2. Query the sessions table
    # ------------------------------------------------------------------
    stmt = (
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.id == session_id)
    )
    result = await db.execute(stmt)
    row = result.first()

    if row is None:
        # Session does not exist — no DB row to clean up
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": "Session not found. Please log in again.",
            },
        )

    session: Session = row[0]
    user: User = row[1]

    # ------------------------------------------------------------------
    # 3. Check inactivity timeout (last_activity >= now() - 8h)
    # ------------------------------------------------------------------
    now_utc = datetime.now(tz=timezone.utc)
    cutoff = now_utc - SESSION_MAX_AGE

    # last_activity may be a timezone-aware or naive datetime depending on
    # how the DB driver returns it; normalise to UTC-aware for comparison.
    last_activity: datetime = session.last_activity
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    if last_activity < cutoff:
        # Session has expired — delete the row then reject the request.
        logger.info(
            "Expired session %s for user %s (last_activity=%s)",
            session_id,
            user.username,
            last_activity.isoformat(),
        )
        await db.execute(delete(Session).where(Session.id == session_id))
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "SESSION_EXPIRED",
                "message": "Your session has expired. Please log in again.",
            },
        )

    # ------------------------------------------------------------------
    # 4. Ensure the user account is still active
    # ------------------------------------------------------------------
    if not user.is_active:
        # Deactivated users cannot use existing sessions
        await db.execute(delete(Session).where(Session.id == session_id))
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "ACCOUNT_DISABLED",
                "message": "Your account has been deactivated. Contact an administrator.",
            },
        )

    # ------------------------------------------------------------------
    # 5. Refresh last_activity (sliding window)
    # ------------------------------------------------------------------
    await db.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_activity=now_utc)
    )
    await db.commit()

    return user


# ---------------------------------------------------------------------------
# RBAC dependency factory
# ---------------------------------------------------------------------------


def require_role(*roles: str) -> Callable[..., User]:
    """
    Return a FastAPI dependency that requires ``current_user.role`` to be in
    *roles*.

    Usage::

        @router.post("/engagements", dependencies=[Depends(require_role("lead", "admin"))])
        async def create_engagement(...):
            ...

    Or to also get the user object::

        @router.get("/users")
        async def list_users(current_user: User = Depends(require_role("admin"))):
            ...

    Raises ``HTTPException(403)`` with a structured body when the role check
    fails.  Satisfies Requirement 2.9.
    """

    async def _dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in roles:
            logger.warning(
                "Access denied: user %s (role=%s) attempted action requiring role(s) %s",
                current_user.username,
                current_user.role,
                roles,
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "FORBIDDEN",
                    "message": (
                        f"Your role '{current_user.role}' does not have permission "
                        f"to perform this action. Required role(s): {', '.join(roles)}."
                    ),
                },
            )
        return current_user

    return _dependency
