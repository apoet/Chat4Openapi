from cryptography.fernet import Fernet
from fastmcp import Client
import pytest

from chatapi.mcp.runtime import create_mcp_server
from chatapi.models import ApiSource, GlobalToolAuthConfig, Tool
from chatapi.security.encryption import SecretCipher
from chatapi.tool_sessions.service import ToolSessionService
from chatapi.tools.executor import ToolExecutionResult

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


def seed_runtime(factory) -> tuple[int, int, int]:
    with factory() as session:
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
        return login.id, enabled.id, disabled.id


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


async def test_mcp_tool_resolves_original_api_user_session(db_session_factory) -> None:
    seed_runtime(db_session_factory)
    cipher = SecretCipher(Fernet.generate_key())
    executor = McpFakeExecutor()
    with db_session_factory() as session:
        created = await ToolSessionService(session, cipher, executor).create("alice", "secret")
    server = create_mcp_server(db_session_factory, lambda: cipher, executor)

    async with Client(server) as client:
        result = await client.call_tool("get_me", {"tool_session_id": created.token})

    assert result.data == {
        "tool": "get_me",
        "authorization": "Bearer token-alice",
    }
