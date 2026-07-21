from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.db.session import get_db_session
from chat4openapi.models.admin import AdminUser
from chat4openapi.models.app_setting import AppSetting
from chat4openapi.schemas.setup import SetupRequest, SetupStatus
from chat4openapi.services.admin_auth import AlreadyInitializedError, initialize_admin

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
def setup_status(session: Session = Depends(get_db_session)) -> SetupStatus:
    admin_exists = session.scalar(select(AdminUser.id).limit(1)) is not None
    if not admin_exists:
        return SetupStatus(initialized=False)
    locale = session.scalar(select(AppSetting.default_locale).where(AppSetting.id == 1))
    return SetupStatus(initialized=True, locale=locale)


@router.post("", response_model=SetupStatus, status_code=201)
def setup(request: SetupRequest, session: Session = Depends(get_db_session)) -> SetupStatus:
    try:
        return initialize_admin(session, request)
    except AlreadyInitializedError as exc:
        raise ApiError(409, "setup.already_initialized") from exc
