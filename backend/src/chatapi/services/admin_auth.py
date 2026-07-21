from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.models.admin import AdminUser
from chatapi.models.admin_session import AdminSession
from chatapi.models.app_setting import AppSetting
from chatapi.schemas.auth import AdminSummary
from chatapi.schemas.setup import SetupRequest, SetupStatus
from chatapi.security.passwords import hash_password, verify_password
from chatapi.security.session_tokens import hash_token, new_token


class AlreadyInitializedError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class LoginResult:
    admin: AdminSummary
    session_token: str
    csrf_token: str


def initialize_admin(session: Session, request: SetupRequest) -> SetupStatus:
    if session.scalar(select(AdminUser.id).limit(1)) is not None:
        raise AlreadyInitializedError

    session.add(
        AdminUser(
            id=1,
            username=request.username,
            password_hash=hash_password(request.password),
            locale=request.locale,
        )
    )
    settings = session.get(AppSetting, 1)
    if settings is None:
        session.add(
            AppSetting(id=1, default_locale=request.locale, tool_login_enabled=False)
        )
    else:
        settings.default_locale = request.locale
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AlreadyInitializedError from exc
    return SetupStatus(initialized=True, locale=request.locale)


def authenticate_admin(
    session: Session,
    username: str,
    password: str,
    idle_minutes: int,
    absolute_hours: int,
) -> LoginResult:
    admin = session.scalar(
        select(AdminUser).where(AdminUser.username == username, AdminUser.enabled.is_(True))
    )
    if admin is None or not verify_password(password, admin.password_hash):
        raise InvalidCredentialsError

    now = datetime.now(UTC).replace(tzinfo=None)
    session_token = new_token()
    csrf_token = new_token()
    session.add(
        AdminSession(
            admin_id=admin.id,
            token_hash=hash_token(session_token),
            csrf_hash=hash_token(csrf_token),
            idle_expires_at=now + timedelta(minutes=idle_minutes),
            absolute_expires_at=now + timedelta(hours=absolute_hours),
        )
    )
    session.commit()
    return LoginResult(
        admin=AdminSummary(username=admin.username, locale=admin.locale),
        session_token=session_token,
        csrf_token=csrf_token,
    )
