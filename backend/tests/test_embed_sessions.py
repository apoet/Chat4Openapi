from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import (
    Agent,
    AgentEmbed,
    AgentSkill,
    AppSetting,
    EmbedSession,
    LlmProvider,
    Skill,
)
from chat4openapi.security.session_tokens import hash_token

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _seed_embed(
    client: httpx.AsyncClient,
    factory: sessionmaker[Session],
    *,
    origins: list[str],
) -> AgentEmbed:
    await client.post("/api/setup", json=ADMIN)
    with factory() as db:
        settings = db.get(AppSetting, 1)
        assert settings is not None
        settings.base_url = "https://chat.example"
        provider = LlmProvider(
            name="Embed LLM",
            provider_type="openai",
            base_url="https://llm.example/v1",
            encrypted_api_key=b"secret",
            default_model="gpt-test",
            enabled=True,
        )
        skill = Skill(name="Support", system_prompt="Support.", running=True)
        db.add_all([provider, skill])
        db.flush()
        agent = Agent(
            name="Site Assistant",
            enabled=True,
            system_prompt="Help.",
            provider_id=provider.id,
        )
        db.add(agent)
        db.flush()
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill.id, position=0))
        embed = AgentEmbed(
            agent_id=agent.id,
            name="Site",
            public_id="session-embed-id",
            allowed_origins=origins,
        )
        db.add(embed)
        db.commit()
        db.refresh(embed)
        return embed


@pytest.mark.asyncio
async def test_session_token_is_returned_once_and_only_hash_is_stored(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_embed(
        client, db_session_factory, origins=["https://docs.example"]
    )

    response = await client.post(
        f"/api/embed/{embed.public_id}/sessions",
        json={"parent_origin": "https://Docs.Example/"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["agent"] == {"id": embed.agent_id, "name": "Site Assistant"}
    assert payload["parent_origin"] == "https://docs.example"
    assert payload["token"]
    with db_session_factory() as db:
        stored = db.scalar(select(EmbedSession))
        assert stored is not None
        assert stored.token_hash == hash_token(payload["token"])
        assert stored.token_hash != payload["token"]
        assert stored.public_subject_id == payload["session_id"]


@pytest.mark.asyncio
async def test_session_rejects_disallowed_origin_without_enumerating_embed(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_embed(
        client, db_session_factory, origins=["https://docs.example"]
    )

    denied = await client.post(
        f"/api/embed/{embed.public_id}/sessions",
        json={"parent_origin": "https://evil.example"},
    )
    missing = await client.post(
        "/api/embed/missing/sessions",
        json={"parent_origin": "https://evil.example"},
    )

    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


@pytest.mark.asyncio
async def test_empty_origin_list_allows_secure_parent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_embed(client, db_session_factory, origins=[])

    response = await client.post(
        f"/api/embed/{embed.public_id}/sessions",
        json={"parent_origin": "https://any.example"},
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_session_can_be_revoked_and_expired_session_is_rejected(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_embed(client, db_session_factory, origins=[])
    created = await client.post(
        f"/api/embed/{embed.public_id}/sessions",
        json={"parent_origin": "https://any.example"},
    )
    payload = created.json()
    headers = {"Authorization": f"Bearer {payload['token']}"}

    revoked = await client.delete(
        f"/api/embed/sessions/{payload['session_id']}", headers=headers
    )
    repeated = await client.delete(
        f"/api/embed/sessions/{payload['session_id']}", headers=headers
    )

    assert revoked.status_code == 204
    assert repeated.status_code == 404

    another = await client.post(
        f"/api/embed/{embed.public_id}/sessions",
        json={"parent_origin": "https://any.example"},
    )
    with db_session_factory() as db:
        session = db.scalar(
            select(EmbedSession).where(
                EmbedSession.public_subject_id == another.json()["session_id"]
            )
        )
        assert session is not None
        session.absolute_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()
    expired = await client.delete(
        f"/api/embed/sessions/{another.json()['session_id']}",
        headers={"Authorization": f"Bearer {another.json()['token']}"},
    )
    assert expired.status_code == 404
