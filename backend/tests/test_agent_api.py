from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import Agent, AgentSkill, LlmProvider, Skill

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def login(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def seed_default_agent(factory: sessionmaker[Session]) -> None:
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
            Agent(
                id=1,
                name="Default Agent",
                enabled=True,
                is_default=True,
                system_prompt="Original prompt",
                provider_id=provider.id,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        session.commit()


def seed_disabled_agent_without_skills(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        provider = session.query(LlmProvider).one()
        session.add(
            Agent(
                id=2,
                name="No Skills Agent",
                enabled=False,
                is_default=False,
                system_prompt="No skills yet",
                provider_id=provider.id,
                mode="react",
                max_iterations=8,
            )
        )
        session.commit()


def agent_payload(provider_id: int | None, *, name: str = "Operations Agent") -> dict[str, object]:
    return {
        "name": name,
        "description": "Coordinates operational work.",
        "enabled": False,
        "system_prompt": "Use configured Skills.",
        "provider_id": provider_id,
        "model": "gpt-special",
        "mode": "react",
        "max_iterations": 12,
    }


@pytest.mark.asyncio
async def test_default_agent_cannot_be_disabled(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)

    response = await client.post("/api/admin/agents/1/disable", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.default_cannot_disable"


@pytest.mark.asyncio
async def test_enable_requires_a_running_bound_skill(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)

    response = await client.post("/api/admin/agents/2/enable", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.no_running_skills"


@pytest.mark.asyncio
async def test_enable_requires_an_available_provider(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        agent = session.get(Agent, 2)
        agent.provider_id = None
        running = Skill(name="Providerless", system_prompt="Runnable", running=True)
        session.add(running)
        session.flush()
        session.add(AgentSkill(agent_id=agent.id, skill_id=running.id, position=0))
        session.commit()

    response = await client.post("/api/admin/agents/2/enable", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.provider_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "deleted"),
    [(False, False), (True, True)],
)
async def test_enable_rejects_disabled_or_deleted_provider(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
    enabled: bool,
    deleted: bool,
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        provider = LlmProvider(
            name="Unavailable",
            provider_type="openai",
            base_url="https://unavailable.test/v1",
            encrypted_api_key=b"secret",
            default_model="unavailable-model",
            enabled=enabled,
            deleted_at=datetime.now(UTC).replace(tzinfo=None) if deleted else None,
        )
        running = Skill(name="Unavailable provider", system_prompt="Run", running=True)
        session.add_all([provider, running])
        session.flush()
        agent = session.get(Agent, 2)
        agent.provider_id = provider.id
        session.add(AgentSkill(agent_id=agent.id, skill_id=running.id, position=0))
        session.commit()

    response = await client.post(
        "/api/admin/agents/2/enable", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.provider_unavailable"


@pytest.mark.asyncio
async def test_admin_can_create_list_get_update_and_soft_delete_agents(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    with db_session_factory() as session:
        provider_id = session.query(LlmProvider.id).scalar()

    created = await client.post(
        "/api/admin/agents",
        json=agent_payload(provider_id),
        headers={"X-CSRF-Token": csrf},
    )
    listed = await client.get("/api/admin/agents")
    fetched = await client.get(f"/api/admin/agents/{created.json()['id']}")
    updated_payload = agent_payload(None, name="Updated Agent")
    updated = await client.put(
        f"/api/admin/agents/{created.json()['id']}",
        json=updated_payload,
        headers={"X-CSRF-Token": csrf},
    )
    deleted = await client.delete(
        f"/api/admin/agents/{created.json()['id']}",
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert created.json()["description"] == "Coordinates operational work."
    assert created.json()["is_default"] is False
    assert created.json()["skill_ids"] == []
    assert [agent["id"] for agent in listed.json()] == [1, created.json()["id"]]
    assert fetched.json() == created.json()
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Agent"
    assert updated.json()["description"] == "Coordinates operational work."
    assert updated.json()["provider_id"] is None
    assert deleted.status_code == 204
    assert (await client.get(f"/api/admin/agents/{created.json()['id']}")).status_code == 404
    assert [agent["id"] for agent in (await client.get("/api/admin/agents")).json()] == [1]
    with db_session_factory() as session:
        row = session.get(Agent, created.json()["id"])
        assert row is not None
        assert row.enabled is False
        assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_skill_replacement_preserves_order_and_stopped_bindings(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        stopped = Skill(name="Stopped", system_prompt="Stopped", running=False)
        running = Skill(name="Running", system_prompt="Running", running=True)
        session.add_all([stopped, running])
        session.commit()
        stopped_id, running_id = stopped.id, running.id

    replaced = await client.put(
        "/api/admin/agents/2/skills",
        json={"skill_ids": [running_id, stopped_id]},
        headers={"X-CSRF-Token": csrf},
    )
    enabled = await client.post("/api/admin/agents/2/enable", headers={"X-CSRF-Token": csrf})

    assert replaced.status_code == 200
    assert replaced.json()["skill_ids"] == [running_id, stopped_id]
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["skill_ids"] == [running_id, stopped_id]
    with db_session_factory() as session:
        bindings = (
            session.query(AgentSkill).filter_by(agent_id=2).order_by(AgentSkill.position).all()
        )
        assert [(binding.skill_id, binding.position) for binding in bindings] == [
            (running_id, 0),
            (stopped_id, 1),
        ]


@pytest.mark.asyncio
async def test_invalid_skill_replacement_keeps_existing_bindings(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        skill = Skill(name="Bound", system_prompt="Bound", running=False)
        session.add(skill)
        session.flush()
        session.add(AgentSkill(agent_id=2, skill_id=skill.id, position=0))
        session.commit()
        skill_id = skill.id

    response = await client.put(
        "/api/admin/agents/2/skills",
        json={"skill_ids": [skill_id, skill_id]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.skill_duplicate"
    assert (await client.get("/api/admin/agents/2")).json()["skill_ids"] == [skill_id]


@pytest.mark.asyncio
async def test_missing_skill_cannot_be_bound(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        existing = Skill(name="Existing", system_prompt="Existing", running=False)
        session.add(existing)
        session.flush()
        session.add(AgentSkill(agent_id=2, skill_id=existing.id, position=0))
        session.commit()
        existing_id = existing.id

    response = await client.put(
        "/api/admin/agents/2/skills",
        json={"skill_ids": [999]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "agents.skill_unavailable",
            "params": {"skill_id": 999},
        }
    }
    assert (await client.get("/api/admin/agents/2")).json()["skill_ids"] == [existing_id]


@pytest.mark.asyncio
async def test_setting_default_switches_once_and_enables_the_target(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)
    with db_session_factory() as session:
        skill = Skill(name="Runnable", system_prompt="Runnable", running=True)
        session.add(skill)
        session.flush()
        session.add(AgentSkill(agent_id=2, skill_id=skill.id, position=0))
        session.commit()

    switched = await client.post("/api/admin/agents/2/set-default", headers={"X-CSRF-Token": csrf})
    old_disabled = await client.post("/api/admin/agents/1/disable", headers={"X-CSRF-Token": csrf})
    new_deleted = await client.delete("/api/admin/agents/2", headers={"X-CSRF-Token": csrf})

    assert switched.status_code == 200
    assert switched.json()["enabled"] is True
    assert switched.json()["is_default"] is True
    assert old_disabled.status_code == 200
    assert new_deleted.status_code == 409
    assert new_deleted.json()["error"]["code"] == "agents.default_cannot_delete"
    agents = (await client.get("/api/admin/agents")).json()
    assert [(agent["id"], agent["enabled"], agent["is_default"]) for agent in agents] == [
        (1, False, False),
        (2, True, True),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/admin/agents", "/api/admin/agents/1"])
async def test_agent_reads_require_admin_login(
    client: httpx.AsyncClient,
    path: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/admin/agents", agent_payload(None)),
        ("PUT", "/api/admin/agents/2", agent_payload(None)),
        ("PUT", "/api/admin/agents/2/skills", {"skill_ids": []}),
        ("POST", "/api/admin/agents/2/enable", None),
        ("POST", "/api/admin/agents/2/disable", None),
        ("POST", "/api/admin/agents/2/set-default", None),
        ("DELETE", "/api/admin/agents/2", None),
    ],
)
async def test_agent_writes_require_valid_csrf(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    await login(client)
    seed_default_agent(db_session_factory)
    seed_disabled_agent_without_skills(db_session_factory)

    response = await client.request(method, path, json=payload)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_invalid"
