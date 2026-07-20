from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.models.admin import AdminUser
from chatapi.models.app_setting import AppSetting
from chatapi.schemas.setup import SetupRequest, SetupStatus
from chatapi.security.passwords import hash_password


class AlreadyInitializedError(Exception):
    pass


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
    session.add(AppSetting(id=1, default_locale=request.locale, tool_login_enabled=False))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AlreadyInitializedError from exc
    return SetupStatus(initialized=True, locale=request.locale)
