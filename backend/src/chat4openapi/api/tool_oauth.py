from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.api.tool_sessions import (
    TOOL_SESSION_COOKIE,
    _creation_agent_id,
    get_tool_secret_cipher,
    get_tool_session_mutation_owner,
)
from chat4openapi.config import Settings, get_settings
from chat4openapi.db.session import get_db_session
from chat4openapi.embed.grants import create_auth_grant
from chat4openapi.models import AppSetting
from chat4openapi.security.agent_keys import AgentKeyContext, require_agent_api_key
from chat4openapi.security.encryption import SecretCipher, SecretDecryptionError
from chat4openapi.tool_sessions.oauth import (
    OAuthFlowError,
    OAuthPollingTooSoon,
    OAuthStatus,
    ToolOAuthService,
)
from chat4openapi.tools.network_policy import UnsafeNetworkTarget, validate_network_target

router = APIRouter(tags=["tool-oauth"])


class OAuthConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=2048)
    token_endpoint_auth_method: Literal[
        "auto", "client_secret_basic", "client_secret_post", "none"
    ] | None = None
    token_headers: dict[str, str] = Field(default_factory=dict, max_length=32)
    token_params: dict[str, str] = Field(default_factory=dict, max_length=64)
    authorization_url: str | None = Field(default=None, max_length=2048)
    token_url: str = Field(min_length=1, max_length=2048)
    device_authorization_url: str | None = Field(default=None, max_length=2048)
    redirect_uri: str | None = Field(default=None, max_length=2048)
    scopes: list[str] = Field(default_factory=list, max_length=100)


class OAuthConfigSummary(BaseModel):
    api_source_id: int
    enabled: bool
    client_id: str
    has_client_secret: bool
    token_endpoint_auth_method: Literal[
        "auto", "client_secret_basic", "client_secret_post", "none"
    ]
    token_headers: dict[str, str]
    token_params: dict[str, str]
    authorization_url: str | None
    token_url: str
    device_authorization_url: str | None
    redirect_uri: str | None
    scopes: list[str]
    recommended_redirect_uri: str | None
    effective_redirect_uri: str | None


class OAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_source_id: int = Field(gt=0)
    agent_id: int | None = Field(default=None, gt=0)


class OAuthRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_session_id: str = Field(min_length=1, max_length=512)
    api_source_id: int = Field(gt=0)


class DeviceFlowResponse(BaseModel):
    tool_session_id: str
    status: str
    api_source_id: int
    expires_at: datetime
    interval: int | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None


class PKCEStartResponse(BaseModel):
    authorization_url: str
    expires_at: datetime


class OAuthReadyResponse(BaseModel):
    status: str
    api_source_id: int
    expires_at: datetime


class OAuthTestResponse(BaseModel):
    success: bool
    status: int


def get_oauth_transport() -> httpx.AsyncBaseTransport | None:
    return None


def get_oauth_network_validator() -> Callable[[httpx.URL, bool], Awaitable[None]]:
    return validate_network_target


def get_tool_oauth_service(
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    transport: httpx.AsyncBaseTransport | None = Depends(get_oauth_transport),
    network_validator: Callable[[httpx.URL, bool], Awaitable[None]] = Depends(
        get_oauth_network_validator
    ),
) -> ToolOAuthService:
    return ToolOAuthService(
        db,
        cipher,
        transport=transport,
        network_validator=network_validator,
    )


def _oauth_error(exc: Exception) -> ApiError:
    if isinstance(exc, OAuthPollingTooSoon):
        return ApiError(429, exc.code, retry_after=exc.retry_after)
    if isinstance(exc, OAuthFlowError):
        status = 404 if exc.code in {"oauth.source_not_found", "oauth.session_not_found"} else 400
        if exc.code in {"oauth.not_configured", "oauth.device_not_configured", "oauth.pkce_not_configured"}:
            status = 409
        return ApiError(status, exc.code)
    if isinstance(exc, (SecretDecryptionError, UnsafeNetworkTarget)):
        return ApiError(400, "oauth.upstream_failed")
    return ApiError(500, "oauth.failed")


def _device_response(status: OAuthStatus) -> DeviceFlowResponse:
    return DeviceFlowResponse(
        tool_session_id=status.tool_session_id,
        status=status.status,
        api_source_id=status.api_source_id,
        expires_at=status.expires_at,
        interval=status.interval,
        user_code=status.user_code,
        verification_uri=status.verification_uri,
        verification_uri_complete=status.verification_uri_complete,
    )


def _config_summary(
    service: ToolOAuthService, db: Session, source_id: int
) -> OAuthConfigSummary:
    summary = service.config_summary(source_id)
    settings = db.get(AppSetting, 1)
    recommended = (
        f"{settings.base_url}/api/tool-sessions/oauth/pkce/callback"
        if settings is not None and settings.base_url is not None
        else None
    )
    return OAuthConfigSummary.model_validate(
        {
            **summary,
            "recommended_redirect_uri": recommended,
            "effective_redirect_uri": summary.get("redirect_uri") or recommended,
        }
    )


@router.put(
    "/api/admin/sources/{source_id}/oauth", response_model=OAuthConfigSummary
)
def configure_oauth(
    source_id: int,
    payload: OAuthConfigRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
) -> OAuthConfigSummary:
    service = ToolOAuthService(context.db, cipher)
    try:
        service.configure_source(source_id, payload.model_dump())
        return _config_summary(service, context.db, source_id)
    except Exception as exc:
        raise _oauth_error(exc) from exc


@router.get(
    "/api/admin/sources/{source_id}/oauth", response_model=OAuthConfigSummary
)
def oauth_config(
    source_id: int,
    context: AdminContext = Depends(require_admin),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
) -> OAuthConfigSummary:
    try:
        return _config_summary(
            ToolOAuthService(context.db, cipher), context.db, source_id
        )
    except Exception as exc:
        raise _oauth_error(exc) from exc


@router.post(
    "/api/tool-sessions/oauth/device/start",
    response_model=DeviceFlowResponse,
    status_code=201,
)
async def start_device(
    payload: OAuthStartRequest,
    owner: AgentKeyContext = Depends(require_agent_api_key),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
) -> DeviceFlowResponse:
    if payload.agent_id is not None and payload.agent_id != owner.agent.id:
        raise ApiError(403, "auth.agent_key_forbidden")
    try:
        return _device_response(await service.start_device(owner, payload.api_source_id))
    except Exception as exc:
        raise _oauth_error(exc) from exc


@router.get(
    "/api/tool-sessions/{tool_session_id}/status",
    response_model=DeviceFlowResponse,
)
async def poll_device(
    tool_session_id: str,
    owner: AgentKeyContext = Depends(require_agent_api_key),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
) -> DeviceFlowResponse:
    try:
        return _device_response(await service.poll_device(tool_session_id, owner))
    except Exception as exc:
        raise _oauth_error(exc) from exc


@router.post(
    "/api/tool-sessions/oauth/pkce/start",
    response_model=PKCEStartResponse,
    status_code=201,
)
async def start_pkce(
    payload: OAuthStartRequest,
    owner: AdminContext = Depends(require_csrf),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
) -> PKCEStartResponse:
    try:
        agent_id = _creation_agent_id(owner.db, owner, payload.agent_id)
        started = await service.start_pkce(
            owner, payload.api_source_id, agent_id=agent_id
        )
        return PKCEStartResponse(
            authorization_url=started.authorization_url,
            expires_at=started.expires_at,
        )
    except Exception as exc:
        raise _oauth_error(exc) from exc


@router.get(
    "/api/tool-sessions/oauth/pkce/callback", response_model=OAuthReadyResponse
)
async def pkce_callback(
    response: Response,
    state: str = Query(min_length=1, max_length=512),
    code: str | None = Query(default=None, min_length=1, max_length=4096),
    error: str | None = Query(default=None, min_length=1, max_length=256),
    error_description: str | None = Query(default=None, max_length=2048),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
    settings: Settings = Depends(get_settings),
):
    del error_description
    try:
        if (code is None) == (error is None):
            raise OAuthFlowError("oauth.callback_invalid")
        if error is not None:
            completed = service.reject_pkce(state)
        else:
            completed = await service.complete_pkce(state, code)
    except Exception as exc:
        raise _oauth_error(exc) from exc


    if error is not None:
        target_origin = completed.target_origin or completed.popup_origin
        if target_origin is None:
            raise ApiError(
                400,
                "oauth.authorization_denied"
                if error == "access_denied"
                else "oauth.authorization_failed",
            )
        payload = json.dumps(
            {
                "type": "chat4openapi:auth-error",
                "api_source_id": completed.api_source_id,
                "error": (
                    "access_denied"
                    if error == "access_denied"
                    else "authorization_failed"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return HTMLResponse(
            "<!doctype html><script>"
            f"window.opener.postMessage({payload},{json.dumps(target_origin)});"
            "window.close()"
            "</script>",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )
    if (
        completed.embed_session_id is not None
        and completed.tool_session_db_id is not None
        and completed.target_origin is not None
    ):
        grant = create_auth_grant(
            service._session,
            completed.embed_session_id,
            completed.tool_session_db_id,
            completed.api_source_id,
        )
        service._session.commit()
        payload = json.dumps(
            {"type": "chat4openapi:auth-grant", "grant": grant},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        target_origin = json.dumps(completed.target_origin)
        return HTMLResponse(
            "<!doctype html><script>"
            f"window.opener.postMessage({payload},{target_origin});window.close()"
            "</script>",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )
    if (
        completed.browser_chat_session_id is not None
        and completed.popup_origin is not None
    ):
        payload = json.dumps(
            {
                "type": "chat4openapi:auth-complete",
                "api_source_id": completed.api_source_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        target_origin = json.dumps(completed.popup_origin)
        return HTMLResponse(
            "<!doctype html><script>"
            f"window.opener.postMessage({payload},{target_origin});window.close()"
            "</script>",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )
    response.set_cookie(
        TOOL_SESSION_COOKIE,
        completed.tool_session_id,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
        max_age=max(
            1,
            int(
                (
                    completed.expires_at
                    - datetime.now(UTC).replace(tzinfo=None)
                ).total_seconds()
            ),
        ),
    )
    return OAuthReadyResponse(
        status=completed.status,
        api_source_id=completed.api_source_id,
        expires_at=completed.expires_at,
    )


@router.post(
    "/api/admin/sources/{source_id}/oauth/test",
    response_model=OAuthTestResponse,
)
async def test_oauth_config(
    source_id: int,
    context: AdminContext = Depends(require_csrf),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
) -> OAuthTestResponse:
    del context
    try:
        result = await service.test_source(source_id)
        return OAuthTestResponse(success=True, status=result)
    except OAuthFlowError as exc:
        params = getattr(exc, "params", {})
        if params:
            raise ApiError(400, exc.code, **params) from exc
        raise _oauth_error(exc) from exc


@router.post("/api/tool-sessions/oauth/refresh", response_model=OAuthReadyResponse)
async def refresh_oauth(
    payload: OAuthRefreshRequest,
    owner: AgentKeyContext | AdminContext = Depends(get_tool_session_mutation_owner),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
) -> OAuthReadyResponse:
    try:
        refreshed = await service.refresh(
            payload.tool_session_id, owner, payload.api_source_id
        )
        return OAuthReadyResponse(
            status=refreshed.status,
            api_source_id=refreshed.api_source_id,
            expires_at=refreshed.expires_at,
        )
    except Exception as exc:
        raise _oauth_error(exc) from exc
