from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_PATH = Path("data/chat4openapi.db")
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
DEFAULT_ENCRYPTION_KEY_FILE = Path("data/.chat4openapi.key")
DEFAULT_ADMIN_PASSWORD_RESET_DIR = Path("data/password-reset")
_LEGACY_PRODUCT_STEM = "chat" + "api"
_LEGACY_DATABASE_PATH = Path("data") / f"{_LEGACY_PRODUCT_STEM}.db"
_LEGACY_ENCRYPTION_KEY_FILE = Path("data") / f".{_LEGACY_PRODUCT_STEM}.key"


def migrate_legacy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except (FileExistsError, FileNotFoundError):
        return
    source.unlink(missing_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHAT4OPENAPI_", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    default_locale: str = Field(default="en-US", pattern=r"^(en-US|zh-CN)$")
    admin_session_idle_minutes: int = Field(default=30, ge=1)
    admin_session_absolute_hours: int = Field(default=8, ge=1)
    browser_chat_session_days: int = Field(default=30, ge=1)
    secure_cookies: bool = False
    encryption_key: str | None = None
    encryption_key_file: Path = DEFAULT_ENCRYPTION_KEY_FILE
    admin_password_reset_dir: Path = DEFAULT_ADMIN_PASSWORD_RESET_DIR
    admin_password_reset_minutes: int = Field(default=15, ge=1, le=60)


def migrate_legacy_default_files(settings: Settings) -> None:
    if settings.database_url == DEFAULT_DATABASE_URL:
        migrate_legacy_file(_LEGACY_DATABASE_PATH, DEFAULT_DATABASE_PATH)
    if settings.encryption_key_file == DEFAULT_ENCRYPTION_KEY_FILE:
        migrate_legacy_file(_LEGACY_ENCRYPTION_KEY_FILE, DEFAULT_ENCRYPTION_KEY_FILE)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    migrate_legacy_default_files(settings)
    return settings
