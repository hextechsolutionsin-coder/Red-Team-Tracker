"""
Shared pytest fixtures for the Red Team Operations Tracker backend tests.

Uses an in-memory SQLite database via aiosqlite so tests run without a live
PostgreSQL instance.  The DATABASE_URL environment variable is set to a valid
SQLite URL *before* app.database is imported so that the module-level
``_build_engine()`` call succeeds on first import.  After import the
module-level singletons are replaced with SQLite equivalents.

asyncio_mode = "auto" is set in pytest.ini so no ``@pytest.mark.asyncio``
decoration is needed on individual tests.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator

# ---------------------------------------------------------------------------
# Set required env vars BEFORE any app module is imported.
# app.database reads settings.DATABASE_URL at module level; we must provide
# a valid URL so create_async_engine() does not raise on import.
# app.config.settings is a module-level singleton built at import time.
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SESSION_SECRET", "test-secret-key")
os.environ.setdefault("UPLOAD_DIR", "/tmp/redboard_test_uploads")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Build the shared in-memory SQLite engine.
# StaticPool keeps a single connection alive so all async tasks share
# the same in-memory DB state.
# ---------------------------------------------------------------------------

_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_test_engine: AsyncEngine = create_async_engine(
    _TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

_test_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Now import app modules — DATABASE_URL env var is set so database.py will
# attempt to build an engine with the SQLite URL from settings.  We then
# replace the module-level singletons with our StaticPool version.
# ---------------------------------------------------------------------------

import app.database as _db_module  # noqa: E402

# Replace the production engine/session factory with the test ones.
_db_module.engine = _test_engine
_db_module.async_session_factory = _test_session_factory

# Import Base and all ORM models (side-effect: registers all tables on Base.metadata).
from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    Engagement,
    EngagementOperator,
    EvidenceFile,
    Finding,
    OperatorLog,
    Session,
    User,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal FastAPI test app (no lifespan / no migrations)
# ---------------------------------------------------------------------------

def _build_test_app():
    """
    Return a FastAPI instance with all routers registered but *without* the
    production lifespan (no env-var validation, no Alembic migrations).
    The test engine is already patched into ``app.database``.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    from app.errors import http_exception_handler
    from app.main import _register_routers  # type: ignore[attr-defined]

    test_app = FastAPI(title="RedBoard Test App")
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    _register_routers(test_app)
    return test_app


# ---------------------------------------------------------------------------
# Session-scoped fixture: create all tables once; drop them at the end.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Yield the shared SQLite engine; create all tables before, drop after."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield _test_engine

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Function-scoped fixture: an AsyncSession that rolls back after each test.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an ``AsyncSession`` that is rolled back at the end of each test,
    keeping the database clean between tests without dropping/recreating tables.
    """
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Function-scoped fixture: an AsyncClient wired to the FastAPI test app.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """
    Yield an ``httpx.AsyncClient`` that calls the FastAPI test app.

    The ``get_session_db`` dependency is overridden so every request uses
    the same in-memory SQLite session factory.
    """
    from app.dependencies import get_session_db

    test_app = _build_test_app()

    async def _override_get_session_db() -> AsyncGenerator[AsyncSession, None]:
        async with _test_session_factory() as session:
            yield session

    test_app.dependency_overrides[get_session_db] = _override_get_session_db

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Convenience factory: insert a User row and return it.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def create_user(db_session: AsyncSession):
    """
    Factory fixture — call it to insert a ``User`` row for testing.

    Usage::

        async def test_something(create_user):
            user = await create_user(username="alice", role="admin")
    """

    async def _factory(
        username: str = "testuser",
        role: str = "operator",
        password_hash: str = "$2b$12$placeholderhashortest00000000000000000000000",
        is_active: bool = True,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            username=username,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _factory
