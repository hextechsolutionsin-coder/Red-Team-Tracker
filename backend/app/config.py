"""
Application configuration — reads all required env vars via pydantic-settings BaseSettings.
Missing variables are detected early during the startup validation step in main.py lifespan.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All environment-specific configuration for the Tracker backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Don't raise on missing values here — main.py lifespan does the explicit check
        # so we can log each missing variable by name before exiting.
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = ""

    # Session cookie signing secret
    SESSION_SECRET: str = ""

    # Directory where evidence files are stored (outside the web root)
    UPLOAD_DIR: str = ""

    # Comma-separated allowed CORS origins
    ALLOWED_ORIGINS: str = ""

    # Ports (informational; actual binding is controlled by docker-compose / uvicorn args)
    FRONTEND_PORT: int = 80
    API_PORT: int = 8000


# Module-level singleton — imported by other modules
settings = Settings()

# Names of variables that are REQUIRED to be non-empty at startup.
REQUIRED_ENV_VARS: list[str] = [
    "DATABASE_URL",
    "SESSION_SECRET",
    "UPLOAD_DIR",
    "ALLOWED_ORIGINS",
]
