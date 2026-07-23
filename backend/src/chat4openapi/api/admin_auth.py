import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.config import Settings, get_settings
from chat4openapi.db.session import get_db_session
from chat4openapi.models.admin import AdminUser
from chat4openapi.models.admin_session import AdminSession
from chat4openapi.schemas.auth import (
    AdminSummary,
    AdminPasswordResetIssued,
    AdminPasswordResetRequest,
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
)
from chat4openapi.security.passwords import (
    hash_password,
    verify_password,
)
from chat4openapi.security.session_tokens import hash_token, new_token
from chat4openapi.services.admin_auth import InvalidCredentialsError, authenticate_admin
from chat4openapi.services.password_reset import (
    PasswordResetCredentialError,
    consume_admin_password_reset,
    issue_admin_password_reset,
)

ADMIN_COOKIE = "chat4openapi_admin_session"

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


@dataclass
class AdminContext:
    admin: AdminUser
    admin_session: AdminSession
    db: Session


def require_admin(
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AdminContext:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise ApiError(401, "auth.required")

    admin_session = db.scalar(
        select(AdminSession).where(AdminSession.token_hash == hash_token(token))
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    if admin_session is None or admin_session.revoked_at is not None:
        raise ApiError(401, "auth.session_invalid")
    if admin_session.idle_expires_at <= now or admin_session.absolute_expires_at <= now:
        admin_session.revoked_at = now
        db.commit()
        raise ApiError(401, "auth.session_expired")

    admin = db.get(AdminUser, admin_session.admin_id)
    if admin is None or not admin.enabled:
        raise ApiError(401, "auth.session_invalid")

    next_idle_expiry = now + timedelta(minutes=settings.admin_session_idle_minutes)
    admin_session.idle_expires_at = min(next_idle_expiry, admin_session.absolute_expires_at)
    db.commit()
    return AdminContext(admin=admin, admin_session=admin_session, db=db)


def require_csrf(
    context: AdminContext = Depends(require_admin),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AdminContext:
    if csrf_token is None or not secrets.compare_digest(
        hash_token(csrf_token), context.admin_session.csrf_hash
    ):
        raise ApiError(403, "auth.csrf_invalid")
    return context


def require_system_admin(
    context: AdminContext = Depends(require_admin),
) -> AdminContext:
    if context.admin.role != "admin":
        raise ApiError(403, "auth.system_admin_required")
    return context


def require_system_csrf(
    context: AdminContext = Depends(require_csrf),
) -> AdminContext:
    if context.admin.role != "admin":
        raise ApiError(403, "auth.system_admin_required")
    return context


def revoke_admin_sessions(
    db: Session,
    admin_id: int,
    *,
    now: datetime | None = None,
) -> None:
    revoked_at = now or datetime.now(UTC).replace(tzinfo=None)
    sessions = db.scalars(
        select(AdminSession).where(
            AdminSession.admin_id == admin_id,
            AdminSession.revoked_at.is_(None),
        )
    )
    for admin_session in sessions:
        admin_session.revoked_at = revoked_at


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    try:
        result = authenticate_admin(
            db,
            username=payload.username,
            password=payload.password,
            idle_minutes=settings.admin_session_idle_minutes,
            absolute_hours=settings.admin_session_absolute_hours,
        )
    except InvalidCredentialsError as exc:
        raise ApiError(401, "auth.invalid_credentials") from exc

    response.set_cookie(
        ADMIN_COOKIE,
        result.session_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
        max_age=settings.admin_session_absolute_hours * 60 * 60,
    )
    return AuthResponse(admin=result.admin, csrf_token=result.csrf_token)


@router.get("/me", response_model=AuthResponse)
def me(context: AdminContext = Depends(require_admin)) -> AuthResponse:
    csrf_token = new_token()
    context.admin_session.csrf_hash = hash_token(csrf_token)
    context.db.commit()
    return AuthResponse(
        admin=AdminSummary(
            username=context.admin.username,
            locale=context.admin.locale,
            role=context.admin.role,
        ),
        csrf_token=csrf_token,
    )


@router.post("/logout", status_code=204)
def logout(response: Response, context: AdminContext = Depends(require_csrf)) -> None:
    context.admin_session.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    context.db.commit()
    response.delete_cookie(ADMIN_COOKIE, path="/")


@router.put("/password", status_code=204)
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    context: AdminContext = Depends(require_csrf),
) -> None:
    if not verify_password(payload.current_password, context.admin.password_hash):
        raise ApiError(400, "auth.current_password_invalid")
    context.admin.password_hash = hash_password(payload.new_password)
    revoke_admin_sessions(context.db, context.admin.id)
    context.db.commit()
    response.delete_cookie(ADMIN_COOKIE, path="/")


@router.post(
    "/password-reset/request",
    response_model=AdminPasswordResetIssued,
    status_code=201,
)
def request_password_reset(
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AdminPasswordResetIssued:
    admin_id = db.scalar(
        select(AdminUser.id).where(
            AdminUser.role == "admin",
            AdminUser.enabled.is_(True),
        )
    )
    if admin_id is None:
        raise ApiError(409, "auth.reset_unavailable")
    issued = issue_admin_password_reset(settings)
    return AdminPasswordResetIssued(
        credential_path=str(issued.path),
        expires_at=issued.expires_at,
    )


@router.post("/password-reset/complete", status_code=204)
def complete_password_reset(
    payload: AdminPasswordResetRequest,
    response: Response,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> None:
    admin = db.scalar(
        select(AdminUser).where(
            AdminUser.role == "admin",
            AdminUser.enabled.is_(True),
        )
    )
    if admin is None:
        raise ApiError(409, "auth.reset_unavailable")
    try:
        consume_admin_password_reset(settings, payload.key)
    except PasswordResetCredentialError as exc:
        raise ApiError(400, exc.code) from exc
    admin.password_hash = hash_password(payload.new_password)
    revoke_admin_sessions(db, admin.id)
    db.commit()
    response.delete_cookie(ADMIN_COOKIE, path="/")
