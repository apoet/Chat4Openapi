import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.db.session import get_db_session
from chat4openapi.embed.sessions import (
    EmbedUnavailableError,
    authenticate_embed_session,
    available_embed,
    issue_embed_session,
)
from chat4openapi.embed.urls import frame_ancestors
from chat4openapi.models import AppSetting
from chat4openapi.schemas.embeds import (
    EmbedAgentSummary,
    EmbedSessionCreate,
    EmbedSessionCreated,
)

router = APIRouter(tags=["embed"])


def _unavailable() -> ApiError:
    return ApiError(404, "embed.unavailable")


def _public_embed(db: Session, public_id: str):
    try:
        return available_embed(db, public_id)
    except EmbedUnavailableError as exc:
        raise _unavailable() from exc


def _base_url(db: Session) -> str:
    settings = db.get(AppSetting, 1)
    if settings is None or settings.base_url is None:
        raise _unavailable()
    return settings.base_url


def _loader_source(base_url: str, public_id: str, position: str) -> str:
    config = json.dumps(
        {
            "baseUrl": base_url,
            "publicId": public_id,
            "position": position,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Recompute the origin in-browser because Base URL may contain a deployment path.
    return f"""(() => {{
  const config = {config};
  config.chatOrigin = new URL(config.baseUrl).origin;
  const side = config.position === 'bottom_left' ? 'left' : 'right';
  if (document.querySelector('[data-chat4openapi="' + config.publicId + '"]')) return;
  const host = document.createElement('div');
  host.dataset.chat4openapi = config.publicId;
  const root = host.attachShadow({{ mode: 'open' }});
  const style = document.createElement('style');
  style.textContent = `:host{{all:initial}}button{{position:fixed;bottom:24px;width:56px;height:56px;border:0;border-radius:50%;background:#fff;box-shadow:0 8px 28px #0003;cursor:pointer;z-index:2147483646;padding:8px}}img{{width:100%;height:100%;object-fit:contain}}iframe{{position:fixed;bottom:92px;width:min(380px,calc(100vw - 32px));height:min(620px,calc(100vh - 120px));border:0;border-radius:16px;box-shadow:0 12px 40px #0004;z-index:2147483647;background:#fff}}[hidden]{{display:none!important}}@media(max-width:640px){{iframe{{inset:12px;width:calc(100vw - 24px);height:calc(100vh - 24px)}}}}`;
  const button = document.createElement('button');
  button.type = 'button'; button.setAttribute('aria-label', 'Open Chat4Openapi');
  button.style[side] = '24px';
  const image = document.createElement('img'); image.alt = ''; image.src = config.baseUrl + '/embed/assets/logo.png';
  button.append(image);
  const frame = document.createElement('iframe');
  frame.title = 'Chat4Openapi'; frame.allow = 'tools'; frame.hidden = true;
  frame.style[side] = '24px';
  frame.src = config.baseUrl + '/embed/' + encodeURIComponent(config.publicId);
  button.addEventListener('click', () => {{ frame.hidden = !frame.hidden; }});
  frame.addEventListener('load', () => frame.contentWindow?.postMessage(
    {{ type: 'chat4openapi:init', parentOrigin: location.origin }}, config.chatOrigin));
  window.addEventListener('message', (event) => {{
    if (event.origin !== config.chatOrigin || event.source !== frame.contentWindow) return;
    if (event.data?.type === 'chat4openapi:close') frame.hidden = true;
  }});
  root.append(style, button, frame); document.body.append(host);
}})();"""


@router.get("/embed/assets/logo.png", include_in_schema=False)
def embed_logo() -> FileResponse:
    logo = Path(__file__).resolve().parents[4] / "logo.png"
    return FileResponse(logo, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/embed/{public_id}.js", include_in_schema=False)
def embed_loader(public_id: str, db: Session = Depends(get_db_session)) -> Response:
    embed, _agent = _public_embed(db, public_id)
    source = _loader_source(_base_url(db), public_id, embed.position)
    return Response(
        source,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/embed/{public_id}", include_in_schema=False)
def embed_application(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
) -> Response:
    embed, _agent = _public_embed(db, public_id)
    headers = {
        "Content-Security-Policy": frame_ancestors(embed.allowed_origins),
        "Cache-Control": "no-store",
    }
    index_file = getattr(request.app.state, "frontend_index", None)
    if isinstance(index_file, Path) and index_file.is_file():
        return FileResponse(index_file, media_type="text/html", headers=headers)
    return HTMLResponse(
        "<!doctype html><html><body><div id=\"app\"></div></body></html>",
        headers=headers,
    )


@router.post(
    "/api/embed/{public_id}/sessions",
    response_model=EmbedSessionCreated,
    status_code=201,
)
def create_embed_session(
    public_id: str,
    payload: EmbedSessionCreate,
    db: Session = Depends(get_db_session),
) -> EmbedSessionCreated:
    embed, agent = _public_embed(db, public_id)
    if embed.allowed_origins and payload.parent_origin not in embed.allowed_origins:
        raise _unavailable()
    session, token = issue_embed_session(db, embed, payload.parent_origin)
    db.commit()
    return EmbedSessionCreated(
        session_id=session.public_subject_id,
        token=token,
        parent_origin=session.parent_origin,
        agent=EmbedAgentSummary(id=agent.id, name=agent.name),
    )


def _bearer(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise _unavailable()
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unavailable()
    return token


@router.delete("/api/embed/sessions/{session_id}", status_code=204)
def revoke_embed_session(
    session_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> None:
    try:
        session = authenticate_embed_session(
            db, _bearer(authorization), session_id=session_id
        )
    except EmbedUnavailableError as exc:
        raise _unavailable() from exc
    session.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
