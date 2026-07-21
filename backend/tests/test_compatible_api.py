import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from chatapi.api.tool_sessions import get_tool_secret_cipher
from chatapi.chat.api import get_llm_client
from chatapi.llm.client import CanonicalResponse
from chatapi.models import LlmProvider, Skill
from chatapi.security.encryption import SecretCipher


class FinalAnswerLlm:
    async def complete(self, **_kwargs):
        return CanonicalResponse(
            content="Hello from the Skill.",
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
        skill = Skill(
            name="General helper",
            system_prompt="Help the user.",
            provider_id=provider.id,
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
    app.dependency_overrides[get_llm_client] = lambda: FinalAnswerLlm()
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

    assert models.json()["data"][0]["id"] == f"skill-{skill.id}"
    body = completion.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {
        "role": "assistant",
        "content": "Hello from the Skill.",
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
    assert chunks[0]["choices"][0]["delta"]["content"] == "Hello from the Skill."


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
    assert response.json()["content"] == [{"type": "text", "text": "Hello from the Skill."}]
    assert "event: content_block_delta" in streamed.text
    assert streamed.text.rstrip().endswith("event: message_stop\ndata: {\"type\":\"message_stop\"}")
