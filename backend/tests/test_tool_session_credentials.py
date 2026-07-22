import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, text

from chat4openapi.api.tool_sessions import (
    TOOL_SESSION_COOKIE,
    get_tool_executor,
    get_tool_secret_cipher,
    get_tool_session_service,
)
from chat4openapi.models import (
    Agent,
    AgentApiKey,
    ApiSource,
    ApiSourceOAuthConfig,
    ToolSessionCredential,
    ToolUserSession,
    Tool,
    GlobalToolAuthConfig,
)
from chat4openapi.security.agent_keys import AgentKeyContext
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.service import (
    ToolSessionNotFound,
    ToolSessionService,
)
from chat4openapi.tool_sessions.credentials import CredentialValidationError
from chat4openapi.tools.executor import RequestAuth, ToolExecutionResult
from chat4openapi.tools.executor import ToolExecutor


class UnusedExecutor:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("credential injection must not call an upstream Tool")


class RecordingInvokeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, tool, source, arguments, auth):
        self.calls.append((tool.id, source.id, arguments, auth))
        return ToolExecutionResult(200, {"ok": True}, "application/json")


def _jwt(exp: datetime) -> str:
    def encoded(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    epoch = int(exp.replace(tzinfo=UTC).timestamp()) if exp.tzinfo is None else int(exp.timestamp())
    return f"{encoded({'alg': 'none'})}.{encoded({'exp': epoch})}.unsigned"


def _seed_owner(factory, *, second: bool = False):
    secret = "c4o_test_agent_key_000000000000000000000000"
    with factory() as session:
        first = Agent(
            name="First",
            enabled=True,
            is_default=True,
            system_prompt="First",
            mode="react",
            max_iterations=8,
        )
        session.add(first)
        session.flush()
        key = AgentApiKey(
            agent_id=first.id,
            label="test",
            key_prefix=secret[:12],
            key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        )
        session.add(key)
        source = ApiSource(
            name="Protected",
            source_type="openapi",
            base_url="https://api.test",
            spec_snapshot=json.dumps(
                {
                    "openapi": "3.1.0",
                    "components": {
                        "securitySchemes": {
                            "bearer": {"type": "http", "scheme": "bearer"},
                            "tenant": {
                                "type": "apiKey",
                                "in": "header",
                                "name": "X-Tenant-Token",
                            },
                            "session": {
                                "type": "apiKey",
                                "in": "cookie",
                                "name": "session_id",
                            },
                        }
                    },
                }
            ),
        )
        session.add(source)
        if second:
            other = Agent(
                name="Second",
                enabled=True,
                is_default=False,
                system_prompt="Second",
                mode="react",
                max_iterations=8,
            )
            session.add(other)
            session.flush()
        session.commit()
        return secret, first.id, key.id, source.id, other.id if second else None


def _context(session, agent_id: int, key_id: int) -> AgentKeyContext:
    agent = session.get(Agent, agent_id)
    key = session.get(AgentApiKey, key_id)
    assert agent is not None and key is not None
    return AgentKeyContext(agent=agent, api_key=key, db=session)


@pytest.mark.asyncio
async def test_injected_credentials_are_encrypted_normalized_and_secret_free(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        service = ToolSessionService(session, cipher, UnusedExecutor())
        created = await service.create_injected(
            _context(session, agent_id, key_id),
            {
                source_id: {
                    "headers": {"authorization": "Bearer injected-secret"},
                    "cookies": {"SESSION_ID": "cookie-secret"},
                }
            },
            datetime.now(UTC) + timedelta(hours=2),
        )

        row = session.scalar(select(ToolUserSession))
        credential = session.scalar(select(ToolSessionCredential))
        assert row is not None and credential is not None
        assert row.agent_id == agent_id
        assert row.agent_key_id == key_id
        assert row.admin_session_id is None
        assert row.status == "ready"
        assert row.token_hash != created.token
        assert b"injected-secret" not in credential.encrypted_credentials
        assert b"cookie-secret" not in credential.encrypted_credentials
        assert created.status == "ready"
        assert not hasattr(created, "credentials")

        resolved = await service.resolve(created.token, agent_id, key_id, source_id)
        assert resolved.auth == RequestAuth(
            headers={"Authorization": "Bearer injected-secret"},
            cookies={"session_id": "cookie-secret"},
        )


@pytest.mark.asyncio
async def test_cross_agent_key_and_source_resolution_is_rejected(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id, other_agent_id = _seed_owner(
        db_session_factory, second=True
    )
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        other_source = ApiSource(
            name="Other", source_type="openapi", base_url="https://other.test"
        )
        session.add(other_source)
        session.flush()
        service = ToolSessionService(session, cipher, UnusedExecutor())
        created = await service.create_injected(
            _context(session, agent_id, key_id),
            {source_id: {"headers": {"Authorization": "Bearer secret"}}},
            None,
        )

        for binding in (
            (other_agent_id, key_id, source_id),
            (agent_id, key_id + 999, source_id),
            (agent_id, key_id, other_source.id),
        ):
            with pytest.raises(ToolSessionNotFound):
                await service.resolve(created.token, *binding)


@pytest.mark.asyncio
async def test_agent_key_revocation_immediately_invalidates_injected_session(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        service = ToolSessionService(session, cipher, UnusedExecutor())
        created = await service.create_injected(
            _context(session, agent_id, key_id),
            {source_id: {"headers": {"Authorization": "Bearer secret"}}},
            None,
        )
        key = session.get(AgentApiKey, key_id)
        assert key is not None
        key.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

        with pytest.raises(ToolSessionNotFound):
            await service.resolve(created.token, agent_id, key_id, source_id)


@pytest.mark.asyncio
async def test_unverified_jwt_exp_only_caps_session_expiry(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    now = datetime.now(UTC).replace(tzinfo=None)
    jwt_expiry = now + timedelta(minutes=20)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        service = ToolSessionService(session, cipher, UnusedExecutor(), now=lambda: now)
        created = await service.create_injected(
            _context(session, agent_id, key_id),
            {source_id: {"headers": {"Authorization": f"Bearer {_jwt(jwt_expiry)}"}}},
            now + timedelta(hours=5),
        )

        assert created.absolute_expires_at == jwt_expiry.replace(microsecond=0)
        resolved = await service.resolve(created.token, agent_id, key_id, source_id)
        assert resolved.auth.headers["Authorization"].startswith("Bearer ey")


@pytest.mark.asyncio
async def test_injected_header_must_be_allow_listed(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher

    response = await client.post(
        "/api/tool-sessions/credentials",
        headers={"Authorization": f"Bearer {secret}"},
        json={"api_source_id": source_id, "headers": {"Host": "evil.example"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_credentials.field_not_allowed"
    assert "evil.example" not in response.text


@pytest.mark.asyncio
async def test_injected_header_value_cannot_contain_transport_controls(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(
        Fernet.generate_key()
    )

    response = await client.post(
        "/api/tool-sessions/credentials",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "api_source_id": source_id,
            "headers": {"X-Tenant-Token": "safe\r\nHost: evil.example"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_credentials.field_not_allowed"
    assert "evil.example" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_value", ["", "has space", 'has\"quote', "has,comma", "has;semicolon", r"has\slash", "has\x7fctl"]
)
async def test_injected_cookie_value_must_be_rfc6265_safe(
    client: httpx.AsyncClient, app, db_session_factory, unsafe_value: str
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(
        Fernet.generate_key()
    )

    response = await client.post(
        "/api/tool-sessions/credentials",
        headers={"Authorization": f"Bearer {secret}"},
        json={"api_source_id": source_id, "cookies": {"session_id": unsafe_value}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_credentials.field_not_allowed"


@pytest.mark.asyncio
async def test_safe_injected_cookie_reaches_transport_as_one_cookie_header() -> None:
    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers["Cookie"])
        return httpx.Response(200, json={"ok": True})

    source = ApiSource(
        id=1,
        name="Cookie API",
        source_type="openapi",
        base_url="https://api.test",
        allow_private_networks=True,
    )
    tool = Tool(
        id=1,
        api_source_id=1,
        operation_key="GET /me",
        name="get_me",
        input_schema={"type": "object"},
        execution_schema={"method": "GET", "path": "/me", "parameters": []},
    )
    executor = ToolExecutor(
        transport=httpx.MockTransport(handler),
        network_validator=lambda *_args: _completed(),
    )

    await executor.execute(
        tool, source, {}, RequestAuth(cookies={"session_id": "safe-token_123.~"})
    )

    assert captured == ["session_id=safe-token_123.~"]


async def _completed() -> None:
    return None


@pytest.mark.asyncio
async def test_legacy_login_allowlist_does_not_authorize_an_unrelated_source(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, login_source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        login = Tool(
            api_source_id=login_source_id,
            operation_key="POST /login",
            name="login",
            input_schema={"type": "object"},
            execution_schema={"method": "POST", "path": "/login", "parameters": []},
        )
        unrelated = ApiSource(
            name="Unrelated", source_type="openapi", base_url="https://unrelated.test"
        )
        session.add_all([login, unrelated])
        session.flush()
        session.add(
            GlobalToolAuthConfig(
                id=1,
                enabled=True,
                login_tool_id=login.id,
                auth_type="bearer",
                auth_name="Authorization",
            )
        )
        session.commit()
        service = ToolSessionService(session, cipher, UnusedExecutor())

        with pytest.raises(CredentialValidationError) as exc_info:
            await service.create_injected(
                _context(session, agent_id, key_id),
                {unrelated.id: {"headers": {"Authorization": "Bearer leaked"}}},
                None,
            )

        assert exc_info.value.code == "tool_credentials.field_not_allowed"


@pytest.mark.asyncio
async def test_explicit_allowlist_cannot_make_an_unsafe_cookie_name_valid(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    with db_session_factory() as session:
        source = session.get(ApiSource, source_id)
        assert source is not None
        source.spec_snapshot = json.dumps(
            {
                "openapi": "3.1.0",
                "x-chat4openapi-credential-allowlist": {"cookies": ["bad;name"]},
            }
        )
        session.commit()
        service = ToolSessionService(
            session, SecretCipher(Fernet.generate_key()), UnusedExecutor()
        )

        with pytest.raises(CredentialValidationError):
            await service.create_injected(
                _context(session, agent_id, key_id),
                {source_id: {"cookies": {"bad;name": "safe-value"}}},
                None,
            )


@pytest.mark.asyncio
async def test_programmatic_injection_response_contains_token_but_no_secrets(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    test_cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: test_cipher

    response = await client.post(
        "/api/tool-sessions/credentials",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "api_source_id": source_id,
            "headers": {"Authorization": "Bearer never-return-me"},
            "cookies": {"session_id": "cookie-never-return-me"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tool_session_id"]
    assert body["status"] == "ready"
    assert body["api_source_ids"] == [source_id]
    assert "never-return-me" not in response.text
    with db_session_factory() as session:
        row = session.scalar(select(ToolUserSession))
        assert row is not None
        assert (row.agent_id, row.agent_key_id) == (agent_id, key_id)


@pytest.mark.asyncio
async def test_programmatic_status_and_revoke_enforce_the_creating_key(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    headers = {"Authorization": f"Bearer {secret}"}
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers=headers,
        json={
            "api_source_id": source_id,
            "headers": {"Authorization": "Bearer never-return-me"},
        },
    )
    token = created.json()["tool_session_id"]

    status = await client.get(f"/api/tool-sessions/{token}", headers=headers)
    revoked = await client.delete(f"/api/tool-sessions/{token}", headers=headers)
    after = await client.get(f"/api/tool-sessions/{token}", headers=headers)

    assert status.status_code == 200
    assert status.json()["status"] == "ready"
    assert status.json()["api_source_ids"] == [source_id]
    assert "never-return-me" not in status.text
    assert revoked.status_code == 204
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "tool_reauthorization_required"


@pytest.mark.asyncio
async def test_programmatic_logout_replay_is_idempotent_and_keeps_secrets_erased(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    headers = {"Authorization": f"Bearer {secret}"}
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers=headers,
        json={
            "api_source_id": source_id,
            "headers": {"Authorization": "Bearer erase-me"},
        },
    )
    token = created.json()["tool_session_id"]

    first = await client.delete(f"/v1/tool-sessions/{token}", headers=headers)
    second = await client.delete(f"/v1/tool-sessions/{token}", headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    with db_session_factory() as session:
        row = session.scalar(select(ToolUserSession))
        credential = session.scalar(select(ToolSessionCredential))
        assert row is not None and credential is not None
        assert row.status == "revoked"
        assert row.encrypted_login_data is None
        assert row.encrypted_auth_data is None
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}
        assert b"erase-me" not in credential.encrypted_credentials


@pytest.mark.asyncio
async def test_programmatic_logout_hides_cross_owner_sessions(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    first_secret, agent_id, _key_id, source_id, other_agent_id = _seed_owner(
        db_session_factory, second=True
    )
    other_secret = "c4o_other_agent_key_000000000000000000000"
    with db_session_factory() as session:
        session.add(
            AgentApiKey(
                agent_id=other_agent_id,
                label="other",
                key_prefix=other_secret[:12],
                key_hash=hashlib.sha256(other_secret.encode()).hexdigest(),
            )
        )
        session.commit()
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers={"Authorization": f"Bearer {first_secret}"},
        json={"api_source_id": source_id, "headers": {"Authorization": "Bearer safe"}},
    )
    token = created.json()["tool_session_id"]

    hidden = await client.delete(
        f"/v1/tool-sessions/{token}",
        headers={"Authorization": f"Bearer {other_secret}"},
    )

    assert hidden.status_code == 204
    with db_session_factory() as session:
        row = session.scalar(select(ToolUserSession))
        assert row is not None
        assert row.agent_id == agent_id
        assert row.status == "ready"


@pytest.mark.asyncio
async def test_browser_logout_replay_clears_a_stale_cookie_idempotently(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    setup = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "admin123", "locale": "en-US"},
    )
    assert setup.status_code == 201
    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    csrf = login.json()["csrf_token"]
    cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers={"X-CSRF-Token": csrf},
        json={
            "agent_id": agent_id,
            "api_source_id": source_id,
            "headers": {"Authorization": "Bearer erase-browser"},
        },
    )
    token = created.json()["tool_session_id"]
    headers = {"X-CSRF-Token": csrf}
    client.cookies.set(TOOL_SESSION_COOKIE, token)
    first = await client.post("/api/tool-session/logout", headers=headers)
    client.cookies.set(TOOL_SESSION_COOKIE, token)
    second = await client.post("/api/tool-session/logout", headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    assert TOOL_SESSION_COOKIE in first.headers["set-cookie"]
    assert "Max-Age=0" in first.headers["set-cookie"]
    assert TOOL_SESSION_COOKIE in second.headers["set-cookie"]
    assert "Max-Age=0" in second.headers["set-cookie"]
    with db_session_factory() as session:
        credential = session.scalar(select(ToolSessionCredential))
        assert credential is not None
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}


@pytest.mark.asyncio
async def test_programmatic_logout_does_not_swallow_unexpected_service_errors(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, _source_id, _ = _seed_owner(db_session_factory)

    class ExplodingService:
        def binding_for_context(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    app.dependency_overrides[get_tool_session_service] = lambda: ExplodingService()

    with pytest.raises(RuntimeError, match="database unavailable"):
        await client.delete(
            "/v1/tool-sessions/opaque-token",
            headers={"Authorization": f"Bearer {secret}"},
        )


@pytest.mark.asyncio
async def test_admin_cookie_tool_session_mutations_require_csrf(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    with db_session_factory() as session:
        tool = Tool(
            api_source_id=source_id,
            operation_key="GET /me",
            name="get_me",
            input_schema={"type": "object"},
            execution_schema={"method": "GET", "path": "/me", "parameters": []},
            enabled=True,
        )
        session.add(tool)
        session.commit()
        tool_id = tool.id
    setup = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "admin123", "locale": "en-US"},
    )
    assert setup.status_code == 201
    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    csrf_cipher = SecretCipher(Fernet.generate_key())
    app.dependency_overrides[get_tool_secret_cipher] = lambda: csrf_cipher
    payload = {
        "agent_id": agent_id,
        "api_source_id": source_id,
        "headers": {"Authorization": "Bearer browser-secret"},
    }

    missing_create = await client.post("/api/tool-sessions/credentials", json=payload)
    created = await client.post(
        "/api/tool-sessions/credentials",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    token = created.json()["tool_session_id"]
    missing_invoke = await client.post(
        f"/api/tools/{tool_id}/invoke",
        json={"arguments": {}, "tool_session_id": token},
    )
    missing_revoke = await client.delete(f"/api/tool-sessions/{token}")
    revoked = await client.delete(
        f"/api/tool-sessions/{token}", headers={"X-CSRF-Token": csrf}
    )

    for response in (missing_create, missing_invoke, missing_revoke):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "auth.csrf_invalid"
    assert revoked.status_code == 204


def _seed_oauth_tool(factory, source_id: int, cipher: SecretCipher) -> int:
    with factory() as session:
        tool = Tool(
            api_source_id=source_id,
            operation_key="GET /protected",
            name="protected_tool",
            input_schema={"type": "object"},
            execution_schema={"method": "GET", "path": "/protected", "parameters": []},
            enabled=True,
        )
        session.add(tool)
        session.flush()
        session.add(
            ApiSourceOAuthConfig(
                api_source_id=source_id,
                encrypted_config=cipher.encrypt_json({"client_secret": "never-return"}),
                enabled=True,
            )
        )
        session.commit()
        return tool.id


@pytest.mark.asyncio
async def test_direct_oauth_tool_requires_session_before_upstream(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    tool_id = _seed_oauth_tool(db_session_factory, source_id, cipher)
    executor = RecordingInvokeExecutor()
    app.dependency_overrides[get_tool_executor] = lambda: executor

    response = await client.post(
        f"/api/tools/{tool_id}/invoke",
        headers={"Authorization": f"Bearer {secret}"},
        json={"arguments": {}},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "tool_session.required"
    assert executor.calls == []
    assert "never-return" not in response.text


@pytest.mark.asyncio
async def test_direct_oauth_tool_accepts_valid_bound_session(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    tool_id = _seed_oauth_tool(db_session_factory, source_id, cipher)
    executor = RecordingInvokeExecutor()
    app.dependency_overrides[get_tool_executor] = lambda: executor
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    headers = {"Authorization": f"Bearer {secret}"}
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers=headers,
        json={"api_source_id": source_id, "headers": {"Authorization": "Bearer safe"}},
    )

    response = await client.post(
        f"/api/tools/{tool_id}/invoke",
        headers=headers,
        json={"arguments": {}, "tool_session_id": created.json()["tool_session_id"]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"ok": True}
    assert len(executor.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("session_state", ["expired", "revoked", "rejected"])
async def test_direct_oauth_tool_maps_invalid_bound_session_to_reauthorization(
    client: httpx.AsyncClient, app, db_session_factory, session_state: str
) -> None:
    secret, _agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    tool_id = _seed_oauth_tool(db_session_factory, source_id, cipher)
    executor = RecordingInvokeExecutor()
    app.dependency_overrides[get_tool_executor] = lambda: executor
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    headers = {"Authorization": f"Bearer {secret}"}
    created = await client.post(
        "/api/tool-sessions/credentials",
        headers=headers,
        json={"api_source_id": source_id, "headers": {"Authorization": "Bearer safe"}},
    )
    token = created.json()["tool_session_id"]
    with db_session_factory() as session:
        row = session.scalar(select(ToolUserSession))
        credential = session.scalar(select(ToolSessionCredential))
        assert row is not None and credential is not None
        if session_state == "expired":
            row.idle_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        elif session_state == "revoked":
            row.status = "revoked"
            row.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            credential.status = "failed"
        session.commit()

    response = await client.post(
        f"/api/tools/{tool_id}/invoke",
        headers=headers,
        json={"arguments": {}, "tool_session_id": token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "tool_reauthorization_required"
    assert executor.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source_state", ["missing", "disabled", "deleted"])
@pytest.mark.parametrize("with_session", [False, True])
@pytest.mark.parametrize("owner_kind", ["agent_key", "admin"])
async def test_direct_invoke_rejects_unavailable_source_in_every_session_branch(
    client: httpx.AsyncClient,
    app,
    db_session_factory,
    source_state: str,
    with_session: bool,
    owner_kind: str,
) -> None:
    secret, agent_id, _key_id, source_id, _ = _seed_owner(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    tool_id = _seed_oauth_tool(db_session_factory, source_id, cipher)
    executor = RecordingInvokeExecutor()
    app.dependency_overrides[get_tool_executor] = lambda: executor
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    if owner_kind == "agent_key":
        headers = {"Authorization": f"Bearer {secret}"}
    else:
        setup = await client.post(
            "/api/setup",
            json={"username": "admin", "password": "admin123", "locale": "en-US"},
        )
        assert setup.status_code == 201
        login = await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    token = None
    if with_session:
        created = await client.post(
            "/api/tool-sessions/credentials",
            headers=headers,
            json={
                "agent_id": agent_id,
                "api_source_id": source_id,
                "headers": {"Authorization": "Bearer safe"},
            },
        )
        token = created.json()["tool_session_id"]
    with db_session_factory() as session:
        source = session.get(ApiSource, source_id)
        assert source is not None
        if source_state == "missing":
            session.execute(text("PRAGMA foreign_keys=OFF"))
            session.execute(delete(ApiSource).where(ApiSource.id == source_id))
        elif source_state == "disabled":
            source.enabled = False
        else:
            source.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

    response = await client.post(
        f"/api/tools/{tool_id}/invoke",
        headers=headers,
        json={"arguments": {}, **({"tool_session_id": token} if token else {})},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tools.source_not_found"
    assert executor.calls == []
