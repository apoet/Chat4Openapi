from datetime import UTC, datetime, timedelta
import base64
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import (
    Agent,
    AgentApiKey,
    ApiSource,
    GlobalToolAuthConfig,
    Tool,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.agent_keys import AgentKeyContext
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.auth_mapping import build_request_auth, extract_json_path
from chat4openapi.tool_sessions.service import (
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionService,
)
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.executor import RequestAuth, ToolExecutionResult


class FakeExecutor:
    def __init__(self) -> None:
        self.login_calls: list[str] = []
        self.protected_calls = 0
        self.fail_protected_once = False

    async def execute(self, tool, _source, arguments, auth):
        if tool.name == "login":
            username = arguments["user"]
            self.login_calls.append(username)
            return ToolExecutionResult(
                200,
                {
                    "data": {
                        "access_token": f"{username}-token-{len(self.login_calls)}",
                        "expires_in": 3600,
                    }
                },
                "application/json",
            )
        self.protected_calls += 1
        if self.fail_protected_once and self.protected_calls == 1:
            raise ToolExecutionError(
                "upstream_error", "unauthorized", status_code=401, details={"error": "expired"}
            )
        return ToolExecutionResult(200, {"auth": auth.headers["Authorization"]}, "application/json")


def configured_runtime(
    factory: sessionmaker[Session],
) -> tuple[Session, Tool, Tool, AgentKeyContext]:
    session = factory()
    agent = Agent(
        name="Agent",
        enabled=True,
        is_default=True,
        system_prompt="Agent",
        mode="react",
        max_iterations=8,
    )
    session.add(agent)
    session.flush()
    key = AgentApiKey(
        agent_id=agent.id,
        label="test",
        key_prefix="c4o_test_key",
        key_hash="a" * 64,
    )
    session.add(key)
    source = ApiSource(name="API", source_type="openapi", base_url="https://api.test")
    session.add(source)
    session.flush()
    login = Tool(
        api_source_id=source.id,
        operation_key="POST /login",
        name="login",
        input_schema={"type": "object"},
        execution_schema={"method": "POST", "path": "/login", "parameters": []},
        enabled=True,
    )
    protected = Tool(
        api_source_id=source.id,
        operation_key="GET /me",
        name="get_me",
        input_schema={"type": "object"},
        execution_schema={"method": "GET", "path": "/me", "parameters": []},
        enabled=True,
    )
    session.add_all([login, protected])
    session.flush()
    session.add(
        GlobalToolAuthConfig(
            id=1,
            enabled=True,
            login_tool_id=login.id,
            username_field="user",
            password_field="pass",
            token_json_path="$.data.access_token",
            expires_json_path="$.data.expires_in",
            auth_type="bearer",
            auth_name="Authorization",
            auth_prefix="Bearer",
            idle_minutes=30,
            absolute_hours=8,
        )
    )
    session.commit()
    return session, login, protected, AgentKeyContext(agent=agent, api_key=key, db=session)


def cipher() -> SecretCipher:
    return SecretCipher(Fernet.generate_key())


def test_json_path_and_request_auth_mappings() -> None:
    payload = {"data": {"tokens": [{"value": "abc"}]}}
    assert extract_json_path(payload, "$.data.tokens[0].value") == "abc"
    config = GlobalToolAuthConfig(
        id=1,
        token_json_path="$.data.tokens[0].value",
        auth_type="cookie",
        auth_name="sid",
        auth_prefix="",
    )
    assert build_request_auth(config, payload) == RequestAuth(cookies={"sid": "abc"})


@pytest.mark.asyncio
async def test_sessions_are_encrypted_and_identity_isolated(db_session_factory) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)
    executor = FakeExecutor()
    service = ToolSessionService(session, cipher(), executor)

    alice = await service.create("alice", "alice-password", context=context)
    bob = await service.create("bob", "bob-password", context=context)

    rows = session.scalars(select(ToolUserSession).order_by(ToolUserSession.id)).all()
    stored = b" ".join(
        row.encrypted_login_data + b" " + row.encrypted_auth_data for row in rows
    )
    assert b"alice" not in stored
    assert b"alice-password" not in stored
    assert rows[0].token_hash != alice.token
    assert rows[1].token_hash != bob.token
    assert (
        await service.resolve(
            alice.token, context.agent.id, context.api_key.id, protected.api_source_id
        )
    ).auth.headers == {
        "Authorization": "Bearer alice-token-1"
    }
    assert (
        await service.resolve(
            bob.token, context.agent.id, context.api_key.id, protected.api_source_id
        )
    ).auth.headers == {
        "Authorization": "Bearer bob-token-2"
    }
    assert executor.login_calls == ["alice", "bob"]
    session.close()


@pytest.mark.asyncio
async def test_swagger_login_credentials_are_scoped_to_the_login_tool_source(
    db_session_factory,
) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)
    other_source = ApiSource(
        name="Unrelated API", source_type="openapi", base_url="https://other.test"
    )
    session.add(other_source)
    session.commit()
    service = ToolSessionService(session, cipher(), FakeExecutor())

    created = await service.create("alice", "password", context=context)

    credentials = session.scalars(
        select(ToolSessionCredential).order_by(ToolSessionCredential.api_source_id)
    ).all()
    assert created.api_source_ids == (protected.api_source_id,)
    assert [row.api_source_id for row in credentials] == [protected.api_source_id]
    with pytest.raises(ToolSessionNotFound):
        await service.resolve(
            created.token, context.agent.id, context.api_key.id, other_source.id
        )

    await service.resolve(
        created.token,
        context.agent.id,
        context.api_key.id,
        protected.api_source_id,
        force_refresh=True,
    )
    assert session.scalar(select(ToolSessionCredential).where(
        ToolSessionCredential.api_source_id == other_source.id
    )) is None
    session.close()


def _unsigned_jwt(expiry: datetime) -> str:
    def encode(payload: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")

    utc_expiry = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
    return f"{encode({'alg': 'none'})}.{encode({'exp': int(utc_expiry.timestamp())})}.unsigned"


@pytest.mark.asyncio
async def test_swagger_login_jwt_caps_expiry_without_expires_json_path(
    db_session_factory,
) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)
    now = datetime.now(UTC).replace(tzinfo=None)
    jwt_expiry = (now + timedelta(minutes=15)).replace(microsecond=0)
    config = session.get(GlobalToolAuthConfig, 1)
    assert config is not None
    config.expires_json_path = ""
    session.commit()

    class JwtLoginExecutor(FakeExecutor):
        async def execute(self, tool, _source, arguments, auth):
            if tool.name == "login":
                self.login_calls.append(arguments["user"])
                return ToolExecutionResult(
                    200,
                    {"data": {"access_token": _unsigned_jwt(jwt_expiry)}},
                    "application/json",
                )
            return await super().execute(tool, _source, arguments, auth)

    service = ToolSessionService(session, cipher(), JwtLoginExecutor(), now=lambda: now)
    created = await service.create("alice", "password", context=context)
    row = session.scalar(select(ToolUserSession))
    credential = session.scalar(select(ToolSessionCredential))

    assert row is not None and credential is not None
    assert created.absolute_expires_at == jwt_expiry
    assert row.auth_expires_at == jwt_expiry
    assert credential.expires_at == jwt_expiry
    assert (
        await service.resolve(
            created.token, context.agent.id, context.api_key.id, protected.api_source_id
        )
    ).auth.headers["Authorization"].startswith("Bearer ey")
    session.close()


@pytest.mark.asyncio
async def test_idle_absolute_expiry_and_revoke_delete_secrets(db_session_factory) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)
    test_cipher = cipher()
    service = ToolSessionService(session, test_cipher, FakeExecutor())
    expired = await service.create("expired", "password", context=context)
    row = session.scalar(select(ToolUserSession).where(ToolUserSession.token_hash == expired.token_hash))
    assert row is not None
    row.idle_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.commit()

    with pytest.raises(ToolSessionExpired):
        await service.resolve(
            expired.token, context.agent.id, context.api_key.id, protected.api_source_id
        )
    expired_row = session.scalar(
        select(ToolUserSession).where(ToolUserSession.token_hash == expired.token_hash)
    )
    assert expired_row is not None
    assert expired_row.status == "expired"
    assert expired_row.encrypted_login_data is None
    assert expired_row.encrypted_auth_data is None
    expired_credential = session.scalar(
        select(ToolSessionCredential).where(
            ToolSessionCredential.tool_session_id == expired_row.id
        )
    )
    assert expired_credential is not None
    assert expired_credential.status == "expired"
    assert test_cipher.decrypt_json(expired_credential.encrypted_credentials) == {}

    active = await service.create("active", "password", context=context)
    await service.revoke(
        active.token, context.agent.id, context.api_key.id
    )
    with pytest.raises(ToolSessionNotFound):
        await service.resolve(
            active.token, context.agent.id, context.api_key.id, protected.api_source_id
        )
    session.close()


@pytest.mark.asyncio
async def test_refreshes_expired_auth_and_retries_one_unauthorized_call(db_session_factory) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)
    executor = FakeExecutor()
    service = ToolSessionService(session, cipher(), executor)
    created = await service.create("alice", "password", context=context)
    row = session.scalar(select(ToolUserSession).where(ToolUserSession.token_hash == created.token_hash))
    assert row is not None
    row.auth_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.commit()

    resolved = await service.resolve(
        created.token, context.agent.id, context.api_key.id, protected.api_source_id
    )
    assert resolved.auth.headers["Authorization"] == "Bearer alice-token-2"

    executor.fail_protected_once = True
    result = await service.execute(
        protected,
        {},
        created.token,
        agent_id=context.agent.id,
        agent_key_id=context.api_key.id,
    )
    assert result.data == {"auth": "Bearer alice-token-3"}
    assert executor.protected_calls == 2
    assert executor.login_calls == ["alice", "alice", "alice"]
    session.close()


@pytest.mark.asyncio
async def test_forbidden_tool_response_does_not_refresh_or_replay(db_session_factory) -> None:
    session, _, protected, context = configured_runtime(db_session_factory)

    class ForbiddenExecutor(FakeExecutor):
        async def execute(self, tool, source, arguments, auth):
            if tool.name == "login":
                return await super().execute(tool, source, arguments, auth)
            self.protected_calls += 1
            raise ToolExecutionError(
                "upstream_error",
                "forbidden",
                status_code=403,
                details={"error": "forbidden"},
            )

    executor = ForbiddenExecutor()
    service = ToolSessionService(session, cipher(), executor)
    created = await service.create("alice", "password", context=context)

    with pytest.raises(ToolExecutionError) as forbidden:
        await service.execute(
            protected,
            {},
            created.token,
            agent_id=context.agent.id,
            agent_key_id=context.api_key.id,
        )

    assert forbidden.value.status_code == 403
    assert executor.protected_calls == 1
    assert executor.login_calls == ["alice"]
    session.close()
