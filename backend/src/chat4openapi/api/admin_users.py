from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chat4openapi.api.admin_auth import AdminContext, require_system_admin, require_system_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.models import AdminSession, AdminUser
from chat4openapi.schemas.auth import NewPasswordRequest
from chat4openapi.schemas.users import UserCreateRequest, UserResponse, UserUpdateRequest
from chat4openapi.security.passwords import hash_password

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def _ordinary_user(context: AdminContext, user_id: int) -> AdminUser:
    user = context.db.get(AdminUser, user_id)
    if user is None or user.role != "user":
        raise ApiError(404, "users.not_found")
    return user


def _response(user: AdminUser) -> UserResponse:
    return UserResponse.model_validate(user)


def _commit(context: AdminContext) -> None:
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "users.username_conflict") from exc


def _revoke_sessions(context: AdminContext, user_id: int) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    sessions = context.db.scalars(
        select(AdminSession).where(
            AdminSession.admin_id == user_id,
            AdminSession.revoked_at.is_(None),
        )
    )
    for session in sessions:
        session.revoked_at = now


@router.get("", response_model=list[UserResponse])
def list_users(
    context: AdminContext = Depends(require_system_admin),
) -> list[UserResponse]:
    users = context.db.scalars(
        select(AdminUser).where(AdminUser.role == "user").order_by(AdminUser.id)
    ).all()
    return [_response(user) for user in users]


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreateRequest,
    context: AdminContext = Depends(require_system_csrf),
) -> UserResponse:
    user = AdminUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="user",
        locale=payload.locale,
        enabled=payload.enabled,
    )
    context.db.add(user)
    _commit(context)
    return _response(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    context: AdminContext = Depends(require_system_csrf),
) -> UserResponse:
    user = _ordinary_user(context, user_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(user, key, value)
    if values.get("enabled") is False:
        _revoke_sessions(context, user.id)
    _commit(context)
    return _response(user)


@router.put("/{user_id}/password", status_code=204)
def reset_user_password(
    user_id: int,
    payload: NewPasswordRequest,
    context: AdminContext = Depends(require_system_csrf),
) -> None:
    user = _ordinary_user(context, user_id)
    user.password_hash = hash_password(payload.new_password)
    _revoke_sessions(context, user.id)
    _commit(context)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    context: AdminContext = Depends(require_system_csrf),
) -> None:
    user = _ordinary_user(context, user_id)
    context.db.delete(user)
    context.db.commit()
