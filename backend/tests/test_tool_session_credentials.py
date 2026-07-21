import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.models import (
    Agent,
    AgentApiKey,
    ApiSource,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.agent_keys import AgentKeyContext
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.service import (
    ToolSessionNotFound,
    ToolSessionService,
)
from chat4openapi.tools.executor import RequestAuth


class UnusedExecutor:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("credential injection must not call an upstream Tool")


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
async def test_programmatic_injection_response_contains_token_but_no_secrets(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, agent_id, key_id, source_id, _ = _seed_owner(db_session_factory)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: SecretCipher(
        Fernet.generate_key()
    )

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
    assert after.json()["error"]["code"] == "tool_session.required"
