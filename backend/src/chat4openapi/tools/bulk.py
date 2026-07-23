from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.models import (
    ApiSource,
    ApiSourceToolAuthConfig,
    GlobalToolAuthConfig,
    Skill,
    SkillTool,
    Tool,
)

ToolAction = Literal["enable", "disable", "delete"]
ToolActionStatus = Literal["enabled", "disabled", "deleted"]


def _managed_tool(db: Session, tool_id: int) -> Tool:
    tool = db.get(Tool, tool_id)
    if tool is None or tool.deleted_at is not None:
        raise ApiError(404, "tools.not_found")
    return tool


def _ensure_source_available(db: Session, tool: Tool) -> None:
    source = db.get(ApiSource, tool.api_source_id)
    if source is None or source.deleted_at is not None or not source.enabled:
        raise ApiError(409, "tools.source_unavailable", source_id=tool.api_source_id)


def _ensure_not_login_tool(db: Session, tool_id: int) -> None:
    source_config = db.scalar(
        select(ApiSourceToolAuthConfig).where(
            ApiSourceToolAuthConfig.enabled.is_(True),
            ApiSourceToolAuthConfig.login_tool_id == tool_id,
        )
    )
    if source_config is not None:
        raise ApiError(409, "tools.login_tool_conflict")
    config = db.get(GlobalToolAuthConfig, 1)
    if config is not None and config.enabled and config.login_tool_id == tool_id:
        raise ApiError(409, "tools.login_tool_conflict")


def stop_skills_using_tools(db: Session, tool_ids: list[int]) -> None:
    if not tool_ids:
        return
    skills = db.scalars(
        select(Skill)
        .join(SkillTool, SkillTool.skill_id == Skill.id)
        .where(SkillTool.tool_id.in_(tool_ids), Skill.running.is_(True))
        .distinct()
    ).all()
    for skill in skills:
        skill.running = False


def apply_tool_action(
    db: Session,
    tool_id: int,
    action: ToolAction,
) -> ToolActionStatus:
    tool = _managed_tool(db, tool_id)
    if action == "enable":
        _ensure_source_available(db, tool)
        tool.enabled = True
        return "enabled"

    _ensure_not_login_tool(db, tool.id)
    stop_skills_using_tools(db, [tool.id])
    tool.enabled = False
    if action == "delete":
        tool.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        return "deleted"
    return "disabled"
