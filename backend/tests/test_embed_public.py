import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import (
    Agent,
    AgentEmbed,
    AgentSkill,
    AppSetting,
    LlmProvider,
    Skill,
)

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _seed_public_embed(
    client: httpx.AsyncClient,
    factory: sessionmaker[Session],
    *,
    origins: list[str] | None = None,
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
            encrypted_api_key=b"provider-secret",
            default_model="gpt-test",
            enabled=True,
        )
        skill = Skill(name="Support", system_prompt="Support visitors.", running=True)
        db.add_all([provider, skill])
        db.flush()
        agent = Agent(
            name="Site Assistant",
            enabled=True,
            system_prompt="Help site visitors.",
            provider_id=provider.id,
        )
        db.add(agent)
        db.flush()
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill.id, position=0))
        embed = AgentEmbed(
            agent_id=agent.id,
            name="Documentation",
            public_id="public-embed-id",
            allowed_origins=origins or ["https://docs.example"],
        )
        db.add(embed)
        db.commit()
        db.refresh(embed)
        return embed


@pytest.mark.asyncio
async def test_loader_contains_public_configuration_and_no_secrets(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_public_embed(client, db_session_factory)

    response = await client.get(f"/embed/{embed.public_id}.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "frame.allow = 'tools'" in response.text
    assert "frame.hidden = true" in response.text
    assert "button.setAttribute('aria-expanded', 'false')" in response.text
    assert "width:min(400px,calc(100vw - 32px))" in response.text
    assert "setOpen(frame.hidden)" in response.text
    assert "chat4openapi:ready" in response.text
    assert "initializeFrame" in response.text
    assert "https://chat.example" in response.text
    assert embed.public_id in response.text
    assert "provider-secret" not in response.text
    assert "client_secret" not in response.text
    assert "Authorization" not in response.text


@pytest.mark.asyncio
async def test_loader_uses_configured_left_position(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_public_embed(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(AgentEmbed, embed.id)
        assert row is not None
        row.position = "bottom_left"
        db.commit()

    response = await client.get(f"/embed/{embed.public_id}.js")

    assert response.status_code == 200
    assert '"position":"bottom_left"' in response.text
    assert "const side = config.position === 'bottom_left' ? 'left' : 'right'" in response.text


@pytest.mark.asyncio
async def test_iframe_uses_embed_specific_frame_ancestors(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_public_embed(
        client,
        db_session_factory,
        origins=["https://docs.example", "https://portal.example:8443"],
    )

    response = await client.get(f"/embed/{embed.public_id}")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == (
        "frame-ancestors https://docs.example https://portal.example:8443"
    )
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_disabled_embed_and_unknown_embed_share_unavailable_boundary(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed = await _seed_public_embed(client, db_session_factory)
    with db_session_factory() as db:
        row = db.get(AgentEmbed, embed.id)
        assert row is not None
        row.enabled = False
        db.commit()

    disabled = await client.get(f"/embed/{embed.public_id}.js")
    unknown = await client.get("/embed/unknown-id.js")

    assert disabled.status_code == unknown.status_code == 404
    assert disabled.json() == unknown.json() == {
        "error": {"code": "embed.unavailable", "params": {}}
    }
