import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api.tool_oauth import (
    get_oauth_network_validator,
    get_oauth_transport,
)
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.api.tool_sessions import get_tool_executor
from chat4openapi.embed.sessions import issue_embed_session
from chat4openapi.models import (
    Agent,
    AgentEmbed,
    AgentSkill,
    ApiSource,
    AppSetting,
    EmbedAuthGrant,
    GlobalToolAuthConfig,
    LlmProvider,
    Skill,
    ToolOAuthAuthorization,
    Tool,
    ToolUserSession,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.oauth import ToolOAuthService
from chat4openapi.tool_sessions.service import ToolSessionService
from chat4openapi.tool_sessions.service import ToolSessionNotFound
from chat4openapi.tools.executor import ToolExecutionResult


class _UnusedExecutor:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("resolve does not execute a Tool")


async def _allow_network(_url: httpx.URL, _allow_private: bool) -> None:
    return None


def _seed(
    factory: sessionmaker[Session], cipher: SecretCipher
) -> tuple[AgentEmbed, str, str, ApiSource]:
    with factory() as db:
        settings = AppSetting(id=1, base_url="https://chat.example")
        provider = LlmProvider(
            name="Provider",
            provider_type="openai",
            base_url="https://llm.example/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "provider-secret"}),
            default_model="test-model",
            enabled=True,
        )
        source = ApiSource(
            name="Protected API",
            source_type="openapi",
            base_url="https://api.example",
            enabled=True,
        )
        skill = Skill(name="Support", system_prompt="Help.", running=True)
        db.add_all([settings, provider, source, skill])
        db.flush()
        login_tool = Tool(
            api_source_id=source.id,
            operation_key="POST /login",
            name="swagger_login",
            description="Sign in",
            input_schema={"type": "object"},
            execution_schema={"method": "POST", "path": "/login", "parameters": []},
            enabled=True,
        )
        db.add(login_tool)
        db.flush()
        db.add(
            GlobalToolAuthConfig(
                id=1,
                enabled=True,
                login_tool_id=login_tool.id,
                username_field="username",
                password_field="password",
                token_json_path="$.token",
                auth_type="bearer",
                auth_name="Authorization",
                auth_prefix="Bearer",
            )
        )
        agent = Agent(
            name="Site Assistant",
            system_prompt="Help visitors.",
            provider_id=provider.id,
            enabled=True,
        )
        db.add(agent)
        db.flush()
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill.id, position=0))
        embed = AgentEmbed(
            agent_id=agent.id,
            name="Docs",
            public_id="oauth-embed",
            allowed_origins=["https://host.example"],
            enabled=True,
        )
        db.add(embed)
        db.flush()
        owner, token = issue_embed_session(db, embed, "https://host.example")
        ToolOAuthService(db, cipher).configure_source(
            source.id,
            {
                "enabled": True,
                "client_id": "embed-client",
                "client_secret": "client-secret",
                "authorization_url": "https://identity.example/authorize",
                "token_url": "https://identity.example/token",
                "device_authorization_url": None,
                "redirect_uri": None,
                "scopes": ["orders.read"],
            },
        )
        db.commit()
        return embed, owner.public_subject_id, token, source


@pytest.mark.asyncio
async def test_embed_pkce_callback_returns_single_use_grant_not_tokens(
    client: httpx.AsyncClient,
    app,
    db_session_factory: sessionmaker[Session],
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    embed, session_id, token, source = _seed(db_session_factory, cipher)

    async def token_exchange(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://identity.example/token")
        assert b"redirect_uri=https%3A%2F%2Fchat.example%2Fapi%2Ftool-sessions%2Foauth%2Fpkce%2Fcallback" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "upstream-access-token",
                "refresh_token": "upstream-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_oauth_network_validator] = lambda: _allow_network
    app.dependency_overrides[get_oauth_transport] = lambda: httpx.MockTransport(
        token_exchange
    )
    headers = {"Authorization": f"Bearer {token}"}

    started = await client.post(
        f"/api/embed/sessions/{session_id}/auth/start",
        headers=headers,
        json={"api_source_id": source.id, "flow": "pkce"},
    )

    assert started.status_code == 201
    authorization_url = started.json()["authorization_url"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["redirect_uri"] == [
        "https://chat.example/api/tool-sessions/oauth/pkce/callback"
    ]
    state = query["state"][0]
    with db_session_factory() as db:
        flow = db.scalar(select(ToolOAuthAuthorization))
        assert flow is not None
        tool_session = db.get(ToolUserSession, flow.tool_session_id)
        assert tool_session is not None
        assert tool_session.embed_session_id is not None
        assert tool_session.agent_key_id is None
        assert tool_session.admin_session_id is None
        binding = cipher.decrypt_json(flow.encrypted_flow_data)
        assert binding["parent_origin"] == "https://host.example"
        assert binding["embed_session_id"] == tool_session.embed_session_id

    callback = await client.get(
        "/api/tool-sessions/oauth/pkce/callback",
        params={"state": state, "code": "upstream-code"},
    )

    assert callback.status_code == 200
    assert callback.headers["cache-control"] == "no-store"
    assert "chat4openapi:auth-grant" in callback.text
    assert "https://host.example" in callback.text
    assert "upstream-access-token" not in callback.text
    assert "upstream-refresh-token" not in callback.text
    assert "tool_session" not in callback.text
    grant_code = re.search(r'"grant":"([^"]+)"', callback.text)
    assert grant_code is not None

    exchanged = await client.post(
        f"/api/embed/sessions/{session_id}/auth/exchange",
        headers=headers,
        json={"grant": grant_code.group(1)},
    )
    replay = await client.post(
        f"/api/embed/sessions/{session_id}/auth/exchange",
        headers=headers,
        json={"grant": grant_code.group(1)},
    )

    assert exchanged.status_code == 200
    assert exchanged.json() == {
        "status": "ready",
        "api_source_id": source.id,
    }
    assert replay.status_code == 404
    assert "upstream-access-token" not in exchanged.text
    assert "tool_session" not in exchanged.text
    with db_session_factory() as db:
        assert db.scalar(select(EmbedAuthGrant)) is not None
        tool_session = db.scalar(select(ToolUserSession))
        assert tool_session is not None
        resolved = await ToolSessionService(
            db, cipher, _UnusedExecutor()
        ).resolve_for_embed(
            tool_session.embed_session_id,
            tool_session.agent_id,
            source.id,
        )
        assert resolved.auth.headers == {
            "Authorization": "Bearer upstream-access-token"
        }

    revoked = await client.delete(
        f"/api/embed/sessions/{session_id}/auth/{source.id}",
        headers=headers,
    )
    assert revoked.status_code == 204
    with db_session_factory() as db:
        tool_session = db.scalar(select(ToolUserSession))
        assert tool_session is not None
        with pytest.raises(ToolSessionNotFound):
            await ToolSessionService(db, cipher, _UnusedExecutor()).resolve_for_embed(
                tool_session.embed_session_id,
                tool_session.agent_id,
                source.id,
            )


@pytest.mark.asyncio
async def test_embed_swagger_login_posts_credentials_and_returns_only_grant(
    client: httpx.AsyncClient,
    app,
    db_session_factory: sessionmaker[Session],
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    _embed, session_id, token, source = _seed(db_session_factory, cipher)

    class LoginExecutor:
        def __init__(self) -> None:
            self.calls = []

        async def execute(self, tool, _source, arguments, _auth):
            self.calls.append((tool.name, arguments))
            return ToolExecutionResult(
                200,
                {"token": "swagger-access-token"},
                "application/json",
            )

    executor = LoginExecutor()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_tool_executor] = lambda: executor
    headers = {"Authorization": f"Bearer {token}"}

    started = await client.post(
        f"/api/embed/sessions/{session_id}/auth/start",
        headers=headers,
        json={"api_source_id": source.id, "flow": "swagger"},
    )

    assert started.status_code == 201
    popup_url = started.json()["authorization_url"]
    assert popup_url.startswith("https://chat.example/api/embed/auth/swagger?state=")
    form = await client.get(urlparse(popup_url).path + "?" + urlparse(popup_url).query)
    assert form.status_code == 200
    assert 'type="password"' in form.text
    assert "swagger-access-token" not in form.text
    state = parse_qs(urlparse(popup_url).query)["state"][0]

    completed = await client.post(
        "/api/embed/auth/swagger",
        data={"state": state, "username": "visitor", "password": "secret-password"},
    )

    assert completed.status_code == 200
    assert "chat4openapi:auth-grant" in completed.text
    assert "visitor" not in completed.text
    assert "secret-password" not in completed.text
    assert "swagger-access-token" not in completed.text
    assert "tool_session" not in completed.text
    assert executor.calls == [
        ("swagger_login", {"username": "visitor", "password": "secret-password"})
    ]
    grant_code = re.search(r'"grant":"([^"]+)"', completed.text)
    assert grant_code is not None
    exchanged = await client.post(
        f"/api/embed/sessions/{session_id}/auth/exchange",
        headers=headers,
        json={"grant": grant_code.group(1)},
    )
    assert exchanged.status_code == 200
    assert exchanged.json() == {"status": "ready", "api_source_id": source.id}
