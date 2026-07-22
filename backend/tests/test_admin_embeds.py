import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import Agent, AgentEmbed

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _login(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def _seed_agent(factory: sessionmaker[Session]) -> int:
    with factory() as db:
        agent = Agent(
            name="Site Assistant",
            enabled=True,
            is_default=False,
            system_prompt="Help site visitors.",
        )
        db.add(agent)
        db.commit()
        return agent.id


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "name": "Documentation",
        "enabled": True,
        "allowed_origins": ["https://Docs.Example/", "https://docs.example"],
        "position": "bottom_right",
        **overrides,
    }


@pytest.mark.asyncio
async def test_admin_can_create_list_update_and_soft_delete_embed(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await _login(client)
    agent_id = _seed_agent(db_session_factory)
    await client.put(
        "/api/admin/settings",
        json={"base_url": "https://chat.example/app/"},
        headers={"X-CSRF-Token": csrf},
    )

    created = await client.post(
        f"/api/admin/agents/{agent_id}/embeds",
        json=_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    embed_id = created.json()["id"]
    listed = await client.get(f"/api/admin/agents/{agent_id}/embeds")
    updated = await client.put(
        f"/api/admin/agents/{agent_id}/embeds/{embed_id}",
        json=_payload(name="Support", position="bottom_left", allowed_origins=[]),
        headers={"X-CSRF-Token": csrf},
    )
    script = await client.get(
        f"/api/admin/agents/{agent_id}/embeds/{embed_id}/script"
    )
    deleted = await client.delete(
        f"/api/admin/agents/{agent_id}/embeds/{embed_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert len(created.json()["public_id"]) == 43
    assert created.json()["allowed_origins"] == ["https://docs.example"]
    assert created.json()["script"] == (
        f'<script src="https://chat.example/app/embed/{created.json()["public_id"]}.js" async></script>'
    )
    assert [item["id"] for item in listed.json()] == [embed_id]
    assert updated.json()["name"] == "Support"
    assert updated.json()["position"] == "bottom_left"
    assert updated.json()["allowed_origins"] == []
    assert script.json()["script"] == updated.json()["script"]
    assert deleted.status_code == 204
    assert (await client.get(f"/api/admin/agents/{agent_id}/embeds")).json() == []
    with db_session_factory() as db:
        row = db.get(AgentEmbed, embed_id)
        assert row is not None
        assert row.enabled is False
        assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_script_generation_requires_base_url(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await _login(client)
    agent_id = _seed_agent(db_session_factory)
    created = await client.post(
        f"/api/admin/agents/{agent_id}/embeds",
        json=_payload(),
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert created.json()["script"] is None
    response = await client.get(
        f"/api/admin/agents/{agent_id}/embeds/{created.json()['id']}/script"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "settings.base_url_required"


@pytest.mark.asyncio
async def test_embed_rejects_invalid_origin_and_missing_agent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await _login(client)
    agent_id = _seed_agent(db_session_factory)

    invalid = await client.post(
        f"/api/admin/agents/{agent_id}/embeds",
        json=_payload(allowed_origins=["http://docs.example"]),
        headers={"X-CSRF-Token": csrf},
    )
    missing = await client.post(
        "/api/admin/agents/999/embeds",
        json=_payload(allowed_origins=[]),
        headers={"X-CSRF-Token": csrf},
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["params"]["fields"] == ["body.allowed_origins.0"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "agents.not_found"


@pytest.mark.asyncio
async def test_embed_writes_require_csrf_and_reads_require_login(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    assert (await client.get("/api/admin/agents/1/embeds")).status_code == 401
    await _login(client)
    agent_id = _seed_agent(db_session_factory)
    response = await client.post(
        f"/api/admin/agents/{agent_id}/embeds",
        json=_payload(allowed_origins=[]),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_invalid"
