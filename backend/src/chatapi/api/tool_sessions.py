from functools import lru_cache
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session

from chatapi.api.errors import ApiError
from chatapi.config import Settings, get_settings
from chatapi.db.session import get_db_session
from chatapi.models import ApiSource, GlobalToolAuthConfig, Tool
from chatapi.schemas.tools import (
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolSessionCreated,
    ToolSessionLoginRequest,
    ToolSessionStatus,
)
from chatapi.security.encryption import SecretCipher, SecretDecryptionError, load_secret_cipher
from chatapi.tool_sessions.auth_mapping import AuthMappingError
from chatapi.tool_sessions.service import (
    ToolLoginDisabled,
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionService,
)
from chatapi.tools.errors import ToolExecutionError
from chatapi.tools.executor import RequestAuth, ToolExecutor

TOOL_SESSION_COOKIE = "chatapi_tool_session"
router = APIRouter(tags=["tool-sessions"])


def get_tool_executor() -> ToolExecutor:
    return ToolExecutor()


@lru_cache
def _cached_cipher(key: str | None, key_file: str) -> SecretCipher:
    from pathlib import Path

    return load_secret_cipher(key, Path(key_file))


def get_tool_secret_cipher(settings: Settings = Depends(get_settings)) -> SecretCipher:
    return _cached_cipher(settings.encryption_key, str(settings.encryption_key_file))


def get_tool_session_service(
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    executor: ToolExecutor = Depends(get_tool_executor),
) -> ToolSessionService:
    return ToolSessionService(db, cipher, executor)


@router.get("/api/tool-session/config")
def browser_config(db: Session = Depends(get_db_session)) -> dict[str, bool]:
    config = db.get(GlobalToolAuthConfig, 1)
    return {"enabled": bool(config is not None and config.enabled)}


def _session_error(exc: Exception) -> ApiError:
    if isinstance(exc, ToolLoginDisabled):
        return ApiError(409, "tool_session.login_disabled")
    if isinstance(exc, ToolSessionExpired):
        return ApiError(401, "tool_session.expired")
    if isinstance(exc, ToolSessionNotFound):
        return ApiError(401, "tool_session.required")
    if isinstance(exc, (ToolExecutionError, AuthMappingError, SecretDecryptionError)):
        return ApiError(401, "tool_session.login_failed")
    return ApiError(500, "tool_session.failed")


@router.post("/api/tool-session/login", response_model=ToolSessionCreated)
async def browser_login(
    payload: ToolSessionLoginRequest,
    response: Response,
    service: ToolSessionService = Depends(get_tool_session_service),
    settings: Settings = Depends(get_settings),
) -> ToolSessionCreated:
    try:
        created = await service.create(payload.username, payload.password)
    except Exception as exc:
        raise _session_error(exc) from exc
    response.set_cookie(
        TOOL_SESSION_COOKIE,
        created.token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
        max_age=max(
            1,
            int(
                (
                    created.absolute_expires_at
                    - datetime.now(UTC).replace(tzinfo=None)
                ).total_seconds()
            ),
        ),
    )
    return ToolSessionCreated(
        idle_expires_at=created.idle_expires_at,
        absolute_expires_at=created.absolute_expires_at,
    )


@router.get("/api/tool-session/status", response_model=ToolSessionStatus)
async def browser_status(
    tool_session_id: str | None = Cookie(default=None, alias=TOOL_SESSION_COOKIE),
    service: ToolSessionService = Depends(get_tool_session_service),
) -> ToolSessionStatus:
    if not tool_session_id:
        raise ApiError(401, "tool_session.required")
    try:
        resolved = await service.resolve(tool_session_id)
    except Exception as exc:
        raise _session_error(exc) from exc
    return ToolSessionStatus(
        idle_expires_at=resolved.idle_expires_at,
        absolute_expires_at=resolved.absolute_expires_at,
    )


@router.post("/api/tool-session/logout", status_code=204)
async def browser_logout(
    response: Response,
    tool_session_id: str | None = Cookie(default=None, alias=TOOL_SESSION_COOKIE),
    service: ToolSessionService = Depends(get_tool_session_service),
) -> None:
    if tool_session_id:
        try:
            await service.revoke(tool_session_id)
        except ToolSessionNotFound:
            pass
    response.delete_cookie(TOOL_SESSION_COOKIE, path="/")


@router.post("/v1/tool-sessions", response_model=ToolSessionCreated, status_code=201)
async def api_login(
    payload: ToolSessionLoginRequest,
    service: ToolSessionService = Depends(get_tool_session_service),
) -> ToolSessionCreated:
    try:
        created = await service.create(payload.username, payload.password)
    except Exception as exc:
        raise _session_error(exc) from exc
    return ToolSessionCreated(
        tool_session_id=created.token,
        idle_expires_at=created.idle_expires_at,
        absolute_expires_at=created.absolute_expires_at,
    )


@router.delete("/v1/tool-sessions/{tool_session_id}", status_code=204)
async def api_logout(
    tool_session_id: str,
    service: ToolSessionService = Depends(get_tool_session_service),
) -> None:
    try:
        await service.revoke(tool_session_id)
    except ToolSessionNotFound:
        pass


@router.post("/api/tools/{tool_id}/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(
    tool_id: int,
    payload: ToolInvokeRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    service: ToolSessionService = Depends(get_tool_session_service),
    executor: ToolExecutor = Depends(get_tool_executor),
) -> ToolInvokeResponse:
    tool = db.get(Tool, tool_id)
    if tool is None or tool.deleted_at is not None or not tool.enabled:
        raise ApiError(404, "tools.not_found")
    config = db.get(GlobalToolAuthConfig, 1)
    if config is not None and config.enabled and config.login_tool_id == tool.id:
        raise ApiError(404, "tools.not_found")
    token = payload.tool_session_id or request.cookies.get(TOOL_SESSION_COOKIE)
    try:
        if config is not None and config.enabled:
            if not token:
                raise ToolSessionNotFound
            result = await service.execute(tool, payload.arguments, token)
        else:
            source = db.get(ApiSource, tool.api_source_id)
            if source is None:
                raise ApiError(404, "tools.source_not_found")
            result = await executor.execute(tool, source, payload.arguments, RequestAuth())
    except (ToolSessionNotFound, ToolSessionExpired, ToolLoginDisabled) as exc:
        raise _session_error(exc) from exc
    except ToolExecutionError as exc:
        raise ApiError(502, "tools.execution_failed", reason=str(exc)) from exc
    return ToolInvokeResponse(
        status_code=result.status_code,
        data=result.data,
        content_type=result.content_type,
    )
