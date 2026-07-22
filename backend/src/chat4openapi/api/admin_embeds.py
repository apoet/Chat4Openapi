import html
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import Agent, AgentEmbed, AppSetting
from chat4openapi.schemas.embeds import (
    AgentEmbedResponse,
    AgentEmbedScriptResponse,
    AgentEmbedWrite,
)

router = APIRouter(prefix="/api/admin/agents", tags=["admin-embeds"])


def _agent(context: AdminContext, agent_id: int) -> Agent:
    agent = context.db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise ApiError(404, "agents.not_found")
    return agent


def _embed(context: AdminContext, agent_id: int, embed_id: int) -> AgentEmbed:
    _agent(context, agent_id)
    embed = context.db.get(AgentEmbed, embed_id)
    if embed is None or embed.agent_id != agent_id or embed.deleted_at is not None:
        raise ApiError(404, "embeds.not_found")
    return embed


def _generated_script(base_url: str, public_id: str) -> str:
    src = html.escape(f"{base_url}/embed/{public_id}.js", quote=True)
    return f'<script src="{src}" async></script>'


def _script(context: AdminContext, embed: AgentEmbed, *, required: bool) -> str | None:
    settings = context.db.get(AppSetting, 1)
    if settings is None or settings.base_url is None:
        if required:
            raise ApiError(409, "settings.base_url_required")
        return None
    return _generated_script(settings.base_url, embed.public_id)


def _response(context: AdminContext, embed: AgentEmbed) -> AgentEmbedResponse:
    response = AgentEmbedResponse.model_validate(embed)
    return response.model_copy(update={"script": _script(context, embed, required=False)})


@router.get("/{agent_id}/embeds", response_model=list[AgentEmbedResponse])
def list_agent_embeds(
    agent_id: int,
    context: AdminContext = Depends(require_admin),
) -> list[AgentEmbedResponse]:
    _agent(context, agent_id)
    embeds = context.db.scalars(
        select(AgentEmbed)
        .where(AgentEmbed.agent_id == agent_id, AgentEmbed.deleted_at.is_(None))
        .order_by(AgentEmbed.id)
    ).all()
    return [_response(context, embed) for embed in embeds]


@router.post("/{agent_id}/embeds", response_model=AgentEmbedResponse, status_code=201)
def create_agent_embed(
    agent_id: int,
    payload: AgentEmbedWrite,
    context: AdminContext = Depends(require_csrf),
) -> AgentEmbedResponse:
    with serialized_write(context.db):
        _agent(context, agent_id)
        embed = AgentEmbed(
            agent_id=agent_id,
            public_id=secrets.token_urlsafe(32),
            **payload.model_dump(),
        )
        context.db.add(embed)
        context.db.flush()
    return _response(context, embed)


@router.put("/{agent_id}/embeds/{embed_id}", response_model=AgentEmbedResponse)
def update_agent_embed(
    agent_id: int,
    embed_id: int,
    payload: AgentEmbedWrite,
    context: AdminContext = Depends(require_csrf),
) -> AgentEmbedResponse:
    with serialized_write(context.db):
        embed = _embed(context, agent_id, embed_id)
        for field, value in payload.model_dump().items():
            setattr(embed, field, value)
    return _response(context, embed)


@router.delete("/{agent_id}/embeds/{embed_id}", status_code=204)
def delete_agent_embed(
    agent_id: int,
    embed_id: int,
    context: AdminContext = Depends(require_csrf),
) -> None:
    with serialized_write(context.db):
        embed = _embed(context, agent_id, embed_id)
        embed.enabled = False
        embed.deleted_at = datetime.now(UTC).replace(tzinfo=None)


@router.get(
    "/{agent_id}/embeds/{embed_id}/script",
    response_model=AgentEmbedScriptResponse,
)
def get_agent_embed_script(
    agent_id: int,
    embed_id: int,
    context: AdminContext = Depends(require_admin),
) -> AgentEmbedScriptResponse:
    embed = _embed(context, agent_id, embed_id)
    script = _script(context, embed, required=True)
    assert script is not None
    return AgentEmbedScriptResponse(script=script)
