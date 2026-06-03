"""
User management router — admin-only CRUD for user accounts.

Routes
------
GET  /api/v1/users              — paginated list of users (admin only)
POST /api/v1/users              — create a new user account (admin only)
PATCH /api/v1/users/{user_id}  — update role or deactivate a user (admin only)

Security
--------
- All three routes are restricted to the ``admin`` role via
  ``require_role("admin")``.
- Passwords are stored exclusively as bcrypt hashes with cost factor 12
  (Requirement 3.3).
- Duplicate username → 409 Conflict (Requirement 3.2).
- Invalid field values → 400 Bad Request with field identification (Req 3.4).
- Role change → invalidates existing sessions within 60 s by deleting them
  from the DB immediately (Requirement 3.7).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session_db, require_role
from app.models.session import Session
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.log_service import record_log

logger = logging.getLogger("redboard.users")

# ---------------------------------------------------------------------------
# Password hashing — cost factor 12 (Requirement 3.3)
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/users", tags=["users"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# GET /users — paginated list (admin only)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[UserResponse],
    summary="List user accounts (admin only)",
    responses={
        200: {"description": "Paginated list of users"},
        400: {"description": "Invalid pagination parameters"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
    },
)
async def list_users(
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session_db),
) -> list[User]:
    """
    Return a paginated list of all user accounts.

    Query params
    ------------
    page:      Page number (1-indexed, default 1).
    page_size: Number of results per page (default 20, max 100).

    Rejects ``page_size > 100`` with 400 (Requirement 3.6, Property 7).
    """
    # Validate page_size
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

    offset = (page - 1) * page_size
    result = await db.execute(
        select(User).order_by(User.created_at.asc()).offset(offset).limit(page_size)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# POST /users — create a new user (admin only)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    summary="Create a new user account (admin only)",
    responses={
        201: {"description": "User created successfully"},
        400: {"description": "Invalid input — field identified in detail"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        409: {"description": "Username already exists"},
    },
)
async def create_user(
    body: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session_db),
) -> User:
    """
    Create a new user account.

    - Validates unique username (→ 409 on duplicate).
    - Validates password length 8–128 (enforced by schema → 422, but
      explicit check here ensures 400 with field identification per Req 3.4).
    - Validates role is one of admin / lead / operator.
    - Hashes the password with bcrypt cost 12 (Requirement 3.3).
    - Persists the user and records a ``user_created`` log entry.
    """
    # ------------------------------------------------------------------
    # Check for duplicate username before hitting the DB constraint
    # ------------------------------------------------------------------
    existing = await db.execute(
        select(User).where(User.username == body.username)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "USERNAME_CONFLICT",
                "message": f"A user with username '{body.username}' already exists.",
                "detail": {"field": "username"},
            },
        )

    # ------------------------------------------------------------------
    # Hash password (cost 12) — Requirement 3.3
    # ------------------------------------------------------------------
    password_hash = _pwd_context.hash(body.password)

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    new_user = User(
        username=body.username,
        password_hash=password_hash,
        role=body.role,
        is_active=True,
    )
    db.add(new_user)

    try:
        await db.flush()
        await db.refresh(new_user)
    except IntegrityError:
        await db.rollback()
        # Rare race condition where another request created the same username
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "USERNAME_CONFLICT",
                "message": f"A user with username '{body.username}' already exists.",
                "detail": {"field": "username"},
            },
        )

    # ------------------------------------------------------------------
    # Audit log — Requirement 7.1 ("user_created")
    # ------------------------------------------------------------------
    await record_log(
        db=db,
        action_type="user_created",
        actor_username=current_user.username,
        description=(
            f"Admin '{current_user.username}' created user '{new_user.username}' "
            f"with role '{new_user.role}'."
        ),
        target_entity_type="user",
        target_entity_id=new_user.id,
    )

    await db.commit()
    await db.refresh(new_user)
    logger.info(
        "User '%s' created by admin '%s'", new_user.username, current_user.username
    )
    return new_user


# ---------------------------------------------------------------------------
# PATCH /users/{user_id} — update role or deactivate (admin only)
# ---------------------------------------------------------------------------


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user's role or active status (admin only)",
    responses={
        200: {"description": "User updated"},
        400: {"description": "Invalid input — field identified in detail"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
        409: {"description": "Username conflict (if username update attempted)"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_session_db),
) -> User:
    """
    Update a user's role or deactivate their account.

    - ``role``: Change the user's role.  All existing sessions are
      invalidated immediately so the new role is effective within 60 s
      (Requirement 3.7).
    - ``is_active=false``: Deactivate the account.  The user's session
      is invalidated; historical data is preserved (Requirement 3.5).

    Returns 400 if neither field is supplied or if a value is invalid.
    """
    # ------------------------------------------------------------------
    # Validate at least one field is present
    # ------------------------------------------------------------------
    if body.role is None and body.is_active is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "At least one of 'role' or 'is_active' must be supplied.",
                "detail": {"fields": ["role", "is_active"]},
            },
        )

    # ------------------------------------------------------------------
    # Load the target user
    # ------------------------------------------------------------------
    result = await db.execute(select(User).where(User.id == user_id))
    target: User | None = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "message": f"No user found with ID '{user_id}'.",
            },
        )

    # ------------------------------------------------------------------
    # Track changes for audit log
    # ------------------------------------------------------------------
    role_changed = False
    deactivated = False

    # ------------------------------------------------------------------
    # Apply role update
    # ------------------------------------------------------------------
    if body.role is not None and body.role != target.role:
        old_role = target.role
        target.role = body.role
        role_changed = True

        # Invalidate all existing sessions for this user so the new role
        # takes effect within 60 s (Requirement 3.7).
        await db.execute(delete(Session).where(Session.user_id == target.id))
        logger.info(
            "Sessions invalidated for user '%s' after role change %s → %s",
            target.username,
            old_role,
            body.role,
        )

    # ------------------------------------------------------------------
    # Apply is_active update
    # ------------------------------------------------------------------
    if body.is_active is not None and body.is_active != target.is_active:
        target.is_active = body.is_active
        if not body.is_active:
            deactivated = True
            # Invalidate sessions on deactivation so the user is locked out
            # immediately (Requirement 3.5).
            await db.execute(delete(Session).where(Session.user_id == target.id))
            logger.info(
                "Sessions invalidated for deactivated user '%s'", target.username
            )

    await db.flush()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    if deactivated:
        await record_log(
            db=db,
            action_type="user_deactivated",
            actor_username=current_user.username,
            description=(
                f"Admin '{current_user.username}' deactivated user '{target.username}'."
            ),
            target_entity_type="user",
            target_entity_id=target.id,
        )

    if role_changed:
        await record_log(
            db=db,
            action_type="user_role_updated",
            actor_username=current_user.username,
            description=(
                f"Admin '{current_user.username}' updated role for user "
                f"'{target.username}'."
            ),
            target_entity_type="user",
            target_entity_id=target.id,
        )

    await db.commit()
    await db.refresh(target)
    logger.info(
        "User '%s' updated by admin '%s' (role_changed=%s, deactivated=%s)",
        target.username,
        current_user.username,
        role_changed,
        deactivated,
    )
    return target
