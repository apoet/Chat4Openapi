import asyncio
import base64
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import select
from types import SimpleNamespace

from chat4openapi.api.tool_oauth import (
    get_oauth_network_validator,
    get_oauth_transport,
)
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.models import (
    Agent,
    AgentApiKey,
    AdminSession,
    AdminUser,
    AppSetting,
    ApiSource,
    ApiSourceOAuthConfig,
    ToolOAuthAuthorization,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.agent_keys import AgentKeyContext
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.oauth import (
    OAuthFlowError,
    OAuthPollingTooSoon,
    ToolOAuthService,
)
from chat4openapi.tool_sessions.service import ToolSessionService


class NoopExecutor:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("OAuth must not execute a Tool")


async def allow_network(*_args, **_kwargs) -> None:
    return None


def _seed(factory):
    secret = "c4o_oauth_test_key_000000000000000000000"
    with factory() as db:
        agent = Agent(
            name="OAuth Agent",
            enabled=True,
            is_default=True,
            system_prompt="test",
            mode="react",
            max_iterations=8,
        )
        db.add(agent)
        db.flush()
        key = AgentApiKey(
            agent_id=agent.id,
            label="oauth",
            key_prefix=secret[:12],
            key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        )
        source = ApiSource(
            name="OAuth API",
            source_type="openapi",
            base_url="https://api.example.test",
            allow_private_networks=False,
        )
        db.add_all([key, source])
        db.commit()
        return secret, agent.id, key.id, source.id


def _context(db, agent_id: int, key_id: int) -> AgentKeyContext:
    agent = db.get(Agent, agent_id)
    key = db.get(AgentApiKey, key_id)
    assert agent is not None and key is not None
    return AgentKeyContext(agent=agent, api_key=key, db=db)


def _admin_context(db):
    admin = AdminUser(username="admin", password_hash="unused")
    db.add(admin)
    db.flush()
    admin_session = AdminSession(
        admin_id=admin.id,
        token_hash="a" * 64,
        csrf_hash="b" * 64,
        idle_expires_at=datetime(2026, 7, 23),
        absolute_expires_at=datetime(2026, 7, 24),
    )
    db.add(admin_session)
    db.flush()
    return SimpleNamespace(admin=admin, admin_session=admin_session, db=db)


def _configure(service: ToolOAuthService, source_id: int) -> None:
    service.configure_source(
        source_id,
        {
            "client_id": "public-client",
            "client_secret": "super-secret",
            "authorization_url": "https://issuer.example.test/authorize",
            "token_url": "https://issuer.example.test/token",
            "device_authorization_url": "https://issuer.example.test/device",
            "redirect_uri": "https://app.example.test/api/tool-sessions/oauth/pkce/callback",
            "scopes": ["openid", "profile"],
        },
    )


@pytest.mark.asyncio
async def test_client_credentials_mode_caches_an_encrypted_service_token(
    db_session_factory,
) -> None:
    _secret, _agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "service-access-secret",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        service.configure_source(
            source_id,
            {
                "client_id": "service-client",
                "client_secret": "service-secret",
                "grant_type": "client_credentials",
                "token_endpoint_auth_method": "client_secret_basic",
                "token_url": "https://issuer.example.test/token",
                "scopes": ["projects.read"],
            },
        )

        first = await service.client_credentials_auth(source_id)
        second = await service.client_credentials_auth(source_id)

        assert first.headers == {"Authorization": "Bearer service-access-secret"}
        assert second == first
        assert len(requests) == 1
        assert parse_qs(requests[0].content.decode()) == {
            "grant_type": ["client_credentials"],
            "scope": ["projects.read"],
        }
        assert service.config_summary(source_id)["grant_type"] == "client_credentials"
        row = db.get(ApiSourceOAuthConfig, source_id)
        assert row is not None
        assert b"service-access-secret" not in row.encrypted_config


@pytest.mark.asyncio
async def test_device_flow_encrypts_codes_and_becomes_ready(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-secret",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://issuer.example.test/verify",
                    "verification_uri_complete": "https://issuer.example.test/verify?user_code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_device(_context(db, agent_id, key_id), source_id)
        assert started.status == "pending"
        assert started.user_code == "ABCD-EFGH"
        assert started.verification_uri == "https://issuer.example.test/verify"
        assert started.interval == 5
        flow = db.scalar(select(ToolOAuthAuthorization))
        config = db.get(ApiSourceOAuthConfig, source_id)
        assert flow is not None and config is not None
        assert b"device-secret" not in flow.encrypted_flow_data
        assert b"super-secret" not in config.encrypted_config

        now += timedelta(seconds=5)
        completed = await service.poll_device(
            started.tool_session_id, _context(db, agent_id, key_id)
        )
        assert completed.status == "ready"
        session = db.scalar(select(ToolUserSession))
        credential = db.scalar(select(ToolSessionCredential))
        assert session is not None and credential is not None
        assert (session.agent_id, session.agent_key_id) == (agent_id, key_id)
        assert credential.api_source_id == source_id
        assert b"access-secret" not in credential.encrypted_credentials
        assert b"refresh-secret" not in credential.encrypted_credentials
        assert "device-secret" in requests[-1].content.decode()


@pytest.mark.asyncio
async def test_device_polling_enforces_interval_and_slow_down(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    poll_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 3,
                },
            )
        poll_count += 1
        error = "authorization_pending" if poll_count == 1 else "slow_down"
        return httpx.Response(400, json={"error": error, "debug": "must-not-leak"})

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_device(_context(db, agent_id, key_id), source_id)
        with pytest.raises(OAuthPollingTooSoon):
            await service.poll_device(started.tool_session_id, _context(db, agent_id, key_id))
        now += timedelta(seconds=3)
        pending = await service.poll_device(
            started.tool_session_id, _context(db, agent_id, key_id)
        )
        assert pending.status == "pending"
        now += timedelta(seconds=3)
        slowed = await service.poll_device(
            started.tool_session_id, _context(db, agent_id, key_id)
        )
        assert slowed.status == "pending"
        assert slowed.interval == 8
        assert "must-not-leak" not in str(slowed)
        with pytest.raises(OAuthPollingTooSoon):
            await service.poll_device(started.tool_session_id, _context(db, agent_id, key_id))


@pytest.mark.asyncio
async def test_device_polling_preserves_large_issuer_interval_and_repeated_slow_down(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 600,
                    "interval": 75,
                },
            )
        return httpx.Response(400, json={"error": "slow_down"})

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        assert started.interval == 75

        now += timedelta(seconds=75)
        first = await service.poll_device(started.tool_session_id, context)
        assert first.interval == 80
        now += timedelta(seconds=80)
        second = await service.poll_device(started.tool_session_id, context)
        assert second.interval == 85


@pytest.mark.asyncio
async def test_device_poll_claim_allows_only_one_real_session_to_call_issuer(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    poll_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        poll_requests += 1
        if poll_requests == 1:
            first_entered.set()
            await release_first.wait()
            return httpx.Response(
                200,
                json={"access_token": "winner", "token_type": "Bearer", "expires_in": 30},
            )
        return httpx.Response(400, json={"error": "access_denied"})

    cipher = SecretCipher(Fernet.generate_key())
    transport = httpx.MockTransport(handler)
    with db_session_factory() as setup_db:
        service = ToolOAuthService(
            setup_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_device(_context(setup_db, agent_id, key_id), source_id)
    now += timedelta(seconds=1)

    first_db = db_session_factory()
    second_db = db_session_factory()
    try:
        first_service = ToolOAuthService(
            first_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        second_service = ToolOAuthService(
            second_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        first_task = asyncio.create_task(
            first_service.poll_device(
                started.tool_session_id, _context(first_db, agent_id, key_id)
            )
        )
        await first_entered.wait()
        with pytest.raises(OAuthPollingTooSoon):
            await second_service.poll_device(
                started.tool_session_id, _context(second_db, agent_id, key_id)
            )
        release_first.set()
        assert (await first_task).status == "ready"
        assert poll_requests == 1
        second_db.expire_all()
        flow = second_db.scalar(select(ToolOAuthAuthorization))
        credential = second_db.scalar(select(ToolSessionCredential))
        assert flow is not None and credential is not None
        assert flow.status == "ready"
        assert credential.status == "ready"
    finally:
        release_first.set()
        first_db.close()
        second_db.close()


@pytest.mark.asyncio
async def test_device_poll_reclaims_a_stale_crashed_operation(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    poll_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        poll_requests += 1
        return httpx.Response(400, json={"error": "authorization_pending"})

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        flow.operation_generation = 9
        flow.operation_in_progress = True
        flow.operation_started_at = now
        db.commit()

        now += timedelta(seconds=61)
        pending = await service.poll_device(started.tool_session_id, context)
        assert pending.status == "pending"
        assert poll_requests == 1
        db.refresh(flow)
        assert flow.operation_in_progress is False


@pytest.mark.asyncio
async def test_device_stale_claim_still_waits_for_long_issuer_interval(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    poll_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 600,
                    "interval": 120,
                },
            )
        poll_requests += 1
        return httpx.Response(400, json={"error": "authorization_pending"})

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        flow.operation_generation = 9
        flow.operation_in_progress = True
        flow.operation_started_at = now
        db.commit()

        now += timedelta(seconds=61)
        with pytest.raises(OAuthPollingTooSoon) as too_soon:
            await service.poll_device(started.tool_session_id, context)
        assert too_soon.value.retry_after == 59
        assert poll_requests == 0

        now += timedelta(seconds=59)
        pending = await service.poll_device(started.tool_session_id, context)
        assert pending.status == "pending"
        assert poll_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["network", "json"])
async def test_device_failed_attempt_is_still_throttled(
    db_session_factory, failure_kind: str
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    poll_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 5,
                },
            )
        poll_requests += 1
        if failure_kind == "network":
            raise httpx.ConnectError("issuer detail", request=request)
        return httpx.Response(200, content=b"not-json")

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        now += timedelta(seconds=5)
        with pytest.raises(OAuthFlowError) as failed:
            await service.poll_device(started.tool_session_id, context)
        assert failed.value.code == "oauth.upstream_failed"
        with pytest.raises(OAuthPollingTooSoon):
            await service.poll_device(started.tool_session_id, context)
        assert poll_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [("access_denied", "failed"), ("expired_token", "expired")],
)
async def test_device_terminal_errors_are_redacted(
    db_session_factory, upstream_error: str, expected_status: str
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        return httpx.Response(
            400, json={"error": upstream_error, "error_description": "issuer secret"}
        )

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_device(_context(db, agent_id, key_id), source_id)
        now += timedelta(seconds=1)
        result = await service.poll_device(
            started.tool_session_id, _context(db, agent_id, key_id)
        )
        assert result.status == expected_status
        assert "issuer secret" not in str(result)


@pytest.mark.asyncio
async def test_pkce_uses_s256_and_callback_state_is_one_time(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_request: list[httpx.Request] = []
    validated_urls: list[str] = []

    async def validate_url(url: httpx.URL, _allow_private: bool) -> None:
        validated_urls.append(str(url))

    async def handler(request: httpx.Request) -> httpx.Response:
        token_request.append(request)
        return httpx.Response(
            200,
            json={"access_token": "pkce-access", "token_type": "Bearer", "expires_in": 900},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=validate_url,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _admin_context(db)
        started = await service.start_pkce(context, source_id, agent_id=agent_id)
        query = parse_qs(urlsplit(started.authorization_url).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"] == [started.state]
        assert "code_verifier" not in query
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        flow_data = cipher.decrypt_json(flow.encrypted_flow_data)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(flow_data["code_verifier"].encode()).digest()
        ).rstrip(b"=").decode()
        assert query["code_challenge"] == [expected]
        assert b"code_verifier" not in flow.encrypted_flow_data

        completed = await service.complete_pkce(started.state, "authorization-code")
        assert completed.status == "ready"
        assert completed.tool_session_id
        posted = parse_qs(token_request[0].content.decode())
        assert posted["code_verifier"] == [flow_data["code_verifier"]]
        assert posted["code"] == ["authorization-code"]
        assert posted["state"] == [started.state]
        assert validated_urls == [
            "https://issuer.example.test/authorize",
            "https://issuer.example.test/token",
        ]
        with pytest.raises(OAuthFlowError) as replay:
            await service.complete_pkce(started.state, "authorization-code")
        assert replay.value.code == "oauth.state_invalid"


@pytest.mark.asyncio
async def test_pkce_supports_client_secret_basic(db_session_factory) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "pkce-access", "token_type": "Bearer"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        config = db.get(ApiSourceOAuthConfig, source_id)
        assert config is not None
        decrypted = cipher.decrypt_json(config.encrypted_config)
        decrypted["token_endpoint_auth_method"] = "client_secret_basic"
        config.encrypted_config = cipher.encrypt_json(decrypted)
        db.commit()

        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        await service.complete_pkce(started.state, "authorization-code")

    assert len(token_requests) == 1
    assert token_requests[0].headers["Authorization"].startswith("Basic ")
    posted = parse_qs(token_requests[0].content.decode())
    assert "client_id" not in posted
    assert "client_secret" not in posted


@pytest.mark.asyncio
async def test_pkce_sends_configured_token_headers_and_unwraps_token_data(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "",
                "data": {
                    "access_token": "wrapped-access",
                    "refresh_token": "wrapped-refresh",
                    "token_type": "Bearer",
                    "expires_in": 600,
                },
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        service.configure_source(
            source_id,
            {
                "client_id": "public-client",
                "client_secret": "super-secret",
                "token_endpoint_auth_method": "client_secret_basic",
                "authorization_url": "https://issuer.example.test/authorize",
                "token_url": "https://issuer.example.test/token",
                "redirect_uri": (
                    "https://app.example.test/api/tool-sessions/oauth/pkce/callback"
                ),
                "token_headers": {"tenant-id": "1"},
                "scopes": ["openid"],
            },
        )
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        completed = await service.complete_pkce(
            started.state, "authorization-code"
        )

    assert completed.status == "ready"
    assert len(token_requests) == 1
    assert token_requests[0].headers["tenant-id"] == "1"


@pytest.mark.asyncio
async def test_pkce_logs_wrapped_business_error_returned_with_http_200(
    db_session_factory, monkeypatch
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    warnings: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "chat4openapi.tool_sessions.oauth.logger.warning",
        lambda *args: warnings.append(args),
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 400,
                "msg": "tenant-id header required",
                "data": None,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        with pytest.raises(OAuthFlowError) as failed:
            await service.complete_pkce(
                started.state, "authorization-code"
            )

    assert failed.value.code == "oauth.exchange_failed"
    assert len(warnings) == 1
    assert warnings[0][4] == 400
    assert warnings[0][5] == "tenant-id header required"


@pytest.mark.asyncio
async def test_pkce_auto_retries_post_only_after_basic_authentication_failure(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        if "Authorization" in request.headers:
            return httpx.Response(401, json={"error": "invalid_client"})
        return httpx.Response(
            200,
            json={"access_token": "pkce-access", "token_type": "Bearer"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        await service.complete_pkce(started.state, "authorization-code")

    assert len(token_requests) == 2
    first = parse_qs(token_requests[0].content.decode())
    assert token_requests[0].headers["Authorization"].startswith("Basic ")
    assert "client_id" not in first
    assert "client_secret" not in first
    second = parse_qs(token_requests[1].content.decode())
    assert second["client_id"] == ["public-client"]
    assert second["client_secret"] == ["super-secret"]


@pytest.mark.asyncio
async def test_pkce_auto_prefers_basic_when_post_auth_returns_invalid_request(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        if "Authorization" not in request.headers:
            return httpx.Response(400, json={"error": "invalid_request"})
        return httpx.Response(
            200,
            json={"access_token": "pkce-access", "token_type": "Bearer"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        completed = await service.complete_pkce(
            started.state, "authorization-code"
        )

    assert completed.status == "ready"
    assert len(token_requests) == 1
    assert token_requests[0].headers["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_pkce_none_authentication_sends_only_public_client_id(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "pkce-access", "token_type": "Bearer"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        service.configure_source(
            source_id,
            {
                "client_id": "public-client",
                "token_endpoint_auth_method": "none",
                "authorization_url": "https://issuer.example.test/authorize",
                "token_url": "https://issuer.example.test/token",
                "redirect_uri": (
                    "https://app.example.test/api/tool-sessions/oauth/pkce/callback"
                ),
            },
        )
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        await service.complete_pkce(started.state, "authorization-code")

    assert len(token_requests) == 1
    assert "Authorization" not in token_requests[0].headers
    posted = parse_qs(token_requests[0].content.decode())
    assert posted["client_id"] == ["public-client"]
    assert "client_secret" not in posted


@pytest.mark.asyncio
async def test_pkce_auto_does_not_retry_non_authentication_token_errors(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(400, json={"error": "invalid_grant"})

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        with pytest.raises(OAuthFlowError) as failed:
            await service.complete_pkce(started.state, "authorization-code")

    assert failed.value.code == "oauth.exchange_failed"
    assert len(token_requests) == 1


@pytest.mark.asyncio
async def test_pkce_rejects_mismatched_and_expired_state(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid state must not call token endpoint")

    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            SecretCipher(Fernet.generate_key()),
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        with pytest.raises(OAuthFlowError) as mismatch:
            await service.complete_pkce(started.state + "x", "code")
        assert mismatch.value.code == "oauth.state_invalid"
        now += timedelta(minutes=11)
        with pytest.raises(OAuthFlowError) as expired:
            await service.complete_pkce(started.state, "code")
        assert expired.value.code == "oauth.state_expired"
        expired_flow = db.scalar(select(ToolOAuthAuthorization))
        assert expired_flow is not None
        assert service._cipher.decrypt_json(expired_flow.encrypted_flow_data) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    [
        "source",
        "config",
        "config_decrypt",
        "flow_decrypt",
        "network",
        "json",
        "non2xx",
        "missing_token",
    ],
)
async def test_claimed_pkce_failure_is_redacted_and_erases_all_flow_secrets(
    db_session_factory, failure_kind: str
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)

    async def handler(request: httpx.Request) -> httpx.Response:
        if failure_kind == "network":
            raise httpx.ConnectError("issuer-secret-network-detail", request=request)
        if failure_kind == "json":
            return httpx.Response(200, content=b"issuer-secret-invalid-json")
        if failure_kind == "non2xx":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "issuer-secret"},
            )
        if failure_kind == "missing_token":
            return httpx.Response(200, json={"refresh_token": "issuer-secret"})
        return httpx.Response(
            200,
            json={"access_token": "unused", "token_type": "Bearer"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        if failure_kind == "source":
            source = db.get(ApiSource, source_id)
            assert source is not None
            source.enabled = False
        elif failure_kind == "config":
            config = db.get(ApiSourceOAuthConfig, source_id)
            assert config is not None
            config.enabled = False
        elif failure_kind == "config_decrypt":
            config = db.get(ApiSourceOAuthConfig, source_id)
            assert config is not None
            config.encrypted_config = b"issuer-secret-corrupt-config"
        elif failure_kind == "flow_decrypt":
            flow.encrypted_flow_data = b"issuer-secret-corrupt-flow"
        db.commit()

        with pytest.raises(OAuthFlowError) as failed:
            await service.complete_pkce(started.state, "authorization-code")
        assert failed.value.code == "oauth.exchange_failed"
        assert "issuer-secret" not in str(failed.value)

        db.expire_all()
        failed_flow = db.scalar(select(ToolOAuthAuthorization))
        row = db.scalar(select(ToolUserSession))
        credential = db.scalar(select(ToolSessionCredential))
        assert failed_flow is not None and row is not None and credential is not None
        assert failed_flow.status == "failed"
        assert row.status == "failed"
        assert credential.status == "failed"
        assert cipher.decrypt_json(failed_flow.encrypted_flow_data) == {}
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}


@pytest.mark.asyncio
async def test_claimed_pkce_cancellation_erases_secrets_and_is_re_raised(
    db_session_factory,
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    cancellation = asyncio.CancelledError("cancel-secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise cancellation

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        started = await service.start_pkce(
            _admin_context(db), source_id, agent_id=agent_id
        )

        with pytest.raises(asyncio.CancelledError) as raised:
            await service.complete_pkce(started.state, "authorization-code")
        assert raised.value is cancellation

        db.expire_all()
        flow = db.scalar(select(ToolOAuthAuthorization))
        row = db.scalar(select(ToolUserSession))
        credential = db.scalar(select(ToolSessionCredential))
        assert flow is not None and row is not None and credential is not None
        assert (flow.status, row.status, credential.status) == (
            "failed",
            "failed",
            "failed",
        )
        assert cipher.decrypt_json(flow.encrypted_flow_data) == {}
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}


@pytest.mark.asyncio
async def test_refresh_keeps_owner_and_source_boundary(db_session_factory) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    refresh_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        form = parse_qs(request.content.decode())
        if form.get("grant_type") == ["refresh_token"]:
            refresh_requests += 1
            assert form["refresh_token"] == ["refresh-1"]
            return httpx.Response(
                200,
                json={"access_token": "access-2", "token_type": "Bearer", "expires_in": 60},
            )
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 1,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        now += timedelta(seconds=1)
        authorized = await service.poll_device(started.tool_session_id, context)
        now += timedelta(seconds=2)
        refreshed = await service.refresh(started.tool_session_id, context, source_id)
        assert refreshed.status == "ready"
        assert refreshed.expires_at == authorized.expires_at
        assert refresh_requests == 1
        with pytest.raises(OAuthFlowError):
            await service.refresh(started.tool_session_id, context, source_id + 999)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_boundary", ["status", "idle", "absolute"])
async def test_refresh_checks_session_state_and_expiry_before_network(
    db_session_factory, invalid_boundary: str
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    refresh_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        form = parse_qs(request.content.decode())
        if form.get("grant_type") == ["refresh_token"]:
            refresh_requests += 1
            return httpx.Response(
                200,
                json={"access_token": "must-not-store", "token_type": "Bearer"},
            )
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 60,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(service, source_id)
        context = _context(db, agent_id, key_id)
        started = await service.start_device(context, source_id)
        now += timedelta(seconds=1)
        await service.poll_device(started.tool_session_id, context)
        row = db.scalar(select(ToolUserSession))
        credential = db.scalar(select(ToolSessionCredential))
        assert row is not None and credential is not None
        if invalid_boundary == "status":
            row.status = "failed"
        elif invalid_boundary == "idle":
            row.idle_expires_at = now
        else:
            row.absolute_expires_at = now
        db.commit()

        with pytest.raises(OAuthFlowError) as failed:
            await service.refresh_bound(row, credential)
        expected_code = (
            "oauth.refresh_unavailable"
            if invalid_boundary == "status"
            else "oauth.session_expired"
        )
        assert failed.value.code == expected_code
        assert refresh_requests == 0
        db.refresh(row)
        db.refresh(credential)
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        if invalid_boundary == "status":
            assert (row.status, credential.status, flow.status) == (
                "failed",
                "ready",
                "ready",
            )
            return
        assert (row.status, credential.status, flow.status) == (
            "expired",
            "expired",
            "expired",
        )
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}
        assert cipher.decrypt_json(flow.encrypted_flow_data) == {}


@pytest.mark.asyncio
async def test_refresh_singleflight_preserves_rotating_token_against_late_failure(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    refresh_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_requests
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        form = parse_qs(request.content.decode())
        if form.get("grant_type") != ["refresh_token"]:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "token_type": "Bearer",
                    "expires_in": 1,
                },
            )
        refresh_requests += 1
        if refresh_requests == 1:
            await asyncio.sleep(0.05)
            return httpx.Response(
                200,
                json={
                    "access_token": "access-2",
                    "refresh_token": "refresh-2",
                    "token_type": "Bearer",
                    "expires_in": 60,
                },
            )
        await asyncio.sleep(0.15)
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "stale-token"},
        )

    cipher = SecretCipher(Fernet.generate_key())
    transport = httpx.MockTransport(handler)
    with db_session_factory() as setup_db:
        setup_service = ToolOAuthService(
            setup_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(setup_service, source_id)
        context = _context(setup_db, agent_id, key_id)
        started = await setup_service.start_device(context, source_id)
        now += timedelta(seconds=1)
        await setup_service.poll_device(started.tool_session_id, context)

    first_db = db_session_factory()
    second_db = db_session_factory()
    try:
        first_row = first_db.scalar(select(ToolUserSession))
        first_credential = first_db.scalar(select(ToolSessionCredential))
        second_row = second_db.scalar(select(ToolUserSession))
        second_credential = second_db.scalar(select(ToolSessionCredential))
        assert first_row is not None and first_credential is not None
        assert second_row is not None and second_credential is not None
        first_service = ToolOAuthService(
            first_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        second_service = ToolOAuthService(
            second_db,
            cipher,
            transport=transport,
            network_validator=allow_network,
            now=lambda: now,
        )
        results = await asyncio.gather(
            first_service.refresh_bound(first_row, first_credential),
            second_service.refresh_bound(second_row, second_credential),
            return_exceptions=True,
        )
        assert results == [None, None]
        assert refresh_requests == 1
    finally:
        first_db.close()
        second_db.close()

    with db_session_factory() as verify_db:
        row = verify_db.scalar(select(ToolUserSession))
        flow = verify_db.scalar(select(ToolOAuthAuthorization))
        credential = verify_db.scalar(select(ToolSessionCredential))
        assert row is not None and flow is not None and credential is not None
        assert (row.status, flow.status, credential.status) == ("ready", "ready", "ready")
        stored = cipher.decrypt_json(credential.encrypted_credentials)
        assert stored["headers"] == {"Authorization": "Bearer access-2"}
        assert stored["oauth"]["refresh_token"] == "refresh-2"


@pytest.mark.asyncio
async def test_tool_resolution_refreshes_expired_oauth_without_redirect_or_wait(
    db_session_factory,
) -> None:
    _secret, agent_id, key_id, source_id = _seed(db_session_factory)
    now = datetime(2026, 7, 22, 8, 0, 0)
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "CODE",
                    "verification_uri": "https://issuer.example.test/verify",
                    "expires_in": 60,
                    "interval": 1,
                },
            )
        form = parse_qs(request.content.decode())
        if form.get("grant_type") == ["refresh_token"]:
            return httpx.Response(
                200,
                json={"access_token": "fresh", "token_type": "Bearer", "expires_in": 60},
            )
        return httpx.Response(
            200,
            json={
                "access_token": "old",
                "refresh_token": "refresh",
                "token_type": "Bearer",
                "expires_in": 1,
            },
        )

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        oauth = ToolOAuthService(
            db,
            cipher,
            transport=httpx.MockTransport(handler),
            network_validator=allow_network,
            now=lambda: now,
        )
        _configure(oauth, source_id)
        context = _context(db, agent_id, key_id)
        started = await oauth.start_device(context, source_id)
        now += timedelta(seconds=1)
        await oauth.poll_device(started.tool_session_id, context)
        now += timedelta(seconds=2)

        sessions = ToolSessionService(
            db,
            cipher,
            NoopExecutor(),
            now=lambda: now,
            oauth_refresher=oauth.refresh_bound,
        )
        resolved = await sessions.resolve(
            started.tool_session_id, agent_id, key_id, source_id
        )

        assert resolved.auth.headers == {"Authorization": "Bearer fresh"}
        assert paths == ["/device", "/token", "/token"]


def test_oauth_config_rejects_request_controlled_or_unsafe_urls(db_session_factory) -> None:
    _secret, _agent_id, _key_id, source_id = _seed(db_session_factory)
    with db_session_factory() as db:
        service = ToolOAuthService(db, SecretCipher(Fernet.generate_key()))
        with pytest.raises(OAuthFlowError) as embedded_credentials:
            service.configure_source(
                source_id,
                {
                    "client_id": "client",
                    "token_url": "https://user:pass@issuer.example/token",
                    "device_authorization_url": "https://issuer.example/device",
                },
            )
        assert embedded_credentials.value.code == "oauth.config_invalid"


def test_oauth_migration_roundtrip(tmp_path) -> None:
    database = tmp_path / "oauth.db"
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "0009_tool_sessions")
    command.upgrade(config, "0010_tool_oauth")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    tables = set(sa.inspect(engine).get_table_names())
    assert {"api_source_oauth_configs", "tool_oauth_authorizations"} <= tables
    command.downgrade(config, "0009_tool_sessions")
    tables = set(sa.inspect(engine).get_table_names())
    assert "api_source_oauth_configs" not in tables
    assert "tool_oauth_authorizations" not in tables
    command.upgrade(config, "0010_tool_oauth")
    assert "tool_oauth_authorizations" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_oauth_operation_claim_migration_roundtrip(tmp_path) -> None:
    database = tmp_path / "oauth-claims.db"
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "0010_tool_oauth")
    command.upgrade(config, "0011_oauth_operation_claims")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("tool_oauth_authorizations")
    }
    assert {
        "operation_generation",
        "operation_in_progress",
        "operation_started_at",
    } <= columns
    command.downgrade(config, "0010_tool_oauth")
    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("tool_oauth_authorizations")
    }
    assert "operation_generation" not in columns
    assert "operation_in_progress" not in columns
    assert "operation_started_at" not in columns
    command.upgrade(config, "0011_oauth_operation_claims")
    engine.dispose()


@pytest.mark.asyncio
async def test_device_api_uses_agent_key_and_never_accepts_endpoint_urls(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    secret, _agent_id, _key_id, source_id = _seed(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://issuer.example.test/device"
        return httpx.Response(
            200,
            json={
                "device_code": "api-device-secret",
                "user_code": "API-CODE",
                "verification_uri": "https://issuer.example.test/verify",
                "expires_in": 600,
                "interval": 5,
            },
        )

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(handler)
    app.dependency_overrides[get_oauth_network_validator] = lambda: allow_network
    with db_session_factory() as db:
        _configure(ToolOAuthService(db, cipher), source_id)

    response = await client.post(
        "/api/tool-sessions/oauth/device/start",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "api_source_id": source_id,
            "token_url": "https://attacker.invalid/token",
        },
    )

    assert response.status_code == 422
    clean = await client.post(
        "/api/tool-sessions/oauth/device/start",
        headers={"Authorization": f"Bearer {secret}"},
        json={"api_source_id": source_id},
    )
    assert clean.status_code == 201
    assert clean.json()["status"] == "pending"
    assert clean.json()["user_code"] == "API-CODE"
    assert "api-device-secret" not in clean.text


def test_updating_oauth_config_keeps_an_existing_secret_when_omitted(
    db_session_factory,
) -> None:
    _secret, _agent_id, _key_id, source_id = _seed(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as db:
        service = ToolOAuthService(db, cipher)
        _configure(service, source_id)
        service.configure_source(
            source_id,
            {
                "client_id": "updated-client",
                "client_secret": None,
                "authorization_url": "https://issuer.example.test/authorize",
                "token_url": "https://issuer.example.test/token",
                "scopes": ["openid"],
            },
        )
        row = db.get(ApiSourceOAuthConfig, source_id)
        assert row is not None
        assert cipher.decrypt_json(row.encrypted_config)["client_secret"] == "super-secret"


@pytest.mark.asyncio
async def test_admin_oauth_config_and_pkce_callback_are_secret_free_and_csrf_safe(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    setup = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "admin123", "locale": "en-US"},
    )
    assert setup.status_code == 201
    login = await client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "admin123"}
    )
    csrf = login.json()["csrf_token"]
    settings = await client.put(
        "/api/admin/settings",
        headers={"X-CSRF-Token": csrf},
        json={"base_url": "https://chat.example.test/"},
    )
    assert settings.status_code == 200
    cipher = SecretCipher(Fernet.generate_key())
    posted: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request)
        return httpx.Response(
            200,
            json={"access_token": "callback-secret", "token_type": "Bearer", "expires_in": 600},
        )

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(handler)
    app.dependency_overrides[get_oauth_network_validator] = lambda: allow_network
    config_payload = {
        "enabled": True,
        "client_id": "web-client",
        "client_secret": "client-secret-never-return",
        "token_endpoint_auth_method": "client_secret_basic",
        "token_headers": {"tenant-id": "1"},
        "authorization_url": "https://issuer.example.test/authorize",
        "token_url": "https://issuer.example.test/token",
        "device_authorization_url": "https://issuer.example.test/device",
        "redirect_uri": "https://app.example.test/api/tool-sessions/oauth/pkce/callback",
        "scopes": ["openid"],
    }
    missing_csrf = await client.put(
        f"/api/admin/sources/{source_id}/oauth", json=config_payload
    )
    configured = await client.put(
        f"/api/admin/sources/{source_id}/oauth",
        headers={"X-CSRF-Token": csrf},
        json=config_payload,
    )
    assert missing_csrf.status_code == 403
    assert configured.status_code == 200
    assert configured.json()["has_client_secret"] is True
    assert configured.json()["token_endpoint_auth_method"] == "client_secret_basic"
    assert configured.json()["token_headers"] == {"tenant-id": "1"}
    assert configured.json()["recommended_redirect_uri"] == (
        "https://chat.example.test/api/tool-sessions/oauth/pkce/callback"
    )
    assert configured.json()["effective_redirect_uri"] == config_payload["redirect_uri"]
    assert "client-secret-never-return" not in configured.text

    missing_start_csrf = await client.post(
        "/api/tool-sessions/oauth/pkce/start",
        json={"api_source_id": source_id, "agent_id": agent_id},
    )
    started = await client.post(
        "/api/tool-sessions/oauth/pkce/start",
        headers={"X-CSRF-Token": csrf},
        json={"api_source_id": source_id, "agent_id": agent_id},
    )
    assert missing_start_csrf.status_code == 403
    assert started.status_code == 201
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    callback = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state, "code": "api-code"},
    )
    assert callback.status_code == 200
    assert callback.json()["status"] == "ready"
    assert "callback-secret" not in callback.text
    assert "chat4openapi_tool_session=" in callback.headers["set-cookie"]
    replay = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state, "code": "api-code"},
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "oauth.state_invalid"
    assert len(posted) == 1


@pytest.mark.asyncio
async def test_admin_oauth_test_uses_custom_parameters_and_returns_upstream_detail(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, _agent_id, _key_id, source_id = _seed(db_session_factory)
    assert (
        await client.post(
            "/api/setup",
            json={"username": "admin", "password": "admin123", "locale": "en-US"},
        )
    ).status_code == 201
    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    csrf = login.json()["csrf_token"]
    cipher = SecretCipher(Fernet.generate_key())
    posted: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request)
        return httpx.Response(
            200,
            json={
                "code": 400,
                "msg": "tenant or audience is invalid",
                "data": None,
            },
        )

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(handler)
    app.dependency_overrides[get_oauth_network_validator] = lambda: allow_network
    configured = await client.put(
        f"/api/admin/sources/{source_id}/oauth",
        headers={"X-CSRF-Token": csrf},
        json={
            "enabled": True,
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token_endpoint_auth_method": "client_secret_basic",
            "token_headers": {"tenant-id": "1"},
            "token_params": {
                "grant_type": "client_credentials",
                "audience": "orders",
            },
            "authorization_url": "https://issuer.example.test/authorize",
            "token_url": "https://issuer.example.test/token",
            "scopes": ["orders.read"],
        },
    )
    assert configured.status_code == 200
    assert configured.json()["token_params"] == {
        "grant_type": "client_credentials",
        "audience": "orders",
    }

    tested = await client.post(
        f"/api/admin/sources/{source_id}/oauth/test",
        headers={"X-CSRF-Token": csrf},
    )

    assert tested.status_code == 400
    assert tested.json()["error"] == {
        "code": "oauth.test_failed",
        "params": {
            "status": 200,
            "business_code": 400,
            "reason": "tenant or audience is invalid",
            "upstream_error": "unknown",
        },
    }
    assert len(posted) == 1
    assert posted[0].headers["tenant-id"] == "1"
    assert posted[0].headers["authorization"].startswith("Basic ")
    assert parse_qs(posted[0].content.decode()) == {
        "grant_type": ["client_credentials"],
        "audience": ["orders"],
        "scope": ["orders.read"],
    }


@pytest.mark.asyncio
async def test_browser_chat_pkce_binds_credentials_and_returns_popup_completion(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "browser-access", "token_type": "Bearer"},
        )

    with db_session_factory() as db:
        db.add(
            AppSetting(
                id=1,
                default_locale="en-US",
                base_url="https://chat.example",
            )
        )
        db.commit()
        _configure(ToolOAuthService(db, cipher), source_id)

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(handler)
    app.dependency_overrides[get_oauth_network_validator] = lambda: allow_network
    bootstrap = await client.get("/api/chat/bootstrap")
    assert bootstrap.status_code == 200

    started = await client.post(
        "/api/chat/oauth/pkce/start",
        json={"api_source_id": source_id, "agent_id": agent_id},
    )

    assert started.status_code == 201
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    with db_session_factory() as db:
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        tool_session = db.get(ToolUserSession, flow.tool_session_id)
        assert tool_session is not None
        assert tool_session.browser_chat_session_id is not None
        assert tool_session.agent_key_id is None
        assert tool_session.admin_session_id is None
        assert tool_session.embed_session_id is None

    callback = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state, "code": "browser-code"},
    )

    assert callback.status_code == 200
    assert "chat4openapi:auth-complete" in callback.text
    assert '"api_source_id":' in callback.text
    assert "window.opener.postMessage" in callback.text
    assert "window.close()" in callback.text
    nonce = callback.text.split('nonce="', 1)[1].split('"', 1)[0]
    assert (
        callback.headers["content-security-policy"]
        == f"default-src 'none'; script-src 'nonce-{nonce}'"
    )
    assert "browser-access" not in callback.text
    assert "chat4openapi_tool_session" not in callback.headers.get("set-cookie", "")
    assert len(token_requests) == 1
    with db_session_factory() as db:
        tool_session = db.scalar(select(ToolUserSession))
        assert tool_session is not None
        assert tool_session.browser_chat_session_id is not None
        resolved = await ToolSessionService(
            db, cipher, NoopExecutor()
        ).resolve_for_browser(
            tool_session.browser_chat_session_id,
            agent_id,
            source_id,
        )
        assert resolved.auth.headers == {
            "Authorization": "Bearer browser-access"
        }


@pytest.mark.asyncio
async def test_browser_chat_pkce_denial_consumes_state_and_closes_popup(
    client: httpx.AsyncClient, app, db_session_factory
) -> None:
    _secret, agent_id, _key_id, source_id = _seed(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    token_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(500)

    with db_session_factory() as db:
        db.add(
            AppSetting(
                id=1,
                default_locale="en-US",
                base_url="https://chat.example",
            )
        )
        db.commit()
        _configure(ToolOAuthService(db, cipher), source_id)

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(handler)
    app.dependency_overrides[get_oauth_network_validator] = lambda: allow_network
    assert (await client.get("/api/chat/bootstrap")).status_code == 200
    started = await client.post(
        "/api/chat/oauth/pkce/start",
        json={"api_source_id": source_id, "agent_id": agent_id},
    )
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]

    missing_result = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state},
    )
    assert missing_result.status_code == 400
    assert missing_result.json()["error"]["code"] == "oauth.callback_invalid"

    callback = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={
            "state": state,
            "error": "access_denied",
            "error_description": "User denied access",
        },
    )

    assert callback.status_code == 200
    assert "chat4openapi:auth-error" in callback.text
    assert '"error":"access_denied"' in callback.text
    assert "User denied access" not in callback.text
    assert token_requests == []
    with db_session_factory() as db:
        flow = db.scalar(select(ToolOAuthAuthorization))
        tool_session = db.scalar(select(ToolUserSession))
        credential = db.scalar(select(ToolSessionCredential))
        assert flow is not None and tool_session is not None and credential is not None
        assert flow.status == "failed"
        assert flow.consumed_at is not None
        assert tool_session.status == "failed"
        assert credential.status == "failed"
        assert cipher.decrypt_json(flow.encrypted_flow_data) == {}
        assert cipher.decrypt_json(credential.encrypted_credentials) == {}

    replay = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "oauth.state_invalid"
