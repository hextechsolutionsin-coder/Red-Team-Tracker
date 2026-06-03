"""
Red Team Operations Tracker — FastAPI application entry point.

Startup sequence (inside lifespan):
  1. Validate required environment variables — log each missing one and exit(1) if any absent.
  2. Run `alembic upgrade head` — log migration errors and exit(1) on failure.
  3. Register all API routers.
"""

import logging
import sys
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.util.exc import CommandError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import REQUIRED_ENV_VARS, settings
from app.errors import http_exception_handler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("redboard.main")


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------


def _validate_env_vars() -> None:
    """
    Iterate required env var names, log each missing one by name, and
    call sys.exit(1) if any are absent.  Satisfies Requirement 10.4.
    """
    missing: list[str] = []

    for name in REQUIRED_ENV_VARS:
        value = getattr(settings, name, "")
        if not value:  # empty string counts as missing
            logger.error("Required environment variable is not set: %s", name)
            missing.append(name)

    if missing:
        logger.error(
            "Aborting startup — %d required environment variable(s) missing: %s",
            len(missing),
            ", ".join(missing),
        )
        sys.exit(1)


def _run_migrations() -> None:
    """
    Run `alembic upgrade head` synchronously during startup.
    Catch CommandError, log the migration error, and sys.exit(1) on failure.
    Satisfies Requirement 10.5.
    """
    try:
        logger.info("Running Alembic migrations…")
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully.")
    except CommandError as exc:
        logger.error("Alembic migration failed: %s", exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 — catch-all before startup
        logger.error("Unexpected error during Alembic migration: %s", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """
    FastAPI lifespan context manager.

    Runs startup validation and migrations before the application begins
    accepting requests; runs any teardown logic on shutdown.
    """
    import asyncio

    # --- Startup ---
    logger.info("Starting Red Team Operations Tracker backend…")
    _validate_env_vars()

    # Run migrations in a thread pool to avoid asyncio.run() conflict
    # (alembic's async env.py uses asyncio.run() internally, which cannot
    # be called inside an already-running event loop)
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            await loop.run_in_executor(pool, _run_migrations)
        except SystemExit as exc:
            raise RuntimeError(f"Migration failed, exiting with code {exc.code}") from exc

    logger.info("Startup complete — accepting requests.")

    yield  # Application runs here

    # --- Shutdown ---
    logger.info("Shutting down Red Team Operations Tracker backend.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""

    app = FastAPI(
        title="Red Team Operations Tracker",
        version="1.0.0",
        description="Internal red team engagement and findings tracker.",
        lifespan=lifespan,
    )

    # CORS — allow origins defined in ALLOWED_ORIGINS (comma-separated)
    origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handler — standardised AppError JSON format (Requirement 2.9)
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]

    # -----------------------------------------------------------------------
    # Router registration stubs
    # Routers will be implemented in subsequent tasks and imported here.
    # -----------------------------------------------------------------------
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """
    Import and include each router under the /api/v1 prefix.
    Routers not yet implemented are guarded with a try/except so the app
    can start during incremental development.
    """
    # Health check — required by docker-compose healthcheck (Requirement 10.6 / Task 17)
    from fastapi import APIRouter

    health_router = APIRouter()

    @health_router.get("/api/v1/health", tags=["health"])
    async def health_check() -> dict:
        return {"status": "ok"}

    app.include_router(health_router)

    # Auth router (Task 5.1)
    from app.routers.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")

    from app.routers.users import router as users_router
    app.include_router(users_router, prefix="/api/v1")

    from app.routers.engagements import router as engagements_router
    app.include_router(engagements_router, prefix="/api/v1")

    from app.routers.findings import router as findings_router
    app.include_router(findings_router, prefix="/api/v1")

    from app.routers.evidence import router as evidence_router
    app.include_router(evidence_router, prefix="/api/v1")

    from app.routers.logs import router as logs_router
    app.include_router(logs_router, prefix="/api/v1")

    from app.routers.dashboard import router as dashboard_router
    app.include_router(dashboard_router, prefix="/api/v1")

    from app.routers.reports import router as reports_router
    app.include_router(reports_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Application instance (used by Uvicorn: uvicorn app.main:app)
# ---------------------------------------------------------------------------

app = create_app()
