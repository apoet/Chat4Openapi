import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

import chatapi.chat.api as chat_api_module
from chatapi.api.tool_sessions import get_tool_secret_cipher
from chatapi.chat.agent import AgentTurnRequest, AgentTurnResult
from chatapi.chat.api import get_llm_client
from chatapi.llm.client import CanonicalResponse, CanonicalToolCall
from chatapi.models import AgentConfig, Conversation, LlmProvider, Skill
from chatapi.security.encryption import SecretCipher


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
        session.commit()
        return first, second


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
            "message": "查询一个基因",
            "conversation_id": None,
            "candidate_skill_ids": [first.id, second.id],
        },
    )

    assert paused.status_code == 200
    paused_body = paused.json()
    assert paused_body == {
        "status": "needs_input",
        "conversation_id": paused_body["conversation_id"],
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
        "message": "已使用 **GRCh38** 完成查询。",
        "loaded_skill_ids": [first.id],
        "pending": None,
    }


@pytest.mark.asyncio
async def test_browser_turn_rejects_candidate_changes_for_existing_conversation(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: SequencedLlm(
        [CanonicalResponse(content="First answer.")]
    )
    created = await client.post(
        "/api/chat/turns",
        json={"message": "Hello", "candidate_skill_ids": [first.id]},
    )

    response = await client.post(
        "/api/chat/turns",
        json={
            "message": "Switch Skills",
            "conversation_id": created.json()["conversation_id"],
            "candidate_skill_ids": [second.id],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "chat.candidate_scope_locked",
            "params": {},
        }
    }


@pytest.mark.asyncio
async def test_browser_explicit_scope_rejects_explicit_empty_candidate_list(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, _second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_llm_client] = lambda: SequencedLlm(
        [CanonicalResponse(content="First.")]
    )
    created = await client.post(
        "/api/chat/turns",
        json={"message": "Hello", "candidate_skill_ids": [first.id]},
    )

    continued = await client.post(
        "/api/chat/turns",
        json={
            "message": "Continue",
            "conversation_id": created.json()["conversation_id"],
            "candidate_skill_ids": [],
        },
    )

    assert continued.status_code == 409
    assert continued.json()["error"]["code"] == "chat.candidate_scope_locked"


@pytest.mark.asyncio
async def test_browser_explicit_scope_can_be_omitted_on_continuation(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, _second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm(
        [CanonicalResponse(content="First."), CanonicalResponse(content="Second.")]
    )
    app.dependency_overrides[get_llm_client] = lambda: llm
    created = await client.post(
        "/api/chat/turns",
        json={"message": "Hello", "candidate_skill_ids": [first.id]},
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


@pytest.mark.asyncio
async def test_browser_auto_scope_continuation_does_not_recompute_changed_catalog(
    client: httpx.AsyncClient, app: FastAPI, db_session_factory
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    first, _second = seed_agent(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    llm = SequencedLlm(
        [CanonicalResponse(content="First."), CanonicalResponse(content="Second.")]
    )
    app.dependency_overrides[get_llm_client] = lambda: llm
    created = await client.post(
        "/api/chat/turns", json={"message": "Hello", "candidate_skill_ids": []}
    )
    conversation_id = created.json()["conversation_id"]
    with db_session_factory() as session:
        session.add(
            Skill(
                name="Added later",
                description="Later.",
                system_prompt="Later prompt.",
                running=True,
            )
        )
        session.commit()

    continued = await client.post(
        "/api/chat/turns",
        json={
            "message": "Continue",
            "conversation_id": conversation_id,
            "candidate_skill_ids": [],
        },
    )

    assert continued.status_code == 200
    with db_session_factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation.candidate_scope_source == "automatic"
        assert conversation.candidate_skill_ids == [first.id, _second.id]


@pytest.mark.asyncio
async def test_browser_turn_forwards_tool_session_and_maps_agent_result(
    client: httpx.AsyncClient, monkeypatch
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

    client.cookies.set("chatapi_tool_session", "cookie-session")
    response = await client.post(
        "/api/chat/turns",
        json={"message": "Run", "candidate_skill_ids": [7]},
        headers={"X-ChatAPI-Tool-Session": "header-session"},
    )

    assert response.status_code == 200
    assert requests == [
        AgentTurnRequest(
            user_content="Run",
            candidate_skill_ids=[7],
                interactive=True,
                tool_session_id="header-session",
                candidate_scope_source="explicit",
            )
    ]
    assert response.json()["message"] == "Done."


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_skill_id", [True, "1", 0, -1])
async def test_browser_turn_rejects_non_strict_positive_candidate_skill_ids(
    client: httpx.AsyncClient,
    app: FastAPI,
    invalid_skill_id,
) -> None:
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(
        Fernet.generate_key()
    )
    response = await client.post(
        "/api/chat/turns",
        json={"message": "Run", "candidate_skill_ids": [invalid_skill_id]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"
    assert "body.candidate_skill_ids.0" in response.json()["error"]["params"]["fields"]
