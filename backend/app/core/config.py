from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TrendScope AI"
    api_prefix: str = "/api/v1"
    environment: str = "development"

    # Local fallback keeps `uvicorn app.main:app` runnable without Docker.
    database_url: str = "sqlite:///./trendscope.db"
    auto_create_tables: bool = True
    secret_key: str = "dev-secret-change-me"
    access_token_minutes: int = 480
    refresh_token_days: int = 14
    # Cookies are marked Secure outside development so the refresh token is not
    # sent over plain HTTP. Local http://localhost still works in development.
    cookie_secure: bool | None = None
    auth_required: bool = True

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    admin_email: str = "admin@trendscope.app"
    admin_password: str = "admin123"

    # Demo / mock generation
    seed_demo: bool = True
    mock_product_limit: int = 48
    mock_history_days: int = 400

    reports_dir: str = "./reports"
    redis_url: str = "redis://localhost:6379/0"
    celery_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def refresh_cookie_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment.lower() not in {"development", "dev", "local", "test", "testing"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
