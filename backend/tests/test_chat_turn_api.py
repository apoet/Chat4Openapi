import hashlib
from cryptography.fernet import Fernet
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import chat4openapi.chat.api as chat_api_module
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.chat.agent import AgentTurnRequest, AgentTurnResult
from chat4openapi.chat.api import BROWSER_CHAT_COOKIE, get_llm_client
from chat4openapi.llm.client import CanonicalResponse, CanonicalToolCall
from chat4openapi.models import (
    Agent,
    AgentApiKey,
    AgentSkill,
    BrowserChatSession,
    Conversation,
    LlmProvider,
    Skill,
)
from chat4openapi.security.encryption import SecretCipher


class SequencedLlm:
    def __init__(self, responses: list[CanonicalResponse]) -> None:
        self.responses = list(responses)

    async def complete(self, **_kwargs):
        return self.responses.pop(0)


def seed_agent(factory, cipher: SecretCipher) -> tuple[Skill, Skill]:
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
            Agent(
                id=1,
                name="Chat4Openapi Agent",
                enabled=True,
                system_prompt="Route through declared Skills.",
                provider_id=provider.id,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        first = Skill(
            name="Gene lookup",
            description="Look up a gene.",
            system_prompt="Ask for a reference build when it is missing.",
            running=True,
        )
        second = Skill(
            name="Variant lookup",
            description="Look up a variant.",
            system_prompt="Look up variants.",
            running=True,
        )
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                AgentSkill(agent_id=1, skill_id=second.id, position=0),
                AgentSkill(agent_id=1, skill_id=first.id, position=1),
            ]
        )
        session.commit()
        return first, second


@pytest.mark.asyncio
async def test_chat_bootstrap_is_public_and_exposes_only_runnable_agent_summaries(
    client: httpx.AsyncClient, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    _first, second = seed_agent(db_session_factory, cipher)
    with db_session_factory() as session:
        provider = session.scalar(select(LlmProvider))
        stopped = Skill(name="Stopped", system_prompt="Stopped", running=False)
        session.add_all(
            [
                Agent(
                    id=2,
                    name="Disabled",
                    enabled=False,
                    is_default=False,
                    system_prompt="must-not-leak",
                    provider_id=provider.id,
                    mode="react",
                    max_iterations=8,
                ),
                Agent(
                    id=3,
                    name="Deleted",
                    enabled=True,
                    is_default=False,
                    system_prompt="must-not-leak",
                    provider_id=provider.id,
                    mode="react",
                    max_iterations=8,
                    deleted_at=datetime.now(UTC).replace(tzinfo=None),
                ),
                Agent(
                    id=4,
                    name="No runnable Skills",
                    enabled=True,
                    is_default=False,
                    system_prompt="must-not-leak",
                    provider_id=provider.id,
                    mode="react",
                    max_iterations=8,
                ),
                stopped,
            ]
        )
        session.flush()
        session.add_all(
            [
                AgentSkill(agent_id=2, skill_id=second.id, position=0),
                AgentSkill(agent_id=3, skill_id=second.id, position=0),
                AgentSkill(agent_id=4, skill_id=stopped.id, position=0),
            ]
        )
        session.commit()

    response = await client.get("/api/chat/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"subject_id", "agents"}
    assert isinstance(body["subject_id"], str) and len(body["subject_id"]) >= 20
    assert body["agents"] == [{"id": 1, "name": "Chat4Openapi Agent", "is_default": False}]
    assert "prompt" not in response.text.lower()
    assert "provider" not in response.text.lower()
    assert "key" not in response.text.lower()
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_chat_bootstrap_accepts_non_admin_bearer_without_expanding_payload(
    client: httpx.AsyncClient, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    seed_agent(db_session_factory, cipher)

    response = await client.get(
        "/api/chat/bootstrap",
        headers={"Authorization": "Bearer not-an-admin-session"},
    )

    assert response.status_code == 200
    assert list(response.json()["agents"][0]) == ["id", "name", "is_default"]


@pytest.mark.asyncio
async def test_forged_browser_cookie_cannot_resume_conversation_or_observe_agent_metadata(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm(
        [CanonicalResponse(content="Owned answer."), CanonicalResponse(content="must not run")]
    )
    app.dependency_overrides[get_llm_client] = lambda: llm

    bootstrap = await client.get("/api/chat/bootstrap")
    original_subject = bootstrap.json()["subject_id"]
    original_cookie = client.cookies.get(BROWSER_CHAT_COOKIE)
    created = await client.post(
        "/api/chat/turns", json={"agent_id": 1, "message": "Create"}
    )
    conversation_id = created.json()["conversation_id"]

    client.cookies.clear()
    client.cookies.set(BROWSER_CHAT_COOKIE, "forged-browser-session")
    denied = await client.post(
        "/api/chat/turns",
        json={"conversation_id": conversation_id, "message": "Steal"},
    )

    assert denied.status_code == 404
    assert denied.json() == {
        "error": {"code": "agent.conversation_not_found", "params": {}}
    }
    assert "agent_name" not in denied.text
    assert len(llm.responses) == 1
    rotated = await client.get("/api/chat/bootstrap")
    assert rotated.json()["subject_id"] != original_subject

    client.cookies.clear()
    client.cookies.set(BROWSER_CHAT_COOKIE, original_cookie)
    restored = await client.get("/api/chat/bootstrap")
    assert restored.json()["subject_id"] == original_subject


@pytest.mark.asyncio
async def test_expired_browser_cookie_rotates_to_a_new_subject(
    client: httpx.AsyncClient, db_session_factory
) -> None:
    first = await client.get("/api/chat/bootstrap")
    first_subject = first.json()["subject_id"]
    with db_session_factory() as session:
        browser_session = session.scalar(
            select(BrowserChatSession).where(
                BrowserChatSession.public_subject_id == first_subject
            )
        )
        assert browser_session is not None
        browser_session.expires_at = datetime(2000, 1, 1)
        session.commit()

    rotated = await client.get("/api/chat/bootstrap")

    assert rotated.status_code == 200
    assert rotated.json()["subject_id"] != first_subject
    assert BROWSER_CHAT_COOKIE in rotated.headers["set-cookie"]


@pytest.mark.asyncio
async def test_agent_key_used_for_browser_tool_credentials_is_not_conversation_identity(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    seed_agent(db_session_factory, cipher)
    secret = "c4o_browser_tool_owner_000000000000000000000000"
    with db_session_factory() as session:
        session.add(
            AgentApiKey(
                agent_id=1,
                label="Browser Tool credentials",
                key_prefix=secret[:12],
                key_hash=hashlib.sha256(secret.encode()).hexdigest(),
            )
        )
        session.commit()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: SequencedLlm(
        [CanonicalResponse(content="Done.")]
    )

    created = await client.post(
        "/api/chat/turns",
        json={"agent_id": 1, "message": "Use my browser Tool credentials"},
        headers={"Authorization": f"Bearer {secret}"},
    )

    assert created.status_code == 200
    with db_session_factory() as session:
        conversation = session.get(Conversation, created.json()["conversation_id"])
        assert conversation is not None
        assert conversation.agent_key_id is None
        assert conversation.browser_chat_session_id is not None


@pytest.mark.asyncio
async def test_browser_turn_pauses_and_resumes_with_structured_contract(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm(
        [
            CanonicalResponse(
                content="",
                tool_calls=[
                    CanonicalToolCall(
                        id="load_gene",
                        name="load_skills",
                        arguments={"skill_ids": [first.id]},
                    )
                ],
            ),
            CanonicalResponse(
                content="",
                tool_calls=[
                    CanonicalToolCall(
                        id="ask_reference",
                        name="ask_user",
                        arguments={
                            "question": "**请选择参考基因组**：GRCh37 还是 GRCh38？",
                            "reason": "坐标取决于参考基因组。",
                            "fields": ["reference"],
                            "choices": ["GRCh37", "GRCh38"],
                        },
                    )
                ],
            ),
            CanonicalResponse(content="已使用 **GRCh38** 完成查询。"),
        ]
    )
    app.dependency_overrides[get_llm_client] = lambda: llm

    paused = await client.post(
        "/api/chat/turns",
        json={
            "agent_id": 1,
            "message": "查询一个基因",
            "conversation_id": None,
        },
    )

    assert paused.status_code == 200
    paused_body = paused.json()
    assert paused_body == {
        "status": "needs_input",
        "conversation_id": paused_body["conversation_id"],
        "agent_id": 1,
        "agent_name": "Chat4Openapi Agent",
        "message": "**请选择参考基因组**：GRCh37 还是 GRCh38？",
        "loaded_skill_ids": [first.id],
        "pending": {
            "tool_call_id": "ask_reference",
            "question": "**请选择参考基因组**：GRCh37 还是 GRCh38？",
            "reason": "坐标取决于参考基因组。",
            "fields": ["reference"],
            "choices": ["GRCh37", "GRCh38"],
        },
    }

    completed = await client.post(
        "/api/chat/turns",
        json={
            "message": "GRCh38",
            "conversation_id": paused_body["conversation_id"],
        },
    )

    assert completed.status_code == 200
    assert completed.json() == {
        "status": "completed",
        "conversation_id": paused_body["conversation_id"],
        "agent_id": 1,
        "agent_name": "Chat4Openapi Agent",
        "message": "已使用 **GRCh38** 完成查询。",
        "loaded_skill_ids": [first.id],
        "pending": None,
    }


@pytest.mark.asyncio
async def test_browser_conversation_rejects_explicit_agent_change(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    _first, second = seed_agent(db_session_factory, cipher)
    with db_session_factory() as session:
        provider = session.scalar(select(LlmProvider))
        session.add(
            Agent(
                id=2,
                name="Second Agent",
                enabled=True,
                system_prompt="Second prompt.",
                provider_id=provider.id,
                mode="react",
                max_iterations=8,
            )
        )
        session.flush()
        session.add(AgentSkill(agent_id=2, skill_id=second.id, position=0))
        session.commit()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: SequencedLlm(
        [
            CanonicalResponse(content="First answer."),
            CanonicalResponse(content="Changed answer."),
        ]
    )
    created = await client.post(
        "/api/chat/turns",
        json={"agent_id": 1, "message": "Hello"},
    )

    response = await client.post(
        "/api/chat/turns",
        json={
            "agent_id": 2,
            "message": "Switch Agent",
            "conversation_id": created.json()["conversation_id"],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "chat.agent_locked",
            "params": {},
        }
    }


@pytest.mark.asyncio
async def test_browser_new_conversation_requires_agent_id(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: SequencedLlm(
        [CanonicalResponse(content="First.")]
    )
    response = await client.post("/api/chat/turns", json={"message": "Hello"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"
    assert "body.agent_id" in response.json()["error"]["params"]["fields"]


@pytest.mark.asyncio
async def test_browser_agent_id_can_be_omitted_on_continuation(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm([CanonicalResponse(content="First."), CanonicalResponse(content="Second.")])
    app.dependency_overrides[get_llm_client] = lambda: llm
    created = await client.post(
        "/api/chat/turns",
        json={"agent_id": 1, "message": "Hello"},
    )

    continued = await client.post(
        "/api/chat/turns",
        json={
            "message": "Continue",
            "conversation_id": created.json()["conversation_id"],
        },
    )

    assert continued.status_code == 200
    assert continued.json()["message"] == "Second."
    assert continued.json()["agent_id"] == 1
    assert continued.json()["agent_name"] == "Chat4Openapi Agent"


@pytest.mark.asyncio
async def test_browser_automatic_scope_does_not_add_later_agent_bindings(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm([CanonicalResponse(content="First."), CanonicalResponse(content="Second.")])
    app.dependency_overrides[get_llm_client] = lambda: llm
    created = await client.post("/api/chat/turns", json={"agent_id": 1, "message": "Hello"})
    conversation_id = created.json()["conversation_id"]
    with db_session_factory() as session:
        added = Skill(
            name="Added later",
            description="Later.",
            system_prompt="Later prompt.",
            running=True,
        )
        session.add(added)
        session.flush()
        session.add(AgentSkill(agent_id=1, skill_id=added.id, position=2))
        session.commit()

    continued = await client.post(
        "/api/chat/turns",
        json={
            "message": "Continue",
            "conversation_id": conversation_id,
        },
    )

    assert continued.status_code == 200
    with db_session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.candidate_scope_source == "automatic"
        assert conversation.candidate_skill_ids == [second.id, first.id]


@pytest.mark.asyncio
async def test_browser_turn_forwards_tool_session_and_maps_agent_result(
    client: httpx.AsyncClient, monkeypatch, db_session_factory
) -> None:
    requests: list[AgentTurnRequest] = []
    expected = AgentTurnResult(
        conversation_id="conversation-1",
        status="completed",
        content="Done.",
        loaded_skill_ids=[7],
        pending=None,
        input_tokens=3,
        output_tokens=2,
    )

    class RecordingRuntime:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def run(self, request: AgentTurnRequest) -> AgentTurnResult:
            requests.append(request)
            return expected

    monkeypatch.setattr(chat_api_module, "AgentRuntime", RecordingRuntime, raising=False)
    await client.get("/api/chat/bootstrap")
    with db_session_factory() as session:
        browser_session = session.scalar(select(BrowserChatSession))
        assert browser_session is not None
        browser_session_id = browser_session.id
        session.add(
            Agent(
                id=3,
                name="Tool Agent",
                enabled=True,
                system_prompt="Use Tools.",
                mode="react",
                max_iterations=8,
            )
        )
        session.add(
            Conversation(
                id="conversation-1",
                agent_id=3,
                browser_chat_session_id=browser_session_id,
            )
        )
        session.commit()

    client.cookies.set("chat4openapi_tool_session", "cookie-session")
    response = await client.post(
        "/api/chat/turns",
        json={"agent_id": 3, "message": "Run"},
        headers={"X-Chat4Openapi-Tool-Session": "header-session"},
    )

    assert response.status_code == 200
    assert requests == [
        AgentTurnRequest(
            agent_id=3,
            user_content="Run",
            candidate_skill_ids=[],
            interactive=True,
            tool_session_id="header-session",
            candidate_scope_source="automatic",
            browser_chat_session_id=browser_session_id,
        )
    ]
    assert response.json()["message"] == "Done."
    assert response.json()["agent_id"] == 3
    assert response.json()["agent_name"] == "Tool Agent"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_agent_id", [True, "1", 0, -1])
async def test_browser_turn_rejects_non_strict_positive_agent_ids(
    client: httpx.AsyncClient,
    app: FastAPI,
    invalid_agent_id,
) -> None:
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(Fernet.generate_key())
    response = await client.post(
        "/api/chat/turns",
        json={"message": "Run", "agent_id": invalid_agent_id},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"
    assert "body.agent_id" in response.json()["error"]["params"]["fields"]


@pytest.mark.asyncio
async def test_browser_turn_rejects_direct_candidate_skill_ids(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(Fernet.generate_key())

    response = await client.post(
        "/api/chat/turns",
        json={"message": "Run", "agent_id": 1, "candidate_skill_ids": [7]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"
    assert "body.candidate_skill_ids" in response.json()["error"]["params"]["fields"]
