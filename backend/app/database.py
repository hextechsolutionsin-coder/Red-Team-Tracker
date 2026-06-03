"""
Async SQLAlchemy engine and session factory.

Usage (in a FastAPI dependency):

    from backend.app.database import async_session_factory

    async def get_session_db():
        async with async_session_factory() as session:
            yield session
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _build_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine from the DATABASE_URL setting.

    Pool size arguments are omitted for SQLite (used in tests) because the
    SQLite dialect does not support ``pool_size`` / ``max_overflow``.
    """
    url = settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        from sqlalchemy.pool import StaticPool

        return create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )
    return create_async_engine(
        url,
        # Echo SQL for development; disable in production via env if needed.
        echo=False,
        # asyncpg pool sizing — sensible defaults for a small internal app.
        pool_size=5,
        max_overflow=10,
    )


engine: AsyncEngine = _build_engine()

# Session factory — call async_session_factory() to obtain an AsyncSession context manager.
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass
