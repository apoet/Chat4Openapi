from dataclasses import dataclass

from sqlalchemy.orm import Session

from chat4openapi.models import (
    ApiSource,
    ApiSourceOAuthConfig,
    ApiSourceToolAuthConfig,
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
    tool_auth = session.get(
        ApiSourceToolAuthConfig, source.id, populate_existing=True
    )
    source_tool_enabled = bool(
        source.auth_mode == "tool"
        and tool_auth is not None
        and tool_auth.enabled
    )
    oauth_enabled = bool(
        source.auth_mode in {"none", "oauth"}
        and oauth is not None
        and oauth.enabled
    )
    legacy_enabled = bool(
        source.auth_mode == "none"
        and legacy is not None
        and legacy.enabled
    )
    login_tool_id = (
        tool_auth.login_tool_id if source_tool_enabled and tool_auth is not None
        else legacy.login_tool_id if legacy_enabled and legacy is not None
        else None
    )
    return ToolExecutionPolicy(
        source=source,
        authorization_required=source_tool_enabled or legacy_enabled or oauth_enabled,
        is_login_tool=login_tool_id == tool.id,
    )
