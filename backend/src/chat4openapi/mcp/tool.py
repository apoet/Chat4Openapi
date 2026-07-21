from copy import deepcopy
from typing import Any

from fastmcp.tools import Tool as FastMCPTool
from fastmcp.tools.base import ToolResult
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import ApiSource, GlobalToolAuthConfig, Tool
from chat4openapi.tool_sessions.service import ToolSessionService
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.executor import RequestAuth, ToolExecutor


class ManagedMCPTool(FastMCPTool):
    def __init__(
        self,
        tool: Tool,
        *,
        auth_enabled: bool,
        session_factory: sessionmaker[Session],
        cipher_factory,
        executor: ToolExecutor,
    ) -> None:
        parameters = deepcopy(tool.input_schema)
        if auth_enabled:
            parameters.setdefault("type", "object")
            parameters.setdefault("properties", {})["tool_session_id"] = {
                "type": "string",
                "description": "Opaque Tool Session ID returned after original API login",
            }
            required = parameters.setdefault("required", [])
            if "tool_session_id" not in required:
                required.append("tool_session_id")
        super().__init__(
            name=tool.name,
            description=tool.description or f"Executes {tool.operation_key}",
            parameters=parameters,
        )
        self._tool_id = tool.id
        self._auth_enabled = auth_enabled
        self._session_factory = session_factory
        self._cipher_factory = cipher_factory
        self._executor = executor

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        call_arguments = dict(arguments)
        with self._session_factory() as session:
            tool = session.get(Tool, self._tool_id)
            if tool is None or tool.deleted_at is not None or not tool.enabled:
                raise ToolExecutionError("tool_disabled", "Tool is disabled or unavailable")
            source = session.get(ApiSource, tool.api_source_id)
            if (
                source is None
                or source.deleted_at is not None
                or not source.enabled
            ):
                raise ToolExecutionError("source_disabled", "Tool API Source is unavailable")
            config = session.get(GlobalToolAuthConfig, 1)
            if config is not None and config.enabled:
                if config.login_tool_id == tool.id:
                    raise ToolExecutionError("tool_unavailable", "Login Tool is not callable")
                session_id = call_arguments.pop("tool_session_id", None)
                if not session_id:
                    raise ToolExecutionError(
                        "tool_session_required", "Original API Tool Session is required"
                    )
                result = await ToolSessionService(
                    session, self._cipher_factory(), self._executor
                ).execute(tool, call_arguments, session_id)
            else:
                call_arguments.pop("tool_session_id", None)
                result = await self._executor.execute(
                    tool, source, call_arguments, RequestAuth()
                )
        return self.convert_result(result.data)
