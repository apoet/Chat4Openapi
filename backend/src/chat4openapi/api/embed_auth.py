import html
import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Form, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chat4openapi.api.embed_public import _bearer, _unavailable
from chat4openapi.api.tool_oauth import _oauth_error, get_tool_oauth_service
from chat4openapi.api.tool_sessions import get_tool_session_service
from chat4openapi.db.session import get_db_session
from chat4openapi.embed.grants import (
    AuthGrantError,
    consume_auth_grant,
    create_auth_grant,
)
from chat4openapi.embed.sessions import EmbedUnavailableError, authenticate_embed_session
from chat4openapi.models import (
    AppSetting,
    EmbedSession,
    ToolOAuthAuthorization,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.session_tokens import hash_token, new_token
from chat4openapi.tool_sessions.auth_mapping import build_request_auth
from chat4openapi.tool_sessions.credentials import auth_to_json, credential_expiry
from chat4openapi.tool_sessions.oauth import ToolOAuthService
from chat4openapi.tool_sessions.service import ToolSessionService, utc_now

router = APIRouter(tags=["embed-auth"])


class EmbedAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_source_id: int = Field(gt=0)
    flow: Literal["pkce", "swagger"]


class EmbedAuthStartResponse(BaseModel):
    authorization_url: str


class EmbedAuthExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant: str = Field(min_length=1, max_length=512)


class EmbedAuthExchangeResponse(BaseModel):
    status: Literal["ready"]
    api_source_id: int


def require_embed_auth_session(
    session_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> EmbedSession:
    try:
        return authenticate_embed_session(
            db,
            _bearer(authorization),
            session_id=session_id,
        )
    except EmbedUnavailableError as exc:
        raise _unavailable() from exc


def _callback_uri(db: Session) -> str:
    settings = db.get(AppSetting, 1)
    if settings is None or settings.base_url is None:
        raise _unavailable()
    return f"{settings.base_url}/api/tool-sessions/oauth/pkce/callback"


def _base_url(db: Session) -> str:
    settings = db.get(AppSetting, 1)
    if settings is None or settings.base_url is None:
        raise _unavailable()
    return settings.base_url


def _popup_result(grant: str, target_origin: str) -> HTMLResponse:
    payload = json.dumps(
        {"type": "chat4openapi:auth-grant", "grant": grant},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    origin = json.dumps(target_origin)
    return HTMLResponse(
        "<!doctype html><script>"
        f"window.opener.postMessage({payload},{origin});window.close()"
        "</script>",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        },
    )


def _start_swagger(
    db: Session,
    owner: EmbedSession,
    source_id: int,
    service: ToolSessionService,
) -> str:
    config = service._config()
    login_tool, source = service._login_runtime(config)
    if source.id != source_id:
        raise _unavailable()
    now = utc_now()
    expires_at = min(now + timedelta(minutes=10), owner.absolute_expires_at)
    state = new_token()
    row = ToolUserSession(
        token_hash=hash_token(new_token()),
        agent_id=owner.agent_id,
        embed_session_id=owner.id,
        status="pending",
        idle_expires_at=expires_at,
        absolute_expires_at=expires_at,
        last_used_at=now,
    )
    db.add(row)
    db.flush()
    db.add(
        ToolSessionCredential(
            tool_session_id=row.id,
            api_source_id=source.id,
            encrypted_credentials=service._cipher.encrypt_json({}),
            status="pending",
            expires_at=expires_at,
            last_used_at=now,
        )
    )
    db.add(
        ToolOAuthAuthorization(
            tool_session_id=row.id,
            api_source_id=source.id,
            flow_type="pkce",
            state_hash=hash_token(state),
            encrypted_flow_data=service._cipher.encrypt_json(
                {
                    "kind": "swagger",
                    "embed_session_id": owner.id,
                    "parent_origin": owner.parent_origin,
                    "login_tool_id": login_tool.id,
                    "owner_absolute_expires_at": owner.absolute_expires_at.isoformat(),
                }
            ),
            status="pending",
            expires_at=expires_at,
        )
    )
    db.commit()
    return state


@router.post(
    "/api/embed/sessions/{session_id}/auth/start",
    response_model=EmbedAuthStartResponse,
    status_code=201,
)
async def start_embed_auth(
    payload: EmbedAuthStartRequest,
    owner: EmbedSession = Depends(require_embed_auth_session),
    db: Session = Depends(get_db_session),
    service: ToolOAuthService = Depends(get_tool_oauth_service),
    tool_service: ToolSessionService = Depends(get_tool_session_service),
) -> EmbedAuthStartResponse:
    if payload.flow == "swagger":
        state = _start_swagger(db, owner, payload.api_source_id, tool_service)
        return EmbedAuthStartResponse(
            authorization_url=f"{_base_url(db)}/api/embed/auth/swagger?state={state}"
        )
    try:
        started = await service.start_embed_pkce(
            owner,
            payload.api_source_id,
            redirect_uri=_callback_uri(db),
        )
    except Exception as exc:
        raise _oauth_error(exc) from exc
    return EmbedAuthStartResponse(authorization_url=started.authorization_url)


def _swagger_flow(
    db: Session,
    state: str,
    service: ToolSessionService,
) -> tuple[ToolOAuthAuthorization, ToolUserSession, dict]:
    flow = db.scalar(
        select(ToolOAuthAuthorization).where(
            ToolOAuthAuthorization.state_hash == hash_token(state),
            ToolOAuthAuthorization.flow_type == "pkce",
        )
    )
    now = utc_now()
    if (
        flow is None
        or flow.status != "pending"
        or flow.consumed_at is not None
        or flow.expires_at <= now
    ):
        raise _unavailable()
    data = service._cipher.decrypt_json(flow.encrypted_flow_data)
    row = db.get(ToolUserSession, flow.tool_session_id)
    if not isinstance(data, dict) or data.get("kind") != "swagger" or row is None:
        raise _unavailable()
    return flow, row, data


@router.get("/api/embed/auth/swagger", response_class=HTMLResponse)
def swagger_login_form(
    state: str = Query(min_length=1, max_length=512),
    db: Session = Depends(get_db_session),
    service: ToolSessionService = Depends(get_tool_session_service),
) -> HTMLResponse:
    _swagger_flow(db, state, service)
    escaped_state = html.escape(state, quote=True)
    return HTMLResponse(
        "<!doctype html><html><body><form method=\"post\" action=\"/api/embed/auth/swagger\">"
        f"<input type=\"hidden\" name=\"state\" value=\"{escaped_state}\">"
        "<label>Username<input name=\"username\" autocomplete=\"username\" required></label>"
        "<label>Password<input type=\"password\" name=\"password\" "
        "autocomplete=\"current-password\" required></label>"
        "<button type=\"submit\">Sign in</button></form></body></html>",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        },
    )


@router.post("/api/embed/auth/swagger", response_class=HTMLResponse)
async def complete_swagger_login(
    state: str = Form(min_length=1, max_length=512),
    username: str = Form(min_length=1, max_length=512),
    password: str = Form(min_length=1, max_length=2048),
    db: Session = Depends(get_db_session),
    service: ToolSessionService = Depends(get_tool_session_service),
) -> HTMLResponse:
    flow, row, data = _swagger_flow(db, state, service)
    now = utc_now()
    claimed = db.execute(
        update(ToolOAuthAuthorization)
        .where(
            ToolOAuthAuthorization.id == flow.id,
            ToolOAuthAuthorization.consumed_at.is_(None),
            ToolOAuthAuthorization.status == "pending",
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise _unavailable()
    db.commit()
    db.refresh(flow)
    try:
        config = service._config()
        login_data = {config.username_field: username, config.password_field: password}
        auth_payload = await service._login(config, login_data)
        auth = build_request_auth(config, auth_payload)
        expiry_candidates = [
            expiry
            for expiry in (
                service._auth_expiry(config, auth_payload),
                credential_expiry(auth),
            )
            if expiry is not None
        ]
        auth_expires_at = min(expiry_candidates) if expiry_candidates else None
        absolute_expires_at = min(
            [now + timedelta(hours=config.absolute_hours), *expiry_candidates]
        )
        credential = db.scalar(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == flow.api_source_id,
            )
        )
        if credential is None:
            raise _unavailable()
        row.status = "ready"
        row.encrypted_login_data = service._cipher.encrypt_json(login_data)
        row.encrypted_auth_data = service._cipher.encrypt_json(auth_payload)
        row.auth_expires_at = auth_expires_at
        owner_absolute_expires_at = datetime.fromisoformat(
            str(data["owner_absolute_expires_at"])
        )
        row.absolute_expires_at = min(
            absolute_expires_at, owner_absolute_expires_at
        )
        row.idle_expires_at = min(
            now + timedelta(minutes=config.idle_minutes), row.absolute_expires_at
        )
        credential.encrypted_credentials = service._cipher.encrypt_json(
            auth_to_json(auth)
        )
        credential.status = "ready"
        credential.expires_at = (
            min(auth_expires_at, row.absolute_expires_at)
            if auth_expires_at is not None
            else row.absolute_expires_at
        )
        flow.status = "ready"
        flow.encrypted_flow_data = service._cipher.encrypt_json({})
        grant = create_auth_grant(db, row.embed_session_id, row.id, flow.api_source_id)
        db.commit()
        return _popup_result(grant, str(data["parent_origin"]))
    except Exception:
        row.status = "failed"
        flow.status = "failed"
        flow.encrypted_flow_data = service._cipher.encrypt_json({})
        db.commit()
        raise


@router.post(
    "/api/embed/sessions/{session_id}/auth/exchange",
    response_model=EmbedAuthExchangeResponse,
)
def exchange_embed_auth(
    payload: EmbedAuthExchangeRequest,
    owner: EmbedSession = Depends(require_embed_auth_session),
    db: Session = Depends(get_db_session),
) -> EmbedAuthExchangeResponse:
    try:
        grant = consume_auth_grant(db, payload.grant, owner.id)
    except AuthGrantError as exc:
        raise _unavailable() from exc
    tool_session = db.get(ToolUserSession, grant.tool_session_id)
    if (
        tool_session is None
        or tool_session.embed_session_id != owner.id
        or tool_session.agent_id != owner.agent_id
        or tool_session.status != "ready"
        or tool_session.revoked_at is not None
    ):
        db.rollback()
        raise _unavailable()
    db.commit()
    return EmbedAuthExchangeResponse(
        status="ready",
        api_source_id=grant.api_source_id,
    )


@router.delete(
    "/api/embed/sessions/{session_id}/auth/{api_source_id}",
    status_code=204,
)
def revoke_embed_auth(
    api_source_id: int,
    owner: EmbedSession = Depends(require_embed_auth_session),
    db: Session = Depends(get_db_session),
    service: ToolSessionService = Depends(get_tool_session_service),
) -> None:
    rows = db.scalars(
        select(ToolUserSession)
        .join(
            ToolSessionCredential,
            ToolSessionCredential.tool_session_id == ToolUserSession.id,
        )
        .where(
            ToolUserSession.embed_session_id == owner.id,
            ToolUserSession.agent_id == owner.agent_id,
            ToolSessionCredential.api_source_id == api_source_id,
        )
    ).all()
    now = utc_now()
    for row in rows:
        row.status = "revoked"
        row.revoked_at = now
        row.encrypted_login_data = None
        row.encrypted_auth_data = None
        for credential in db.scalars(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id
            )
        ):
            credential.status = "revoked"
            credential.encrypted_credentials = service._cipher.encrypt_json({})
    db.commit()
