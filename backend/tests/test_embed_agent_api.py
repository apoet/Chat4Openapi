import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.agui.events import run_finished, run_started
from chat4openapi.api.embed_agent import get_agui_runtime
from chat4openapi.embed.sessions import issue_embed_session
from chat4openapi.models import Agent, AgentEmbed, AgentSkill, LlmProvider, Skill


class FakeAguiRuntime:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, payload, owner):
        self.calls.append((payload, owner))
        yield run_started(payload.thread_id, payload.run_id)
        yield run_finished(payload.thread_id, payload.run_id)


def _run_input(content: str = "hello") -> dict:
    return {
        "threadId": "initial-thread",
        "runId": "run-1",
        "state": {},
        "messages": [{"id": "user-1", "role": "user", "content": content}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def _seed_embed_session(
    factory: sessionmaker[Session], public_id: str
) -> tuple[AgentEmbed, str]:
    with factory() as db:
        provider = LlmProvider(
            name=f"Provider {public_id}",
            provider_type="openai",
            base_url="https://llm.example/v1",
            encrypted_api_key=b"unused",
            default_model="test-model",
            enabled=True,
        )
        skill = Skill(name=f"Skill {public_id}", system_prompt="Help.", running=True)
        db.add_all([provider, skill])
        db.flush()
        agent = Agent(
            name=f"Agent {public_id}",
            system_prompt="Help visitors.",
            provider_id=provider.id,
            enabled=True,
        )
        db.add(agent)
        db.flush()
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill.id, position=0))
        embed = AgentEmbed(
            agent_id=agent.id,
            name=f"Embed {public_id}",
            public_id=public_id,
            allowed_origins=["https://host.example"],
            enabled=True,
        )
        db.add(embed)
        db.flush()
        _owner, token = issue_embed_session(db, embed, "https://host.example")
        db.commit()
        db.refresh(embed)
        return embed, token


@pytest.mark.asyncio
async def test_agui_endpoint_streams_standard_lifecycle(
    client: httpx.AsyncClient,
    app,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed, token = _seed_embed_session(db_session_factory, "public-stream")
    runtime = FakeAguiRuntime()
    app.dependency_overrides[get_agui_runtime] = lambda: runtime

    response = await client.post(
        f"/api/embed/{embed.public_id}/agent",
        headers={"Authorization": f"Bearer {token}"},
        json=_run_input(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text
    assert len(runtime.calls) == 1
    assert runtime.calls[0][1].embed_id == embed.id


@pytest.mark.asyncio
async def test_agui_endpoint_hides_missing_and_owner_mismatch(
    client: httpx.AsyncClient,
    app,
    db_session_factory: sessionmaker[Session],
) -> None:
    embed, _token = _seed_embed_session(db_session_factory, "public-owner")
    _other_embed, other_token = _seed_embed_session(db_session_factory, "public-other")
    runtime = FakeAguiRuntime()
    app.dependency_overrides[get_agui_runtime] = lambda: runtime

    missing = await client.post(
        f"/api/embed/{embed.public_id}/agent", json=_run_input()
    )
    mismatch = await client.post(
        f"/api/embed/{embed.public_id}/agent",
        headers={"Authorization": f"Bearer {other_token}"},
        json=_run_input(),
    )

    assert missing.status_code == mismatch.status_code == 404
    assert missing.json() == mismatch.json() == {
        "error": {"code": "embed.unavailable", "params": {}}
    }
    assert runtime.calls == []
