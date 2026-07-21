import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import Agent, AgentApiKey
from chat4openapi.schemas.agents import AgentApiKeyUpdate


ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def seed_agent(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            Agent(
                id=1,
                name="Keyed Agent",
                enabled=True,
                is_default=True,
                system_prompt="Use only bound Skills.",
                mode="react",
                max_iterations=8,
            )
        )
        session.commit()


def test_key_update_rejects_an_explicit_null_label() -> None:
    with pytest.raises(ValidationError):
        AgentApiKeyUpdate.model_validate({"label": None})


@pytest.mark.asyncio
async def test_plaintext_agent_key_is_returned_once_and_only_hash_is_persisted(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_agent(db_session_factory)

    created = await client.post(
        "/api/admin/agents/1/keys",
        json={"label": "CI"},
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    secret = created.json()["secret"]
    assert secret.startswith("c4o_")
    assert len(secret) >= 40
    assert created.json()["key_prefix"] == secret[:12]
    listed = await client.get("/api/admin/agents/1/keys")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "secret" not in listed.json()[0]
    assert "key_hash" not in listed.json()[0]
    assert secret not in listed.text
    with db_session_factory() as session:
        stored = session.scalar(select(AgentApiKey))
        assert stored is not None
        assert stored.key_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in repr(stored.__dict__)


@pytest.mark.asyncio
async def test_agent_key_metadata_can_be_updated_revoked_and_soft_deleted(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_agent(db_session_factory)
    created = await client.post(
        "/api/admin/agents/1/keys",
        json={"label": "Initial"},
        headers={"X-CSRF-Token": csrf},
    )
    key_id = created.json()["id"]
    expiry = datetime.now(UTC) + timedelta(days=7)

    updated = await client.patch(
        f"/api/admin/agents/1/keys/{key_id}",
        json={"label": "Deployment", "expires_at": expiry.isoformat()},
        headers={"X-CSRF-Token": csrf},
    )
    revoked = await client.post(
        f"/api/admin/agents/1/keys/{key_id}/revoke",
        headers={"X-CSRF-Token": csrf},
    )
    deleted = await client.delete(
        f"/api/admin/agents/1/keys/{key_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert updated.status_code == 200
    assert updated.json()["label"] == "Deployment"
    assert updated.json()["expires_at"].startswith(expiry.date().isoformat())
    assert revoked.status_code == 200
    assert revoked.json()["enabled"] is False
    assert revoked.json()["revoked_at"] is not None
    assert deleted.status_code == 204
    assert (await client.get("/api/admin/agents/1/keys")).json() == []
    with db_session_factory() as session:
        stored = session.get(AgentApiKey, key_id)
        assert stored is not None
        assert stored.deleted_at is not None
        assert stored.enabled is False


@pytest.mark.asyncio
async def test_agent_key_routes_enforce_admin_csrf_and_agent_isolation(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_agent(db_session_factory)
    with db_session_factory() as session:
        session.add(
            Agent(
                id=2,
                name="Other Agent",
                enabled=False,
                is_default=False,
                system_prompt="Other",
                mode="react",
                max_iterations=8,
            )
        )
        session.commit()

    missing_csrf = await client.post(
        "/api/admin/agents/1/keys", json={"label": "No CSRF"}
    )
    created = await client.post(
        "/api/admin/agents/1/keys",
        json={"label": "Scoped"},
        headers={"X-CSRF-Token": csrf},
    )
    key_id = created.json()["id"]
    cross_agent = await client.post(
        f"/api/admin/agents/2/keys/{key_id}/revoke",
        headers={"X-CSRF-Token": csrf},
    )

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "auth.csrf_invalid"
    assert cross_agent.status_code == 404
    assert cross_agent.json()["error"]["code"] == "agent_keys.not_found"


@pytest.mark.asyncio
async def test_key_create_rejects_missing_or_deleted_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_agent(db_session_factory)
    with db_session_factory() as session:
        agent = session.get(Agent, 1)
        assert agent is not None
        agent.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

    deleted = await client.post(
        "/api/admin/agents/1/keys",
        json={"label": "Deleted"},
        headers={"X-CSRF-Token": csrf},
    )
    missing = await client.post(
        "/api/admin/agents/999/keys",
        json={"label": "Missing"},
        headers={"X-CSRF-Token": csrf},
    )

    assert deleted.status_code == 404
    assert missing.status_code == 404
    assert deleted.json()["error"]["code"] == "agents.not_found"
    assert missing.json()["error"]["code"] == "agents.not_found"
