from collections.abc import Callable, Sequence

from fastmcp import FastMCP
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool as FastMCPTool
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.mcp.tool import ManagedMCPTool
from chat4openapi.models import ApiSource, Tool
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.executor import ToolExecutor
from chat4openapi.tools.execution_policy import resolve_tool_execution_policy


class ManagedToolProvider(Provider):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        cipher_factory: Callable[[], SecretCipher],
        executor: ToolExecutor,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._cipher_factory = cipher_factory
        self._executor = executor

    async def _list_tools(self) -> Sequence[FastMCPTool]:
        with self._session_factory() as session:
            tools = session.scalars(
                select(Tool)
                .join(ApiSource, ApiSource.id == Tool.api_source_id)
                .where(
                    Tool.enabled.is_(True),
                    Tool.deleted_at.is_(None),
                    ApiSource.enabled.is_(True),
                    ApiSource.deleted_at.is_(None),
                )
                .order_by(Tool.id)
            ).all()
            exposed: list[FastMCPTool] = []
            for tool in tools:
                policy = resolve_tool_execution_policy(session, tool)
                if policy.is_login_tool:
                    continue
                exposed.append(
                    ManagedMCPTool(
                        tool,
                        auth_enabled=policy.authorization_required,
                        session_factory=self._session_factory,
                        cipher_factory=self._cipher_factory,
                        executor=self._executor,
                    )
                )
            return exposed


def create_mcp_server(
    session_factory: sessionmaker[Session],
    cipher_factory: Callable[[], SecretCipher],
    executor: ToolExecutor,
) -> FastMCP:
    server = FastMCP("Agent4API Managed Tools")
    server.add_provider(ManagedToolProvider(session_factory, cipher_factory, executor))
    return server
