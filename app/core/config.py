from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # .env also carries POSTGRES_* vars consumed only by docker-compose
    )

    # App
    app_env: str = "development"
    secret_key: str = "change-me-in-production-use-32-chars-minimum"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15    # short-lived
    refresh_token_expire_days: int = 7       # long-lived

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/project_mgmt"

    # AWS
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_session_token: str | None = None  # required for temporary/STS credentials
    aws_region: str = "us-east-1"
    s3_bucket_name: str = "project-mgmt-docs-f4a8baae"

    # Lambda
    lambda_function_name: str = "project-file-size-calculator"
    project_storage_limit_mb: int = 100

    # CORS
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"


@lru_cache
def get_settings() -> Settings:
    return Settings()
