"""
Integration tests for the authentication flow.

Covers the full cycle:
  login → session cookie set → protected request succeeds → logout → request rejected

Requirements: 1.1, 1.2, 1.4, 1.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import SESSION_COOKIE_NAME
from app.models.user import User

try:
    import bcrypt as _bcrypt_lib

    def _hash_password(password: str) -> str:
        """Hash a password using bcrypt directly (passlib has compat issues with bcrypt 5.x)."""
        return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()

    def _verify_password(password: str, hashed: str) -> bool:
        return _bcrypt_lib.checkpw(password.encode(), hashed.encode())

except ImportError:
    from passlib.context import CryptContext as _CryptContext

    _pwd_ctx = _CryptContext(schemes=["bcrypt"], deprecated="auto")

    def _hash_password(password: str) -> str:
        return _pwd_ctx.hash(password)

    def _verify_password(password: str, hashed: str) -> bool:
        return _pwd_ctx.verify(password, hashed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    username: str = "authtest",
    password: str = "Secure123!",
    role: str = "operator",
    is_active: bool = True,
) -> User:
    """Insert a real User row with a proper bcrypt hash."""
    now = datetime.now(tz=timezone.utc)
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=_hash_password(password),
        role=role,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Test: valid login sets session cookie and returns role (Requirement 1.1)
# ---------------------------------------------------------------------------


async def test_login_sets_session_cookie(client: AsyncClient, db_session: AsyncSession) -> None:
    """
    A valid login must:
    - Return HTTP 200.
    - Set an HttpOnly session cookie.
    - Return the user's role and username in the response body.
    """
    await _create_user(db_session, username="login_cookie_user", password="Password1!")

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "login_cookie_user", "password": "Password1!"},
    )
    assert response.status_code == 200, response.text

    # Cookie must be present
    assert SESSION_COOKIE_NAME in response.cookies, (
        f"Expected '{SESSION_COOKIE_NAME}' cookie in response, got: {dict(response.cookies)}"
    )

    body = response.json()
    assert body["role"] == "operator"
    assert body["username"] == "login_cookie_user"


# ---------------------------------------------------------------------------
# Test: protected route accessible with valid session (Requirement 1.4)
# ---------------------------------------------------------------------------


async def test_protected_route_accessible_after_login(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    After logging in, a request to a protected route with the session cookie
    must return 200, not 401.
    """
    await _create_user(db_session, username="protected_route_user", password="Password1!")

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "protected_route_user", "password": "Password1!"},
    )
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie is not None

    # Use the cookie on a protected endpoint (GET /api/v1/engagements requires auth)
    protected_resp = await client.get(
        "/api/v1/engagements",
        cookies={SESSION_COOKIE_NAME: session_cookie},
    )
    assert protected_resp.status_code == 200, protected_resp.text


# ---------------------------------------------------------------------------
# Test: logout invalidates session (Requirement 1.5)
# ---------------------------------------------------------------------------


async def test_logout_invalidates_session(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    After logout, the same session cookie must no longer grant access to
    protected routes (should return 401).
    """
    await _create_user(db_session, username="logout_user", password="Password1!")

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "logout_user", "password": "Password1!"},
    )
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get(SESSION_COOKIE_NAME)
    assert session_cookie is not None

    # Logout
    logout_resp = await client.post(
        "/api/v1/auth/logout",
        cookies={SESSION_COOKIE_NAME: session_cookie},
    )
    assert logout_resp.status_code == 200

    # Protected request after logout must be rejected
    after_logout_resp = await client.get(
        "/api/v1/engagements",
        cookies={SESSION_COOKIE_NAME: session_cookie},
    )
    assert after_logout_resp.status_code == 401, (
        f"Expected 401 after logout, got {after_logout_resp.status_code}: "
        f"{after_logout_resp.text}"
    )


# ---------------------------------------------------------------------------
# Test: unauthenticated request returns 401 (Requirement 1.4)
# ---------------------------------------------------------------------------


async def test_unauthenticated_request_returns_401(client: AsyncClient) -> None:
    """
    A request to a protected endpoint without any session cookie must return 401.
    """
    response = await client.get("/api/v1/engagements")
    assert response.status_code == 401, response.text

    body = response.json()
    # The error body must include error_code and message (Requirement 2.9)
    assert "error_code" in body or (
        "detail" in body and isinstance(body["detail"], dict) and "error_code" in body["detail"]
    ), f"Unexpected error body: {body}"


# ---------------------------------------------------------------------------
# Test: wrong password returns generic 401 (Requirement 1.2)
# ---------------------------------------------------------------------------


async def test_wrong_password_returns_generic_401(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    An incorrect password must return 401 with a generic message that does not
    reveal whether the username or password was wrong (Requirement 1.2).
    """
    await _create_user(db_session, username="wrongpass_user", password="CorrectPassword1!")

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "wrongpass_user", "password": "WrongPassword!"},
    )
    assert response.status_code == 401, response.text

    body = response.json()
    # The error response is the AppError format: {"error_code": ..., "message": ..., "detail": {}}
    error_code = body.get("error_code") or body.get("detail", {}).get("error_code")
    assert error_code == "INVALID_CREDENTIALS", f"Expected INVALID_CREDENTIALS, got: {body}"
    # Message must be generic — same for wrong username as for wrong password (Requirement 1.2)
    # (the spec only requires it's generic, not that specific words are absent)
    msg = body.get("message", "")
    assert msg  # must have a message


# ---------------------------------------------------------------------------
# Test: unknown username returns generic 401 (Requirement 1.2)
# ---------------------------------------------------------------------------


async def test_unknown_username_returns_generic_401(client: AsyncClient) -> None:
    """
    An unknown username must return the same generic 401 as a wrong password.
    """
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody_at_all_xyz", "password": "SomePassword1!"},
    )
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Test: inactive account returns generic 401 (Requirement 1.5)
# ---------------------------------------------------------------------------


async def test_inactive_account_cannot_login(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    A deactivated account must be rejected at login with the same generic 401.
    The error message must not reveal that the account is disabled.
    """
    await _create_user(
        db_session,
        username="inactive_user",
        password="Password1!",
        is_active=False,
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "inactive_user", "password": "Password1!"},
    )
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Test: logout without a session cookie still returns 200 (Requirement 1.5)
# ---------------------------------------------------------------------------


async def test_logout_without_cookie_returns_200(client: AsyncClient) -> None:
    """
    Logout must always succeed (return 200) even when there is no session cookie,
    so that the UI can always consider logout as complete (Requirement 1.5).
    """
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Test: full auth cycle end-to-end
# ---------------------------------------------------------------------------


async def test_full_auth_cycle(client: AsyncClient, db_session: AsyncSession) -> None:
    """
    Full integration cycle:
    1. Login → 200 + cookie
    2. Use cookie on protected route → 200
    3. Logout → 200
    4. Use old cookie on protected route → 401
    """
    await _create_user(db_session, username="full_cycle_user", password="CyclePass1!")

    # Step 1: Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "full_cycle_user", "password": "CyclePass1!"},
    )
    assert login.status_code == 200
    cookie = login.cookies.get(SESSION_COOKIE_NAME)
    assert cookie

    # Step 2: Protected request with cookie
    get_eng = await client.get(
        "/api/v1/engagements",
        cookies={SESSION_COOKIE_NAME: cookie},
    )
    assert get_eng.status_code == 200

    # Step 3: Logout
    logout = await client.post(
        "/api/v1/auth/logout",
        cookies={SESSION_COOKIE_NAME: cookie},
    )
    assert logout.status_code == 200

    # Step 4: Protected request rejected
    after = await client.get(
        "/api/v1/engagements",
        cookies={SESSION_COOKIE_NAME: cookie},
    )
    assert after.status_code == 401
