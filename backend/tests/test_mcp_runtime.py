import hashlib

from cryptography.fernet import Fernet
from fastmcp import Client
from fastmcp.exceptions import ToolError
import pytest

from chat4openapi.mcp.runtime import create_mcp_server
from chat4openapi.models import Agent, AgentApiKey, ApiSource, GlobalToolAuthConfig, Tool
from chat4openapi.security.agent_keys import AgentKeyContext
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.service import ToolSessionService
from chat4openapi.tools.executor import ToolExecutionResult

pytestmark = pytest.mark.asyncio


class McpFakeExecutor:
    async def execute(self, tool, _source, arguments, auth):
        if tool.name == "login":
            return ToolExecutionResult(
                200,
                {"access_token": f"token-{arguments['username']}"},
                "application/json",
            )
        return ToolExecutionResult(
            200,
            {"tool": tool.name, "authorization": auth.headers.get("Authorization")},
            "application/json",
        )


def seed_runtime(factory) -> tuple[int, int, int, int, int]:
    with factory() as session:
        agent = Agent(
            name="MCP Agent",
            enabled=True,
            is_default=True,
            system_prompt="MCP Agent",
            mode="react",
            max_iterations=8,
        )
        session.add(agent)
        session.flush()
        key = AgentApiKey(
            agent_id=agent.id,
            label="MCP",
            key_prefix="c4o_mcp_test",
            key_hash=hashlib.sha256(b"mcp-key").hexdigest(),
        )
        session.add(key)
        source = ApiSource(name="API", source_type="openapi", base_url="https://api.test")
        disabled_source = ApiSource(
            name="Off API", source_type="openapi", base_url="https://off.test", enabled=False
        )
        session.add_all([source, disabled_source])
        session.flush()
        login = Tool(
            api_source_id=source.id,
            operation_key="POST /login",
            name="login",
            input_schema={
                "type": "object",
                "properties": {"username": {"type": "string"}, "password": {"type": "string"}},
                "required": ["username", "password"],
            },
            execution_schema={"method": "POST", "path": "/login", "parameters": []},
            enabled=True,
        )
        enabled = Tool(
            api_source_id=source.id,
            operation_key="GET /me",
            name="get_me",
            input_schema={"type": "object", "properties": {}},
            execution_schema={"method": "GET", "path": "/me", "parameters": []},
            enabled=True,
        )
        disabled = Tool(
            api_source_id=source.id,
            operation_key="GET /hidden",
            name="hidden",
            input_schema={"type": "object", "properties": {}},
            execution_schema={"method": "GET", "path": "/hidden", "parameters": []},
            enabled=False,
        )
        source_off = Tool(
            api_source_id=disabled_source.id,
            operation_key="GET /source-off",
            name="source_off",
            input_schema={"type": "object", "properties": {}},
            execution_schema={"method": "GET", "path": "/source-off", "parameters": []},
            enabled=True,
        )
        session.add_all([login, enabled, disabled, source_off])
        session.flush()
        session.add(
            GlobalToolAuthConfig(
                id=1,
                enabled=True,
                login_tool_id=login.id,
                username_field="username",
                password_field="password",
                token_json_path="$.access_token",
                auth_type="bearer",
                auth_name="Authorization",
                auth_prefix="Bearer",
                idle_minutes=30,
                absolute_hours=8,
            )
        )
        session.commit()
        return login.id, enabled.id, disabled.id, agent.id, key.id


async def test_dynamic_mcp_discovery_excludes_disabled_and_login_tools(
    db_session_factory,
) -> None:
    seed_runtime(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    server = create_mcp_server(db_session_factory, lambda: cipher, McpFakeExecutor())

    async with Client(server) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools] == ["get_me"]
    schema = tools[0].inputSchema
    assert schema["properties"]["tool_session_id"]["type"] == "string"
    assert "tool_session_id" in schema["required"]


async def test_mcp_tool_rejects_opaque_session_without_authenticated_owner(
    db_session_factory,
) -> None:
    _login_id, _enabled_id, _disabled_id, agent_id, key_id = seed_runtime(
        db_session_factory
    )
    cipher = SecretCipher(Fernet.generate_key())
    executor = McpFakeExecutor()
    with db_session_factory() as session:
        agent = session.get(Agent, agent_id)
        key = session.get(AgentApiKey, key_id)
        assert agent is not None and key is not None
        context = AgentKeyContext(agent=agent, api_key=key, db=session)
        created = await ToolSessionService(session, cipher, executor).create(
            "alice", "secret", context=context
        )
    server = create_mcp_server(db_session_factory, lambda: cipher, executor)

    async with Client(server) as client:
        with pytest.raises(ToolError, match="authenticated Agent owner"):
            await client.call_tool("get_me", {"tool_session_id": created.token})
