import json
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chatapi.api import admin_tools
from chatapi.api.tool_sessions import get_tool_executor, get_tool_secret_cipher
from chatapi.models import Tool, ToolParameterOverride
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


@pytest.mark.asyncio
async def test_url_import_does_not_verify_https_certificates(monkeypatch) -> None:
    captured: dict = {}
    real_async_client = httpx.AsyncClient

    def create_client(*args, **kwargs):
        captured.update(kwargs)
        return real_async_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=FIXTURE.read_bytes())
            ),
            timeout=kwargs["timeout"],
            verify=kwargs.get("verify", True),
        )

    async def allow_network(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(admin_tools.httpx, "AsyncClient", create_client)
    monkeypatch.setattr(admin_tools, "validate_network_target", allow_network)

    document = await admin_tools._fetch_openapi_document(
        "https://self-signed.example.test/openapi.yaml", False
    )

    assert document == FIXTURE.read_bytes()
    assert captured["verify"] is False


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
async def test_tool_list_exposes_tags_and_execution_metadata(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    payload = import_payload()
    document = json.loads(payload["document"])
    document["paths"]["/pets"]["post"]["tags"] = ["Pets", "Public"]
    payload["document"] = json.dumps(document)
    imported = await client.post(
        "/api/admin/sources/import",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    listed = await client.get("/api/admin/tools")

    assert imported.status_code == 201
    assert listed.status_code == 200
    tool = listed.json()[0]
    assert tool["tags"] == ["Pets", "Public"]
    assert tool["execution_schema"]["parameters"][0] == {
        "name": "trace",
        "in": "query",
        "required": False,
        "argument": "trace",
    }


@pytest.mark.asyncio
async def test_tool_description_can_be_updated(client: httpx.AsyncClient) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]

    updated = await client.patch(
        f"/api/admin/tools/{tool_id}",
        json={"description": "Search pets by criteria"},
        headers={"X-CSRF-Token": csrf},
    )
    listed = await client.get("/api/admin/tools")

    assert updated.status_code == 200
    assert updated.json()["description"] == "Search pets by criteria"
    assert listed.json()[0]["description"] == "Search pets by criteria"


@pytest.mark.asyncio
async def test_tool_parameter_guidance_updates_the_effective_schema(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]

    updated = await client.put(
        f"/api/admin/tools/{tool_id}/parameters/name",
        json={"description": "Pet name supplied by the user", "example": "Fido"},
        headers={"X-CSRF-Token": csrf},
    )
    listed = await client.get("/api/admin/tools")

    assert updated.status_code == 200
    assert updated.json()["input_schema"]["properties"]["name"] == {
        "type": "string",
        "description": "Pet name supplied by the user",
        "example": "Fido",
    }
    listed_tool = next(item for item in listed.json() if item["id"] == tool_id)
    assert listed_tool["input_schema"] == updated.json()["input_schema"]
    with db_session_factory() as session:
        stored = session.get(Tool, tool_id)
        assert stored is not None
        assert stored.input_schema["properties"]["name"] == {"type": "string"}


@pytest.mark.asyncio
async def test_tool_parameter_guidance_rejects_an_unknown_argument(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]

    response = await client.put(
        f"/api/admin/tools/{tool_id}/parameters/missing",
        json={"description": "Unknown"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tools.parameter_not_found"


@pytest.mark.asyncio
async def test_tool_parameter_guidance_rejects_swagger_owned_fields(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]

    response = await client.put(
        f"/api/admin/tools/{tool_id}/parameters/name",
        json={
            "description": "Pet name",
            "type": "integer",
            "location": "query",
            "required": False,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    fields = response.json()["error"]["params"]["fields"]
    assert {"body.type", "body.location", "body.required"} <= set(fields)


@pytest.mark.asyncio
async def test_null_guidance_deletes_the_parameter_override(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]
    endpoint = f"/api/admin/tools/{tool_id}/parameters/name"
    await client.put(
        endpoint,
        json={"description": "Pet name", "example": "Fido"},
        headers={"X-CSRF-Token": csrf},
    )

    deleted = await client.put(
        endpoint,
        json={"description": "   ", "example": None},
        headers={"X-CSRF-Token": csrf},
    )

    assert deleted.status_code == 200
    assert deleted.json()["input_schema"]["properties"]["name"] == {"type": "string"}


@pytest.mark.asyncio
async def test_skill_editors_receive_effective_tool_parameter_guidance(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    tool_id = imported.json()["tools"][0]["id"]
    await client.patch(
        f"/api/admin/tools/{tool_id}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    await client.put(
        f"/api/admin/tools/{tool_id}/parameters/name",
        json={"description": "Pet name", "example": "Fido"},
        headers={"X-CSRF-Token": csrf},
    )

    eligible = await client.get("/api/admin/skills/eligible-tools")
    created = await client.post(
        "/api/admin/skills",
        json={
            "name": "Pet helper",
            "description": None,
            "system_prompt": "Help with pets.",
            "tool_ids": [tool_id],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert eligible.status_code == 200
    assert eligible.json()[0]["input_schema"]["properties"]["name"]["example"] == "Fido"
    assert created.status_code == 201
    assert created.json()["tools"][0]["input_schema"] == eligible.json()[0]["input_schema"]


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
    source_id = imported.json()["source"]["id"]

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
    disable_source = await client.patch(
        f"/api/admin/sources/{source_id}/enabled",
        json={"enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    delete_source = await client.delete(
        f"/api/admin/sources/{source_id}", headers={"X-CSRF-Token": csrf}
    )

    assert enabled.status_code == 200
    assert configured.status_code == 200
    assert disable.status_code == 409
    assert disable.json()["error"]["code"] == "tools.login_tool_conflict"
    assert delete.status_code == 409
    assert disable_source.status_code == 409
    assert delete_source.status_code == 409


@pytest.mark.asyncio
async def test_api_source_can_be_edited_disabled_and_deleted(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    source_id = imported.json()["source"]["id"]

    edited = await client.put(
        f"/api/admin/sources/{source_id}",
        json={
            "name": "Renamed API",
            "base_url": "https://renamed.example.test/api",
            "allow_private_networks": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    disabled = await client.patch(
        f"/api/admin/sources/{source_id}/enabled",
        json={"enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    deleted = await client.delete(
        f"/api/admin/sources/{source_id}", headers={"X-CSRF-Token": csrf}
    )
    sources = await client.get("/api/admin/sources")
    tools = await client.get("/api/admin/tools")

    assert edited.status_code == 200
    assert edited.json()["name"] == "Renamed API"
    assert edited.json()["allow_private_networks"] is True
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert deleted.status_code == 204
    assert sources.json() == []
    assert tools.json() == []


@pytest.mark.asyncio
async def test_api_source_file_refresh_updates_only_changed_tools(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    source_id = imported.json()["source"]["id"]
    tool_id = imported.json()["tools"][0]["id"]
    await client.patch(
        f"/api/admin/tools/{tool_id}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    document = json.loads(import_payload()["document"])
    document["paths"]["/pets"]["post"]["parameters"].append(
        {"name": "limit", "in": "query", "schema": {"type": "integer"}}
    )
    document["paths"]["/health"] = {
        "get": {
            "operationId": "healthCheck",
            "responses": {"200": {"description": "Healthy"}},
        }
    }
    raw = json.dumps(document).encode()

    refreshed = await client.post(
        f"/api/admin/sources/{source_id}/refresh-file",
        files={"document": ("openapi.json", raw, "application/json")},
        headers={"X-CSRF-Token": csrf},
    )
    repeated = await client.post(
        f"/api/admin/sources/{source_id}/refresh-file",
        files={"document": ("openapi.json", raw, "application/json")},
        headers={"X-CSRF-Token": csrf},
    )
    tools = (await client.get("/api/admin/tools")).json()
    updated_tool = next(tool for tool in tools if tool["name"] == "createPet")

    assert refreshed.status_code == 200
    assert refreshed.json() == {"created": 1, "updated": 1, "unchanged": 1}
    assert repeated.json() == {"created": 0, "updated": 0, "unchanged": 3}
    assert updated_tool["id"] == tool_id
    assert updated_tool["enabled"] is True
    assert "limit" in updated_tool["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_source_refresh_preserves_and_reconciles_parameter_guidance(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import",
        json=import_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    source_id = imported.json()["source"]["id"]
    tool_id = imported.json()["tools"][0]["id"]
    await client.put(
        f"/api/admin/tools/{tool_id}/parameters/trace",
        json={"description": "Request trace identifier", "example": "trace-123"},
        headers={"X-CSRF-Token": csrf},
    )
    document = json.loads(import_payload()["document"])
    document["paths"]["/pets"]["post"]["parameters"].append(
        {"name": "limit", "in": "query", "schema": {"type": "integer"}}
    )

    preserved_refresh = await client.post(
        f"/api/admin/sources/{source_id}/refresh-file",
        files={
            "document": ("openapi.json", json.dumps(document).encode(), "application/json")
        },
        headers={"X-CSRF-Token": csrf},
    )
    listed = await client.get("/api/admin/tools")
    preserved_tool = next(item for item in listed.json() if item["id"] == tool_id)

    document["paths"]["/pets"]["post"]["parameters"] = [
        parameter
        for parameter in document["paths"]["/pets"]["post"]["parameters"]
        if parameter["name"] != "trace"
    ]
    removed_refresh = await client.post(
        f"/api/admin/sources/{source_id}/refresh-file",
        files={
            "document": ("openapi.json", json.dumps(document).encode(), "application/json")
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert preserved_refresh.status_code == 200
    assert preserved_tool["input_schema"]["properties"]["trace"] == {
        "type": "string",
        "description": "Request trace identifier",
        "example": "trace-123",
    }
    assert removed_refresh.status_code == 200
    with db_session_factory() as session:
        override = session.scalar(
            select(ToolParameterOverride).where(
                ToolParameterOverride.tool_id == tool_id,
                ToolParameterOverride.argument_name == "trace",
            )
        )
        assert override is None


@pytest.mark.asyncio
async def test_url_source_remembers_document_url_and_refreshes(
    client: httpx.AsyncClient, monkeypatch
) -> None:
    async def fetch_document(_url: str, _allow_private: bool) -> bytes:
        return FIXTURE.read_bytes()

    monkeypatch.setattr(admin_tools, "_fetch_openapi_document", fetch_document)
    csrf = await admin_login(client)
    imported = await client.post(
        "/api/admin/sources/import-url",
        json={
            "name": "Remote API",
            "url": "http://localhost:48080/v2/api-docs",
            "base_url": "http://localhost:48080",
            "allow_private_networks": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    source = imported.json()["source"]

    refreshed = await client.post(
        f"/api/admin/sources/{source['id']}/refresh",
        headers={"X-CSRF-Token": csrf},
    )

    assert source["document_url"] == "http://localhost:48080/v2/api-docs"
    assert refreshed.status_code == 200
    assert refreshed.json() == {"created": 0, "updated": 0, "unchanged": 1}


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
