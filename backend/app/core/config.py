"""
Centralised application configuration.

All environment-dependent values are read here once, via pydantic-settings,
so the rest of the codebase never touches `os.environ` directly. This keeps
configuration testable (override with env vars / .env) and makes it obvious
what the service depends on.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "Auction Platform"
    ENV: str = "development"
    DEBUG: bool = True

    # --- Database ---
    # asyncpg driver for the app itself (async SQLAlchemy engine)
    DATABASE_URL: str = "postgresql+asyncpg://auction:auction@localhost:5432/auction_db"
    # plain psycopg2 URL used only by Alembic (sync migrations)
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://auction:auction@localhost:5432/auction_db"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_BID_CHANNEL_PREFIX: str = "auction:channel:"

    # --- Auth ---
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_this_is_a_dev_only_secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h, fine for a portfolio project

    # --- Background worker ---
    AUCTION_EXPIRY_POLL_SECONDS: float = 2.0

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings are cheap to build but we cache so every import shares one
    instance (and so tests can monkeypatch env vars + clear the cache)."""
    return Settings()


settings = get_settings()
