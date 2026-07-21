from datetime import UTC, datetime
from functools import lru_cache
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.api.admin_auth import ADMIN_COOKIE, AdminContext, require_admin
from chat4openapi.api.errors import ApiError
from chat4openapi.config import Settings, get_settings
from chat4openapi.db.session import get_db_session
from chat4openapi.models import (
    Agent,
    ApiSource,
    GlobalToolAuthConfig,
    Tool,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.schemas.tools import (
    ToolCredentialInjectionRequest,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolSessionCreated,
    ToolSessionLoginRequest,
    ToolSessionStatus,
)
from chat4openapi.security.agent_keys import AgentKeyContext, require_agent_api_key
from chat4openapi.security.encryption import SecretCipher, SecretDecryptionError, load_secret_cipher
from chat4openapi.security.session_tokens import hash_token
from chat4openapi.tool_sessions.auth_mapping import AuthMappingError
from chat4openapi.tool_sessions.credentials import CredentialValidationError
from chat4openapi.tool_sessions.service import (
    ToolLoginDisabled,
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionReauthorizationRequired,
    ToolSessionService,
)
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.executor import RequestAuth, ToolExecutor

TOOL_SESSION_COOKIE = "chat4openapi_tool_session"
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


def get_optional_tool_session_owner(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AgentKeyContext | AdminContext | None:
    if authorization:
        return require_agent_api_key(authorization, db)
    if request.cookies.get(ADMIN_COOKIE):
        return require_admin(request, db, settings)
    return None


def get_tool_session_owner(
    context: AgentKeyContext | AdminContext | None = Depends(get_optional_tool_session_owner),
) -> AgentKeyContext | AdminContext:
    if context is None:
        raise ApiError(401, "auth.api_key_required")
    return context


def _creation_agent_id(
    db: Session, context: AgentKeyContext | AdminContext, requested: int | None
) -> int:
    if isinstance(context, AgentKeyContext):
        if requested is not None and requested != context.agent.id:
            raise ApiError(403, "auth.agent_key_forbidden")
        return context.agent.id
    if requested is not None:
        agent = db.get(Agent, requested)
    else:
        agent = db.scalar(
            select(Agent).where(
                Agent.is_default.is_(True),
                Agent.enabled.is_(True),
                Agent.deleted_at.is_(None),
            )
        )
    if agent is None or agent.deleted_at is not None or not agent.enabled:
        raise ApiError(404, "agents.not_found")
    return agent.id


def _created_response(created, *, expose_token: bool) -> ToolSessionCreated:
    return ToolSessionCreated(
        tool_session_id=created.token if expose_token else None,
        idle_expires_at=created.idle_expires_at,
        absolute_expires_at=created.absolute_expires_at,
        status=created.status,
        api_source_ids=list(created.api_source_ids),
    )


async def _status_response(
    token: str,
    owner: AgentKeyContext | AdminContext,
    service: ToolSessionService,
) -> ToolSessionStatus:
    agent_id, key_id, admin_session_id = service.binding_for_context(token, owner)
    row = service._session.scalar(
        select(ToolUserSession).where(ToolUserSession.token_hash == hash_token(token))
    )
    if row is None:
        raise ToolSessionNotFound("Tool Session was not found")
    source_ids = list(
        service._session.scalars(
            select(ToolSessionCredential.api_source_id)
            .where(ToolSessionCredential.tool_session_id == row.id)
            .order_by(ToolSessionCredential.api_source_id)
        )
    )
    if not source_ids:
        raise ToolSessionNotFound("Tool Session was not found")
    resolved = await service.resolve(
        token,
        agent_id,
        key_id,
        source_ids[0],
        admin_session_id=admin_session_id,
    )
    return ToolSessionStatus(
        idle_expires_at=resolved.idle_expires_at,
        absolute_expires_at=resolved.absolute_expires_at,
        status=resolved.status,
        api_source_ids=source_ids,
    )


@router.get("/api/tool-session/config")
def browser_config(db: Session = Depends(get_db_session)) -> dict[str, bool]:
    config = db.get(GlobalToolAuthConfig, 1)
    return {"enabled": bool(config is not None and config.enabled)}


def _session_error(exc: Exception) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, ToolLoginDisabled):
        return ApiError(409, "tool_session.login_disabled")
    if isinstance(exc, ToolSessionExpired):
        return ApiError(401, "tool_reauthorization_required")
    if isinstance(exc, ToolSessionReauthorizationRequired):
        return ApiError(401, "tool_reauthorization_required")
    if isinstance(exc, ToolSessionNotFound):
        return ApiError(401, "tool_session.required")
    if isinstance(exc, (ToolExecutionError, AuthMappingError, SecretDecryptionError)):
        return ApiError(401, "tool_session.login_failed")
    if isinstance(exc, CredentialValidationError):
        return ApiError(422, exc.code)
    return ApiError(500, "tool_session.failed")


@router.post("/api/tool-session/login", response_model=ToolSessionCreated)
async def browser_login(
    payload: ToolSessionLoginRequest,
    response: Response,
    service: ToolSessionService = Depends(get_tool_session_service),
    settings: Settings = Depends(get_settings),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> ToolSessionCreated:
    try:
        created = await service.create(
            payload.username,
            payload.password,
            context=owner,
            agent_id=_creation_agent_id(owner.db, owner, payload.agent_id),
        )
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
    return _created_response(created, expose_token=False)


@router.get("/api/tool-session/status", response_model=ToolSessionStatus)
async def browser_status(
    tool_session_id: str | None = Cookie(default=None, alias=TOOL_SESSION_COOKIE),
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> ToolSessionStatus:
    if not tool_session_id:
        raise ApiError(401, "tool_session.required")
    try:
        return await _status_response(tool_session_id, owner, service)
    except Exception as exc:
        raise _session_error(exc) from exc


@router.post("/api/tool-session/logout", status_code=204)
async def browser_logout(
    response: Response,
    tool_session_id: str | None = Cookie(default=None, alias=TOOL_SESSION_COOKIE),
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> None:
    if tool_session_id:
        try:
            binding = service.binding_for_context(tool_session_id, owner)
            await service.revoke(
                tool_session_id,
                binding[0],
                binding[1],
                admin_session_id=binding[2],
            )
        except ToolSessionNotFound:
            pass
    response.delete_cookie(TOOL_SESSION_COOKIE, path="/")


@router.post("/v1/tool-sessions", response_model=ToolSessionCreated, status_code=201)
async def api_login(
    payload: ToolSessionLoginRequest,
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> ToolSessionCreated:
    try:
        created = await service.create(
            payload.username,
            payload.password,
            context=owner,
            agent_id=_creation_agent_id(owner.db, owner, payload.agent_id),
        )
    except Exception as exc:
        raise _session_error(exc) from exc
    return _created_response(created, expose_token=True)


@router.post(
    "/api/tool-sessions/credentials", response_model=ToolSessionCreated, status_code=201
)
async def inject_credentials(
    payload: ToolCredentialInjectionRequest,
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> ToolSessionCreated:
    try:
        created = await service.create_injected(
            owner,
            {
                payload.api_source_id: {
                    "headers": payload.headers,
                    "cookies": payload.cookies,
                }
            },
            payload.expires_at,
            agent_id=_creation_agent_id(owner.db, owner, payload.agent_id),
        )
    except Exception as exc:
        raise _session_error(exc) from exc
    return _created_response(created, expose_token=True)


@router.get("/api/tool-sessions/{tool_session_id}", response_model=ToolSessionStatus)
async def api_status(
    tool_session_id: str,
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> ToolSessionStatus:
    try:
        return await _status_response(tool_session_id, owner, service)
    except Exception as exc:
        raise _session_error(exc) from exc


@router.delete("/api/tool-sessions/{tool_session_id}", status_code=204)
async def revoke_session(
    tool_session_id: str,
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> None:
    try:
        binding = service.binding_for_context(tool_session_id, owner)
        await service.revoke(
            tool_session_id,
            binding[0],
            binding[1],
            admin_session_id=binding[2],
        )
    except Exception as exc:
        raise _session_error(exc) from exc


@router.delete("/v1/tool-sessions/{tool_session_id}", status_code=204)
async def api_logout(
    tool_session_id: str,
    service: ToolSessionService = Depends(get_tool_session_service),
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_owner),
) -> None:
    try:
        binding = service.binding_for_context(tool_session_id, owner)
        await service.revoke(
            tool_session_id,
            binding[0],
            binding[1],
            admin_session_id=binding[2],
        )
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
    owner: AgentKeyContext | AdminContext | None = Depends(get_optional_tool_session_owner),
) -> ToolInvokeResponse:
    tool = db.get(Tool, tool_id)
    if tool is None or tool.deleted_at is not None or not tool.enabled:
        raise ApiError(404, "tools.not_found")
    config = db.get(GlobalToolAuthConfig, 1)
    if config is not None and config.enabled and config.login_tool_id == tool.id:
        raise ApiError(404, "tools.not_found")
    token = payload.tool_session_id or request.cookies.get(TOOL_SESSION_COOKIE)
    try:
        if token:
            if owner is None:
                raise ToolSessionNotFound
            binding = service.binding_for_context(token, owner)
            result = await service.execute(
                tool,
                payload.arguments,
                token,
                agent_id=binding[0],
                agent_key_id=binding[1],
                admin_session_id=binding[2],
            )
        elif config is not None and config.enabled:
            if not token:
                raise ToolSessionNotFound
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
