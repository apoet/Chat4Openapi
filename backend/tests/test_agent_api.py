from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chatapi.models import AgentConfig, LlmProvider

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def login(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def seed_agent(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        provider = LlmProvider(
            name="Primary",
            provider_type="openai",
            base_url="https://llm.test/v1",
            encrypted_api_key=b"secret",
            default_model="gpt-test",
            enabled=True,
        )
        session.add(provider)
        session.flush()
        session.add(
            AgentConfig(
                id=1,
                name="ChatAPI Agent",
                enabled=True,
                system_prompt="Original prompt",
                provider_id=provider.id,
                model=None,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        session.commit()
        return provider.id


def seed_providerless_agent(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            AgentConfig(
                id=1,
                name="ChatAPI Agent",
                enabled=True,
                system_prompt="Original prompt",
                provider_id=None,
                model=None,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        session.commit()


def add_provider(
    factory: sessionmaker[Session], *, enabled: bool, deleted: bool = False
) -> int:
    with factory() as session:
        provider = LlmProvider(
            name=f"Provider {enabled} {deleted}",
            provider_type="openai",
            base_url="https://llm.test/v1",
            encrypted_api_key=b"secret",
            default_model="gpt-test",
            enabled=enabled,
            deleted_at=datetime.now(UTC).replace(tzinfo=None) if deleted else None,
        )
        session.add(provider)
        session.commit()
        return provider.id


def agent_payload(provider_id: int) -> dict[str, object]:
    return {
        "name": "Operations Agent",
        "enabled": False,
        "system_prompt": "Use the configured skills.",
        "provider_id": provider_id,
        "model": "gpt-special",
        "mode": "react",
        "max_iterations": 12,
    }


@pytest.mark.asyncio
async def test_authenticated_admin_can_read_the_singleton_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    await login(client)
    provider_id = seed_agent(db_session_factory)

    response = await client.get("/api/admin/agent")

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "name": "ChatAPI Agent",
        "enabled": True,
        "system_prompt": "Original prompt",
        "provider_id": provider_id,
        "model": None,
        "mode": "human_in_loop",
        "max_iterations": 8,
    }


@pytest.mark.asyncio
async def test_authenticated_admin_can_read_providerless_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    await login(client)
    seed_providerless_agent(db_session_factory)

    response = await client.get("/api/admin/agent")

    assert response.status_code == 200
    assert response.json()["provider_id"] is None


@pytest.mark.asyncio
async def test_authenticated_admin_can_update_the_singleton_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    provider_id = seed_agent(db_session_factory)
    payload = agent_payload(provider_id)

    response = await client.put(
        "/api/admin/agent", json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 200
    assert response.json() == {"id": 1, **payload}
    assert (await client.get("/api/admin/agent")).json() == {"id": 1, **payload}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("mode", "invalid"), ("max_iterations", 0)],
)
async def test_agent_update_rejects_invalid_mode_and_iteration_bounds(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
    field: str,
    value: object,
) -> None:
    csrf = await login(client)
    provider_id = seed_agent(db_session_factory)
    payload = agent_payload(provider_id)
    payload[field] = value

    response = await client.put(
        "/api/admin/agent", json=payload, headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "deleted"),
    [(False, False), (True, True)],
)
async def test_agent_update_rejects_unavailable_provider(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
    enabled: bool,
    deleted: bool,
) -> None:
    csrf = await login(client)
    seed_agent(db_session_factory)
    provider_id = add_provider(db_session_factory, enabled=enabled, deleted=deleted)

    response = await client.put(
        "/api/admin/agent",
        json=agent_payload(provider_id),
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent.provider_unavailable"


@pytest.mark.asyncio
async def test_authenticated_admin_can_reset_the_singleton_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    provider_id = seed_agent(db_session_factory)
    updated = await client.put(
        "/api/admin/agent",
        json=agent_payload(provider_id),
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200

    response = await client.post(
        "/api/admin/agent/reset", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "name": "ChatAPI Agent",
        "enabled": True,
        "system_prompt": (
            "You are ChatAPI Agent, the built-in assistant. Use the available Skills "
            "and Tools to help the user, and return clear Markdown responses."
        ),
        "provider_id": provider_id,
        "model": None,
        "mode": "human_in_loop",
        "max_iterations": 8,
    }
