from fastapi import APIRouter, Depends

from chat4openapi.api.admin_auth import (
    AdminContext,
    require_system_admin,
    require_system_csrf,
)
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import AppSetting
from chat4openapi.schemas.settings import AppSettingsResponse, AppSettingsWrite

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


@router.get("", response_model=AppSettingsResponse)
def get_app_settings(
    context: AdminContext = Depends(require_system_admin),
) -> AppSettingsResponse:
    settings = context.db.get(AppSetting, 1)
    if settings is None:
        settings = AppSetting(id=1)
        context.db.add(settings)
        context.db.commit()
        context.db.refresh(settings)
    return AppSettingsResponse.model_validate(settings)


@router.put("", response_model=AppSettingsResponse)
def update_app_settings(
    payload: AppSettingsWrite,
    context: AdminContext = Depends(require_system_csrf),
) -> AppSettingsResponse:
    with serialized_write(context.db):
        settings = context.db.get(AppSetting, 1)
        if settings is None:
            settings = AppSetting(id=1)
            context.db.add(settings)
        settings.base_url = payload.base_url
        context.db.flush()
    return AppSettingsResponse.model_validate(settings)
