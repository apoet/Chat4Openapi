import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.llm.client import (
    CanonicalMessage,
    CanonicalResponse,
    CanonicalTool,
    LlmClient,
    LlmProviderError,
)
from chat4openapi.models import AgentConfig, LlmProvider
from chat4openapi.security.encryption import SecretCipher

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def csrf(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    login = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return login.json()["csrf_token"]


@pytest.mark.asyncio
async def test_provider_api_encrypts_and_never_returns_api_key(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    token = await csrf(client)

    created = await client.post(
        "/api/admin/providers",
        json={
            "name": "Primary",
            "provider_type": "openai",
            "base_url": "https://llm.example.test/v1",
            "api_key": "plain-secret-key",
            "default_model": "gpt-test",
            "enabled": True,
        },
        headers={"X-CSRF-Token": token},
    )
    listed = await client.get("/api/admin/providers")

    assert created.status_code == 201
    assert created.json()["has_api_key"] is True
    assert "api_key" not in created.json()
    assert "plain-secret-key" not in json.dumps(created.json())
    assert listed.json()[0]["name"] == "Primary"
    with db_session_factory() as session:
        row = session.scalar(select(LlmProvider))
        assert row is not None
        assert b"plain-secret-key" not in row.encrypted_api_key
        assert cipher.decrypt_json(row.encrypted_api_key) == {"api_key": "plain-secret-key"}


@pytest.mark.asyncio
async def test_provider_connection_test_uses_encrypted_configuration(
    client: httpx.AsyncClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    token = await csrf(client)
    created = await client.post(
        "/api/admin/providers",
        json={
            "name": "Connection test",
            "provider_type": "openai",
            "base_url": "https://llm.example.test/v1",
            "api_key": "connection-secret",
            "default_model": "gpt-test",
        },
        headers={"X-CSRF-Token": token},
    )
    captured: dict[str, object] = {}

    async def complete(_self: LlmClient, **kwargs: object) -> CanonicalResponse:
        captured.update(kwargs)
        return CanonicalResponse(content="OK")

    monkeypatch.setattr(LlmClient, "complete", complete)

    tested = await client.post(
        f"/api/admin/providers/{created.json()['id']}/test",
        headers={"X-CSRF-Token": token},
    )

    assert tested.status_code == 200
    assert tested.json() == {"ok": True, "model": "gpt-test", "response": "OK"}
    assert captured["api_key"] == "connection-secret"


def seed_provider_lifecycle(
    factory: sessionmaker[Session], cipher: SecretCipher
) -> tuple[int, int]:
    with factory() as session:
        referenced = LlmProvider(
            name="Agent provider",
            provider_type="openai",
            base_url="https://agent-provider.test/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "agent-secret"}),
            default_model="agent-model",
            enabled=True,
        )
        unreferenced = LlmProvider(
            name="Spare provider",
            provider_type="openai",
            base_url="https://spare-provider.test/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "spare-secret"}),
            default_model="spare-model",
            enabled=True,
        )
        session.add_all([referenced, unreferenced])
        session.flush()
        session.add(
            AgentConfig(
                id=1,
                name="Chat4Openapi Agent",
                enabled=True,
                system_prompt="Use configured Skills.",
                provider_id=referenced.id,
                mode="human_in_loop",
                max_iterations=8,
            )
        )
        session.commit()
        return referenced.id, unreferenced.id


@pytest.mark.asyncio
async def test_agent_provider_cannot_be_disabled_or_deleted(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await csrf(client)
    cipher = SecretCipher(Fernet.generate_key())
    referenced_id, _ = seed_provider_lifecycle(db_session_factory, cipher)

    disabled = await client.patch(
        f"/api/admin/providers/{referenced_id}",
        json={"enabled": False},
        headers={"X-CSRF-Token": token},
    )
    deleted = await client.delete(
        f"/api/admin/providers/{referenced_id}",
        headers={"X-CSRF-Token": token},
    )

    expected = {
        "error": {"code": "providers.agent_in_use", "params": {"agent_id": 1}}
    }
    assert disabled.status_code == 409
    assert disabled.json() == expected
    assert deleted.status_code == 409
    assert deleted.json() == expected
    with db_session_factory() as session:
        provider = session.get(LlmProvider, referenced_id)
        assert provider is not None
        assert provider.enabled is True
        assert provider.deleted_at is None
        assert session.get(AgentConfig, 1).provider_id == referenced_id


@pytest.mark.asyncio
async def test_unreferenced_provider_can_be_disabled_and_deleted(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await csrf(client)
    cipher = SecretCipher(Fernet.generate_key())
    referenced_id, unreferenced_id = seed_provider_lifecycle(
        db_session_factory, cipher
    )

    disabled = await client.patch(
        f"/api/admin/providers/{unreferenced_id}",
        json={"enabled": False},
        headers={"X-CSRF-Token": token},
    )
    deleted = await client.delete(
        f"/api/admin/providers/{unreferenced_id}",
        headers={"X-CSRF-Token": token},
    )

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    with db_session_factory() as session:
        provider = session.get(LlmProvider, unreferenced_id)
        assert provider is not None
        assert provider.enabled is False
        assert provider.deleted_at is not None
        assert session.get(AgentConfig, 1).provider_id == referenced_id


@pytest.mark.asyncio
async def test_openai_and_anthropic_adapters_translate_tools_and_messages() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_pet",
                                            "arguments": '{"id":7}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                },
            )
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Checking."},
                    {"type": "tool_use", "id": "tool_1", "name": "get_pet", "input": {"id": 7}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    transport = httpx.MockTransport(handler)
    messages = [
        CanonicalMessage(role="system", content="Be concise"),
        CanonicalMessage(role="user", content="Find pet 7"),
    ]
    tools = [
        CanonicalTool(
            name="get_pet",
            description="Get a pet",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
        )
    ]
    openai = await LlmClient(transport=transport).complete(
        provider_type="openai",
        base_url="https://openai.test/v1",
        api_key="openai-key",
        model="gpt-test",
        messages=messages,
        tools=tools,
    )
    anthropic = await LlmClient(transport=transport).complete(
        provider_type="anthropic",
        base_url="https://anthropic.test/v1",
        api_key="anthropic-key",
        model="claude-test",
        messages=messages,
        tools=tools,
    )

    assert requests[0].headers["Authorization"] == "Bearer openai-key"
    assert json.loads(requests[0].content)["tools"][0]["function"]["name"] == "get_pet"
    assert openai.tool_calls[0].arguments == {"id": 7}
    assert requests[1].headers["x-api-key"] == "anthropic-key"
    assert json.loads(requests[1].content)["system"] == "Be concise"
    assert anthropic.content == "Checking."
    assert anthropic.tool_calls[0].name == "get_pet"


@pytest.mark.asyncio
async def test_llm_client_normalizes_network_failures() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("certificate verify failed", request=request)

    with pytest.raises(LlmProviderError) as error:
        await LlmClient(transport=httpx.MockTransport(fail)).complete(
            provider_type="openai",
            base_url="https://openai.test/v1",
            api_key="secret",
            model="gpt-test",
            messages=[CanonicalMessage(role="user", content="hello")],
        )

    assert error.value.status_code == 502
    assert error.value.details == {"message": "certificate verify failed"}


def test_openai_tool_results_are_serialized_as_json_strings() -> None:
    message = LlmClient._openai_message(CanonicalMessage(
        role="tool",
        content={"code": 0, "data": {"chromosome": "1", "map_location": "1p22.1"}},
        tool_call_id="call_1",
        name="get_gene",
    ))

    assert json.loads(message["content"]) == {
        "code": 0,
        "data": {"chromosome": "1", "map_location": "1p22.1"},
    }
