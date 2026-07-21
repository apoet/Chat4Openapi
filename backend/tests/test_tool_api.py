import json
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi import FastAPI

from chatapi.api.tool_sessions import get_tool_executor, get_tool_secret_cipher
from chatapi.security.encryption import SecretCipher
from chatapi.tools.executor import ToolExecutionResult

ADMIN_PAYLOAD = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}
FIXTURE = Path(__file__).parent / "fixtures" / "openapi3.yaml"


class ApiFakeExecutor:
    async def execute(self, tool, _source, arguments, auth):
        if tool.name == "createPet":
            return ToolExecutionResult(
                200,
                {"access_token": f"token-for-{arguments['user']}"},
                "application/json",
            )
        if tool.name == "getMe":
            return ToolExecutionResult(
                200,
                {"authorization": auth.headers.get("Authorization")},
                "application/json",
            )
        raise AssertionError(tool.name)


async def admin_login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN_PAYLOAD)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )
    return response.json()["csrf_token"]


def import_payload() -> dict:
    document = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    document["paths"]["/me"] = {
        "get": {
            "operationId": "getMe",
            "responses": {"200": {"description": "Current user"}},
        }
    }
    return {
        "name": "Pet API",
        "base_url": "https://api.example.test/v1",
        "document": json.dumps(document),
    }


@pytest.mark.asyncio
async def test_tool_import_requires_admin_and_csrf(client: httpx.AsyncClient) -> None:
    unauthenticated = await client.post("/api/admin/sources/import", json=import_payload())
    csrf = await admin_login(client)
    missing_csrf = await client.post("/api/admin/sources/import", json=import_payload())
    imported = await client.post(
        "/api/admin/sources/import-file",
        data={"name": "Pet API", "base_url": "https://api.example.test/v1"},
        files={"document": ("openapi.yaml", FIXTURE.read_bytes(), "application/yaml")},
        headers={"X-CSRF-Token": csrf},
    )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert imported.status_code == 201
    assert imported.json()["source"]["name"] == "Pet API"
    assert imported.json()["tools"][0]["name"] == "createPet"
    assert imported.json()["tools"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_public_tool_session_config_reports_login_requirement(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/tool-session/config")

    assert response.status_code == 200
    assert response.json() == {"enabled": False}


@pytest.mark.asyncio
async def test_tool_lifecycle_and_login_binding_conflicts(client: httpx.AsyncClient) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]

    enabled = await client.patch(
        f"/api/admin/tools/{tool_id}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    configured = await client.put(
        "/api/admin/tool-auth",
        json={
            "enabled": True,
            "login_tool_id": tool_id,
            "username_field": "user",
            "password_field": "pass",
            "token_json_path": "$.access_token",
            "auth_type": "bearer",
            "auth_name": "Authorization",
            "auth_prefix": "Bearer",
            "idle_minutes": 30,
            "absolute_hours": 8,
        },
        headers={"X-CSRF-Token": csrf},
    )
    disable = await client.patch(
        f"/api/admin/tools/{tool_id}/enabled",
        json={"enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    delete = await client.delete(
        f"/api/admin/tools/{tool_id}", headers={"X-CSRF-Token": csrf}
    )

    assert enabled.status_code == 200
    assert configured.status_code == 200
    assert disable.status_code == 409
    assert disable.json()["error"]["code"] == "tools.login_tool_conflict"
    assert delete.status_code == 409


@pytest.mark.asyncio
async def test_browser_and_api_tool_sessions_use_original_api_credentials(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    app.dependency_overrides[get_tool_executor] = lambda: ApiFakeExecutor()
    test_cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: test_cipher
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    login_tool_id = imported.json()["tools"][0]["id"]
    protected_tool_id = imported.json()["tools"][1]["id"]
    await client.patch(
        f"/api/admin/tools/{login_tool_id}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    await client.patch(
        f"/api/admin/tools/{protected_tool_id}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    await client.put(
        "/api/admin/tool-auth",
        json={
            "enabled": True,
            "login_tool_id": login_tool_id,
            "username_field": "user",
            "password_field": "pass",
            "token_json_path": "$.access_token",
            "auth_type": "bearer",
            "auth_name": "Authorization",
            "auth_prefix": "Bearer",
            "idle_minutes": 30,
            "absolute_hours": 8,
        },
        headers={"X-CSRF-Token": csrf},
    )

    browser_login = await client.post(
        "/api/tool-session/login", json={"username": "alice", "password": "api-password"}
    )
    status = await client.get("/api/tool-session/status")
    invocation = await client.post(
        f"/api/tools/{protected_tool_id}/invoke", json={"arguments": {}}
    )
    logout = await client.post("/api/tool-session/logout")
    missing = await client.get("/api/tool-session/status")
    api_login = await client.post(
        "/v1/tool-sessions", json={"username": "bob", "password": "api-password"}
    )

    assert browser_login.status_code == 200
    assert "HttpOnly" in browser_login.headers["set-cookie"]
    assert status.json()["authenticated"] is True
    assert invocation.json()["data"] == {"authorization": "Bearer token-for-alice"}
    assert logout.status_code == 204
    assert missing.status_code == 401
    assert api_login.status_code == 201
    assert api_login.json()["tool_session_id"]
    assert "api-password" not in json.dumps(api_login.json())
