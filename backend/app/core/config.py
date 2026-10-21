"""
Central application configuration.

All values come from environment variables (see .env.example at the repo root).
Nothing here should ever be hard-coded with real secrets — this file only
defines names, types and safe defaults for *local development*.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Looks for .env in the current directory and one level up, so the backend
    # works whether you run it from the repo root or from backend/.
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "Jezseem ERP"
    ENVIRONMENT: str = "development"  # development | staging | production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Security ---
    SECRET_KEY: str  # required, no default — must be set in .env

    # DEVELOPMENT ONLY. When true, every request is treated as though
    # DEV_USER_USERNAME were signed in, and permission checks pass. This
    # exists so the UI can be built before the login flow is finished.
    # Startup aborts if this is true while ENVIRONMENT == "production".
    AUTH_DISABLED: bool = False
    DEV_USER_USERNAME: str = "admin"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    # --- Database ---
    DATABASE_URL: str  # e.g. postgresql+psycopg://user:pass@db:5432/jezseem_erp

    # --- Redis / Celery ---
    # Redis and Celery are not used yet — no module currently queues a
    # background job. They are configured here so that when one does
    # (scheduled WooCommerce sync, report generation), nothing has to change
    # but starting a Redis server.
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- File storage ---
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 25


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — env is only parsed once per process."""
    return Settings()


settings = get_settings()
