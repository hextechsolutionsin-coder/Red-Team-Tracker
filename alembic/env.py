"""
Alembic environment script.

Configured for async SQLAlchemy (asyncpg driver).  The DATABASE_URL is read
from the application settings so there is a single source of truth.

Run migrations from the backend/ directory:

    cd backend
    alembic upgrade head
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Make backend/app importable whether Alembic is invoked from backend/ or from
# the project root (where docker-compose runs `alembic upgrade head`).
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.join(_here, "..", "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

# ---------------------------------------------------------------------------
# Import the shared Base so that autogenerate can discover all mapped tables,
# and import models so their metadata is registered against Base.
# ---------------------------------------------------------------------------
from app.database import Base  # noqa: E402
import app.models  # noqa: F401  — registers all ORM models against Base

# ---------------------------------------------------------------------------
# Alembic Config object (gives access to values in alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Inject DATABASE_URL from the application settings, overriding the placeholder
# in alembic.ini.  We import settings lazily to avoid hard-failing when the env
# var is missing (e.g. during `alembic revision --autogenerate` on a dev machine
# that has DATABASE_URL set via .env).
try:
    from app.config import settings as _app_settings

    _db_url = _app_settings.DATABASE_URL
except Exception:
    # Fall back to the raw environment variable if pydantic-settings is
    # unavailable (e.g. running outside the container without the venv).
    _db_url = os.environ.get("DATABASE_URL", "")

if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

# Interpret the config file for Python logging when the file exists.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object that Alembic inspects when generating autogenerate diffs.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations (no live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In offline mode Alembic doesn't need a live database connection — it
    generates the SQL script to stdout.  Useful for reviewing what will be
    applied before touching a database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Emit CHECK constraints in autogenerate output.
        include_schemas=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (async engine)
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Emit CHECK constraints in autogenerate output.
        compare_type=True,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online (connected) migrations."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
