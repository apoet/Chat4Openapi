from collections.abc import Callable, Sequence

from fastmcp import FastMCP
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool as FastMCPTool
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.mcp.tool import ManagedMCPTool
from chat4openapi.models import ApiSource, GlobalToolAuthConfig, Tool
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.executor import ToolExecutor


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
            config = session.get(GlobalToolAuthConfig, 1)
            auth_enabled = bool(config is not None and config.enabled)
            login_tool_id = config.login_tool_id if auth_enabled else None
            tools = session.scalars(
                select(Tool)
                .join(ApiSource, ApiSource.id == Tool.api_source_id)
                .where(
                    Tool.enabled.is_(True),
                    Tool.deleted_at.is_(None),
                    ApiSource.enabled.is_(True),
                    ApiSource.deleted_at.is_(None),
                    Tool.id != login_tool_id if login_tool_id is not None else Tool.id.is_not(None),
                )
                .order_by(Tool.id)
            ).all()
            return [
                ManagedMCPTool(
                    tool,
                    auth_enabled=auth_enabled,
                    session_factory=self._session_factory,
                    cipher_factory=self._cipher_factory,
                    executor=self._executor,
                )
                for tool in tools
            ]


def create_mcp_server(
    session_factory: sessionmaker[Session],
    cipher_factory: Callable[[], SecretCipher],
    executor: ToolExecutor,
) -> FastMCP:
    server = FastMCP("Agent4API Managed Tools")
    server.add_provider(ManagedToolProvider(session_factory, cipher_factory, executor))
    return server
