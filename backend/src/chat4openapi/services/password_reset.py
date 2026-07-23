import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chat4openapi.config import Settings

ADMIN_PASSWORD_RESET_FILENAME = "admin-password-reset.key"


class PasswordResetCredentialError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PasswordResetCredential:
    path: Path
    expires_at: datetime


def issue_admin_password_reset(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> PasswordResetCredential:
    issued_at = now or datetime.now(UTC)
    directory = settings.admin_password_reset_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    path = directory / ADMIN_PASSWORD_RESET_FILENAME
    try:
        file_stat = path.stat()
        existing_key = path.read_text(encoding="utf-8").strip()
        existing_issued_at = datetime.fromtimestamp(file_stat.st_mtime, UTC)
        existing_expires_at = existing_issued_at + timedelta(
            minutes=settings.admin_password_reset_minutes
        )
        if (
            not path.is_symlink()
            and existing_key
            and issued_at < existing_expires_at
        ):
            return PasswordResetCredential(
                path=path,
                expires_at=existing_expires_at,
            )
    except (FileNotFoundError, OSError, UnicodeError):
        pass
    temporary_path = directory / (
        f".{ADMIN_PASSWORD_RESET_FILENAME}.{secrets.token_hex(8)}.tmp"
    )
    reset_key = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary_path, flags, 0o600)
    try:
        os.write(descriptor, f"{reset_key}\n".encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary_path, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary_path.unlink(missing_ok=True)
    file_issued_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return PasswordResetCredential(
        path=path,
        expires_at=file_issued_at
        + timedelta(minutes=settings.admin_password_reset_minutes),
    )


def consume_admin_password_reset(
    settings: Settings,
    supplied_key: str,
    *,
    now: datetime | None = None,
) -> None:
    checked_at = now or datetime.now(UTC)
    path = (
        settings.admin_password_reset_dir.resolve()
        / ADMIN_PASSWORD_RESET_FILENAME
    )
    try:
        file_stat = path.stat()
        stored_key = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise PasswordResetCredentialError("auth.reset_key_invalid") from exc
    issued_at = datetime.fromtimestamp(file_stat.st_mtime, UTC)
    expires_at = issued_at + timedelta(
        minutes=settings.admin_password_reset_minutes
    )
    if checked_at >= expires_at:
        path.unlink(missing_ok=True)
        raise PasswordResetCredentialError("auth.reset_key_expired")
    if not stored_key or not secrets.compare_digest(stored_key, supplied_key):
        raise PasswordResetCredentialError("auth.reset_key_invalid")
    try:
        path.unlink()
    except FileNotFoundError as exc:
        raise PasswordResetCredentialError("auth.reset_key_invalid") from exc
