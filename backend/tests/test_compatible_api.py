import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from chatapi.api.tool_sessions import get_tool_secret_cipher
from chatapi.chat.api import get_llm_client
from chatapi.llm.client import CanonicalResponse, CanonicalToolCall, LlmProviderError
from chatapi.models import AgentConfig, ChatMessage, Conversation, LlmProvider, Skill
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
async def test_openai_new_conversation_persists_and_uses_full_transcript(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [
                {"role": "system", "content": "Client policy"},
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": "Follow up"},
            ],
        },
    )

    assert response.status_code == 200
    visible = [
        (message.role, message.content)
        for message in llm.calls[0]["messages"]
        if message.role in {"system", "user", "assistant"}
    ]
    assert ("system", "Client policy") in visible
    assert visible[-3:] == [
        ("user", "First question"),
        ("assistant", "First answer"),
        ("user", "Follow up"),
    ]
    with db_session_factory() as session:
        conversation_id = response.json()["chatapi_conversation_id"]
        stored = session.query(ChatMessage).filter_by(
            conversation_id=conversation_id
        ).order_by(ChatMessage.sequence).all()
        assert [(item.role, item.content["text"]) for item in stored] == [
            ("system", "Client policy"),
            ("user", "First question"),
            ("assistant", "First answer"),
            ("user", "Follow up"),
            ("assistant", "Hello from the Agent."),
        ]


@pytest.mark.asyncio
async def test_anthropic_top_level_system_and_full_transcript_are_preserved(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/messages",
        json={
            "model": f"skill-{skill.id}",
            "max_tokens": 128,
            "system": [{"type": "text", "text": "Anthropic policy"}],
            "messages": [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "user", "content": [{"type": "text", "text": "Follow up"}]},
            ],
        },
    )

    assert response.status_code == 200
    assert [(message.role, message.content) for message in llm.calls[0]["messages"]][-4:] == [
        ("system", "Anthropic policy"),
        ("user", "First question"),
        ("assistant", "First answer"),
        ("user", "Follow up"),
    ]


@pytest.mark.asyncio
async def test_compatibility_continuation_appends_only_new_transcript_suffix(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)
    first = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "First question"}],
        },
    )
    conversation_id = first.json()["chatapi_conversation_id"]

    second = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "conversation_id": conversation_id,
            "messages": [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "Hello from the Agent."},
                {"role": "user", "content": "Second question"},
            ],
        },
    )

    assert second.status_code == 200
    with db_session_factory() as session:
        stored = session.query(ChatMessage).filter_by(
            conversation_id=conversation_id
        ).order_by(ChatMessage.sequence).all()
        assert [(item.role, item.content["text"]) for item in stored] == [
            ("user", "First question"),
            ("assistant", "Hello from the Agent."),
            ("user", "Second question"),
            ("assistant", "Hello from the Agent."),
        ]


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
async def test_agent_default_explicit_empty_extension_remains_automatic_on_continuation(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    seed(db_session_factory, cipher)
    created = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "chatapi_skill_ids": [],
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    conversation_id = created.json()["chatapi_conversation_id"]

    continued = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "chatapi_skill_ids": [],
            "conversation_id": conversation_id,
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hello from the Agent."},
                {"role": "user", "content": "Continue"},
            ],
        },
    )

    assert continued.status_code == 200
    with db_session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.candidate_scope_source == "automatic"


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
async def test_agent_default_continuation_keeps_initial_automatic_scope_when_catalog_changes(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    first_skill = seed(db_session_factory, cipher)
    created = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    conversation_id = created.json()["chatapi_conversation_id"]
    with db_session_factory() as session:
        session.add(
            Skill(
                name="Added later",
                description="A later catalog entry.",
                system_prompt="Help later.",
                running=True,
            )
        )
        session.commit()

    continued = await client.post(
        "/v1/chat/completions",
        json={
            "model": "agent-default",
            "conversation_id": conversation_id,
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hello from the Agent."},
                {"role": "user", "content": "Continue"},
            ],
        },
    )

    assert continued.status_code == 200
    catalog = json.loads(llm.calls[-1]["messages"][1].content)
    assert [item["id"] for item in catalog["skills"]] == [first_skill.id]
    with db_session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.candidate_scope_source == "automatic"


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


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_state", ["stopped", "deleted"])
async def test_existing_skill_alias_continuation_records_unavailable_failure(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory,
    unavailable_state: str,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    llm = FinalAnswerLlm()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: llm
    skill = seed(db_session_factory, cipher)
    created = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    conversation_id = created.json()["chatapi_conversation_id"]
    with db_session_factory() as session:
        stored = session.get(Skill, skill.id)
        if unavailable_state == "stopped":
            stored.running = False
        else:
            stored.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

    continued = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "conversation_id": conversation_id,
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hello from the Agent."},
                {"role": "user", "content": "Continue"},
            ],
        },
    )

    assert continued.status_code == 409
    assert continued.json()["error"] == {
        "code": "agent.no_eligible_skills",
        "params": {},
    }
    assert len(llm.calls) == 1
    with db_session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == (
            "No eligible Skills remain for this conversation."
        )


@pytest.mark.asyncio
async def test_provider_failure_uses_redacted_structured_api_envelope(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    class FailedLlm:
        async def complete(self, **_kwargs):
            raise LlmProviderError(500, {"body": "secret upstream response"})

    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: FailedLlm()
    skill = seed(db_session_factory, cipher)

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": f"skill-{skill.id}",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "agent.provider_failed",
            "params": {"reason": "LLM provider request failed."},
        }
    }
    assert "secret" not in response.text.lower()
    with db_session_factory() as session:
        conversation = session.query(Conversation).one()
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == "LLM provider request failed."
