from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chatapi.models import ApiSource, GlobalToolAuthConfig, Tool, ToolUserSession
from chatapi.security.encryption import SecretCipher
from chatapi.tool_sessions.auth_mapping import build_request_auth, extract_json_path
from chatapi.tool_sessions.service import (
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionService,
)
from chatapi.tools.errors import ToolExecutionError
from chatapi.tools.executor import RequestAuth, ToolExecutionResult


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


def configured_runtime(factory: sessionmaker[Session]) -> tuple[Session, Tool, Tool]:
    session = factory()
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
    return session, login, protected


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
    session, _, _ = configured_runtime(db_session_factory)
    executor = FakeExecutor()
    service = ToolSessionService(session, cipher(), executor)

    alice = await service.create("alice", "alice-password")
    bob = await service.create("bob", "bob-password")

    rows = session.scalars(select(ToolUserSession).order_by(ToolUserSession.id)).all()
    stored = b" ".join(
        row.encrypted_login_data + b" " + row.encrypted_auth_data for row in rows
    )
    assert b"alice" not in stored
    assert b"alice-password" not in stored
    assert rows[0].token_hash != alice.token
    assert rows[1].token_hash != bob.token
    assert (await service.resolve(alice.token)).auth.headers == {
        "Authorization": "Bearer alice-token-1"
    }
    assert (await service.resolve(bob.token)).auth.headers == {
        "Authorization": "Bearer bob-token-2"
    }
    assert executor.login_calls == ["alice", "bob"]
    session.close()


@pytest.mark.asyncio
async def test_idle_absolute_expiry_and_revoke_delete_secrets(db_session_factory) -> None:
    session, _, _ = configured_runtime(db_session_factory)
    service = ToolSessionService(session, cipher(), FakeExecutor())
    expired = await service.create("expired", "password")
    row = session.scalar(select(ToolUserSession).where(ToolUserSession.token_hash == expired.token_hash))
    assert row is not None
    row.idle_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.commit()

    with pytest.raises(ToolSessionExpired):
        await service.resolve(expired.token)
    assert session.scalar(
        select(ToolUserSession).where(ToolUserSession.token_hash == expired.token_hash)
    ) is None

    active = await service.create("active", "password")
    await service.revoke(active.token)
    with pytest.raises(ToolSessionNotFound):
        await service.resolve(active.token)
    session.close()


@pytest.mark.asyncio
async def test_refreshes_expired_auth_and_retries_one_unauthorized_call(db_session_factory) -> None:
    session, _, protected = configured_runtime(db_session_factory)
    executor = FakeExecutor()
    service = ToolSessionService(session, cipher(), executor)
    created = await service.create("alice", "password")
    row = session.scalar(select(ToolUserSession).where(ToolUserSession.token_hash == created.token_hash))
    assert row is not None
    row.auth_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.commit()

    resolved = await service.resolve(created.token)
    assert resolved.auth.headers["Authorization"] == "Bearer alice-token-2"

    executor.fail_protected_once = True
    result = await service.execute(protected, {}, created.token)
    assert result.data == {"auth": "Bearer alice-token-3"}
    assert executor.protected_calls == 2
    assert executor.login_calls == ["alice", "alice", "alice"]
    session.close()
