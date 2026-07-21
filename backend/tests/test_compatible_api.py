import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from chatapi.api.tool_sessions import get_tool_secret_cipher
from chatapi.chat.api import get_llm_client
from chatapi.llm.client import CanonicalResponse, CanonicalToolCall
from chatapi.models import AgentConfig, Conversation, LlmProvider, Skill
from chatapi.security.encryption import SecretCipher


class FinalAnswerLlm:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, **_kwargs):
        self.calls.append(_kwargs)
        return CanonicalResponse(
            content="Hello from the Agent.",
            stop_reason="stop",
            input_tokens=5,
            output_tokens=6,
        )


def seed(factory, cipher: SecretCipher) -> Skill:
    with factory() as session:
        provider = LlmProvider(
            name="Primary",
            provider_type="openai",
            base_url="https://llm.test/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "secret"}),
            default_model="gpt-test",
        )
        session.add(provider)
        session.flush()
        session.add(
            AgentConfig(
                id=1,
                name="ChatAPI Agent",
                enabled=True,
                system_prompt="Route through declared Skills.",
                provider_id=provider.id,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        skill = Skill(
            name="General helper",
            description="General help.",
            system_prompt="Help the user.",
            running=True,
        )
        session.add(skill)
        session.commit()
        return skill


@pytest.mark.asyncio
async def test_openai_models_completion_and_sse_are_compatible(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)

    models = await client.get("/v1/models")
    completion = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    streamed = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    )

    assert [model["id"] for model in models.json()["data"]] == [
        "agent-default",
        f"skill-{skill.id}",
    ]
    assert models.json()["data"][1]["name"] == "General helper"
    body = completion.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Hello from the Agent.",
    }
    assert body["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 6,
        "total_tokens": 11,
    }
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.text.rstrip().endswith("data: [DONE]")
    chunks = [
        json.loads(line[6:])
        for line in streamed.text.splitlines()
        if line.startswith("data: {")
    ]
    assert chunks[0]["choices"][0]["delta"]["content"] == "Hello from the Agent."
    with db_session_factory() as session:
        conversations = session.query(Conversation).order_by(Conversation.created_at).all()
        assert [conversation.candidate_skill_ids for conversation in conversations] == [
            [skill.id],
            [skill.id],
        ]
        assert all(conversation.agent_mode == "react" for conversation in conversations)
        assert all(conversation.pending_clarification is None for conversation in conversations)


@pytest.mark.asyncio
async def test_anthropic_messages_and_event_stream_are_compatible(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    skill = seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/messages",
        json={
            "model": f"skill-{skill.id}",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Hello"}],
        },
        headers={"anthropic-version": "2023-06-01"},
    )
    streamed = await client.post(
        "/v1/messages",
        json={
            "model": f"skill-{skill.id}",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    )

    assert response.json()["type"] == "message"
    assert response.json()["content"] == [{"type": "text", "text": "Hello from the Agent."}]
    assert "event: content_block_delta" in streamed.text
    assert streamed.text.rstrip().endswith("event: message_stop\ndata: {\"type\":\"message_stop\"}")


@pytest.mark.asyncio
async def test_agent_default_and_extension_scope_delegate_non_interactively(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    skill = seed(db_session_factory, cipher)

    unrestricted = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    restricted = await client.post(
        "/v1/messages",
        json={
            "model": "agent-default",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
            "chatapi_skill_ids": [skill.id],
        },
    )

    assert unrestricted.status_code == 200
    assert restricted.status_code == 200
    with db_session_factory() as session:
        conversations = session.query(Conversation).order_by(Conversation.created_at).all()
        assert [conversation.candidate_skill_ids for conversation in conversations] == [
            [skill.id],
            [skill.id],
        ]
        assert all(conversation.agent_mode == "react" for conversation in conversations)
        assert all(conversation.pending_clarification is None for conversation in conversations)


@pytest.mark.asyncio
async def test_skill_alias_rejects_conflicting_extension_scope(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    skill = seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "chatapi_skill_ids": [skill.id],
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "chat.candidate_scope_conflict"


@pytest.mark.asyncio
async def test_noninteractive_compatibility_never_exposes_ask_user(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    skill = seed(db_session_factory, cipher)

    class NoninteractiveLlm:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def complete(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                )
            return CanonicalResponse(content="Assumed GRCh38 and completed the request.")

    llm = NoninteractiveLlm()
    app.dependency_overrides[get_llm_client] = lambda: llm

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "messages": [{"role": "user", "content": "查询一个基因"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"].startswith("Assumed")
    assert [tool.name for tool in llm.calls[1]["tools"]] == []
    with db_session_factory() as session:
        conversation = session.query(Conversation).one()
        assert conversation.agent_mode == "react"
        assert conversation.pending_clarification is None


@pytest.mark.asyncio
async def test_skill_alias_conversation_rejects_agent_default_scope_change(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    skill = seed(db_session_factory, cipher)
    created = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    changed = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "conversation_id": created.json()["chatapi_conversation_id"],
            "messages": [{"role": "user", "content": "Continue"}],
        },
    )

    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "chat.candidate_scope_locked"


@pytest.mark.asyncio
async def test_agent_default_conversation_rejects_skill_alias_scope_change(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    skill = seed(db_session_factory, cipher)
    created = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    changed = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "conversation_id": created.json()["chatapi_conversation_id"],
            "messages": [{"role": "user", "content": "Continue"}],
        },
    )

    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "chat.candidate_scope_locked"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["skill-999", "skill-0", "skill--1"])
async def test_unknown_or_illegal_skill_alias_is_not_found(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory, model: str
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
    seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "chat.skill_not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_state", ["stopped", "deleted"])
async def test_existing_unavailable_skill_alias_is_rejected(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory,
    unavailable_state: str,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)
    with db_session_factory() as session:
        stored = session.get(Skill, skill.id)
        if unavailable_state == "stopped":
            stored.running = False
        else:
            stored.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "agent.skill_unavailable",
        "params": {"skill_ids": [skill.id]},
    }
    assert llm.calls == []
