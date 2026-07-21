import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from chatapi.api.tool_sessions import get_tool_secret_cipher
from chatapi.models import ApiSource, GlobalToolAuthConfig, LlmProvider, Tool
from chatapi.security.encryption import SecretCipher

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def login(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def seed(factory: sessionmaker[Session], cipher: SecretCipher) -> tuple[int, int, int, int]:
    with factory() as session:
        provider = LlmProvider(
            name="Primary",
            provider_type="openai",
            base_url="https://llm.test/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "secret"}),
            default_model="gpt-test",
            enabled=True,
        )
        source = ApiSource(name="API", source_type="openapi", base_url="https://api.test")
        session.add_all([provider, source])
        session.flush()
        enabled = make_tool(source.id, "enabled_tool", True, "GET /enabled")
        disabled = make_tool(source.id, "disabled_tool", False, "GET /disabled")
        login_tool = make_tool(source.id, "login_tool", True, "POST /login")
        session.add_all([enabled, disabled, login_tool])
        session.flush()
        session.add(
            GlobalToolAuthConfig(
                id=1,
                enabled=True,
                login_tool_id=login_tool.id,
                token_json_path="$.token",
            )
        )
        session.commit()
        return provider.id, enabled.id, disabled.id, login_tool.id


def make_tool(source_id: int, name: str, enabled: bool, operation: str) -> Tool:
    return Tool(
        api_source_id=source_id,
        operation_key=operation,
        name=name,
        description=name,
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        execution_schema={"method": operation.split()[0], "path": operation.split()[1], "parameters": []},
        enabled=enabled,
    )


@pytest.mark.asyncio
async def test_skill_lifecycle_binds_only_enabled_non_login_tools(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    csrf = await login(client)
    provider_id, enabled_id, disabled_id, login_id = seed(db_session_factory, cipher)

    disabled = await client.post(
        "/api/admin/skills",
        json={
            "name": "Bad disabled",
            "system_prompt": "Help",
            "provider_id": provider_id,
            "tool_ids": [disabled_id],
        },
        headers={"X-CSRF-Token": csrf},
    )
    login_bound = await client.post(
        "/api/admin/skills",
        json={
            "name": "Bad login",
            "system_prompt": "Help",
            "provider_id": provider_id,
            "tool_ids": [login_id],
        },
        headers={"X-CSRF-Token": csrf},
    )
    created = await client.post(
        "/api/admin/skills",
        json={
            "name": "Pet helper",
            "description": "Uses pet tools",
            "system_prompt": "Use {{tool:enabled_tool}} when needed.",
            "provider_id": provider_id,
            "tool_ids": [enabled_id],
        },
        headers={"X-CSRF-Token": csrf},
    )
    skill_id = created.json()["id"]
    started = await client.post(
        f"/api/admin/skills/{skill_id}/start", headers={"X-CSRF-Token": csrf}
    )
    eligible = await client.get("/api/admin/skills/eligible-tools")
    running = await client.get("/api/skills")
    stopped = await client.post(
        f"/api/admin/skills/{skill_id}/stop", headers={"X-CSRF-Token": csrf}
    )

    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "skills.tool_unavailable"
    assert login_bound.status_code == 409
    assert created.status_code == 201
    assert created.json()["tools"][0]["name"] == "enabled_tool"
    assert started.json()["running"] is True
    assert [item["name"] for item in eligible.json()] == ["enabled_tool"]
    assert [item["name"] for item in running.json()] == ["Pet helper"]
    assert stopped.json()["running"] is False
