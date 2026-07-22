from dataclasses import dataclass

from sqlalchemy.orm import Session

from chat4openapi.models import (
    ApiSource,
    ApiSourceOAuthConfig,
    GlobalToolAuthConfig,
    Tool,
)


class ToolUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    source: ApiSource
    authorization_required: bool
    is_login_tool: bool


def resolve_tool_execution_policy(session: Session, tool: Tool) -> ToolExecutionPolicy:
    session.refresh(tool)
    if tool.deleted_at is not None or not tool.enabled:
        raise ToolUnavailableError("Tool was not found")
    source = session.get(ApiSource, tool.api_source_id, populate_existing=True)
    if source is None or source.deleted_at is not None or not source.enabled:
        raise ToolUnavailableError("Tool API Source was not found")
    legacy = session.get(GlobalToolAuthConfig, 1, populate_existing=True)
    oauth = session.get(ApiSourceOAuthConfig, source.id, populate_existing=True)
    legacy_enabled = legacy is not None and legacy.enabled
    return ToolExecutionPolicy(
        source=source,
        authorization_required=legacy_enabled or (oauth is not None and oauth.enabled),
        is_login_tool=bool(legacy_enabled and legacy.login_tool_id == tool.id),
    )
