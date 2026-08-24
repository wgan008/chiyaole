"""Settings. Everything secret comes from the environment; nothing is defaulted to a real value."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+psycopg://chiyaole:chiyaole@localhost:5432/chiyaole"

    dashscope_api_key: str = ""
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    pushplus_token: str = ""

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
