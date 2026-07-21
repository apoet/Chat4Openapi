from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import Agent, AgentApiKey
from chat4openapi.schemas.agents import (
    AgentApiKeyCreate,
    AgentApiKeyCreated,
    AgentApiKeyResponse,
    AgentApiKeyUpdate,
)
from chat4openapi.security.agent_keys import create_agent_key

router = APIRouter(prefix="/api/admin/agents", tags=["agent-keys"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _agent(context: AdminContext, agent_id: int) -> Agent:
    agent = context.db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise ApiError(404, "agents.not_found")
    return agent


def _key(context: AdminContext, agent_id: int, key_id: int) -> AgentApiKey:
    api_key = context.db.scalar(
        select(AgentApiKey).where(
            AgentApiKey.id == key_id,
            AgentApiKey.agent_id == agent_id,
            AgentApiKey.deleted_at.is_(None),
        )
    )
    if api_key is None:
        raise ApiError(404, "agent_keys.not_found")
    return api_key


@router.get("/{agent_id}/keys", response_model=list[AgentApiKeyResponse])
def list_agent_keys(
    agent_id: int, context: AdminContext = Depends(require_admin)
) -> list[AgentApiKey]:
    _agent(context, agent_id)
    return list(
        context.db.scalars(
            select(AgentApiKey)
            .where(
                AgentApiKey.agent_id == agent_id,
                AgentApiKey.deleted_at.is_(None),
            )
            .order_by(AgentApiKey.id)
        )
    )


@router.post("/{agent_id}/keys", response_model=AgentApiKeyCreated, status_code=201)
def add_agent_key(
    agent_id: int,
    payload: AgentApiKeyCreate,
    context: AdminContext = Depends(require_csrf),
) -> AgentApiKeyCreated:
    with serialized_write(context.db):
        _agent(context, agent_id)
        api_key, secret = create_agent_key(
            agent_id=agent_id,
            label=payload.label,
            expires_at=_naive_utc(payload.expires_at),
        )
        context.db.add(api_key)
        context.db.flush()
    response = AgentApiKeyResponse.model_validate(api_key)
    return AgentApiKeyCreated(**response.model_dump(), secret=secret)


@router.patch("/{agent_id}/keys/{key_id}", response_model=AgentApiKeyResponse)
def update_agent_key(
    agent_id: int,
    key_id: int,
    payload: AgentApiKeyUpdate,
    context: AdminContext = Depends(require_csrf),
) -> AgentApiKey:
    with serialized_write(context.db):
        _agent(context, agent_id)
        api_key = _key(context, agent_id, key_id)
        if "label" in payload.model_fields_set:
            api_key.label = payload.label
        if "expires_at" in payload.model_fields_set:
            api_key.expires_at = _naive_utc(payload.expires_at)
    return api_key


@router.post("/{agent_id}/keys/{key_id}/revoke", response_model=AgentApiKeyResponse)
def revoke_agent_key(
    agent_id: int,
    key_id: int,
    context: AdminContext = Depends(require_csrf),
) -> AgentApiKey:
    with serialized_write(context.db):
        _agent(context, agent_id)
        api_key = _key(context, agent_id, key_id)
        api_key.enabled = False
        if api_key.revoked_at is None:
            api_key.revoked_at = _now()
    return api_key


@router.delete("/{agent_id}/keys/{key_id}", status_code=204)
def delete_agent_key(
    agent_id: int,
    key_id: int,
    context: AdminContext = Depends(require_csrf),
) -> None:
    with serialized_write(context.db):
        _agent(context, agent_id)
        api_key = _key(context, agent_id, key_id)
        api_key.enabled = False
        if api_key.revoked_at is None:
            api_key.revoked_at = _now()
        api_key.deleted_at = _now()
