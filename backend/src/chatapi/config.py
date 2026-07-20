from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATAPI_", extra="ignore")

    database_url: str = f"sqlite:///{Path('data/chatapi.db').as_posix()}"
    default_locale: str = Field(default="en-US", pattern=r"^(en-US|zh-CN)$")
    admin_session_idle_minutes: int = Field(default=30, ge=1)
    admin_session_absolute_hours: int = Field(default=8, ge=1)
    secure_cookies: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
