from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chatapi.api.errors import ApiError
from chatapi.db.session import get_db_session
from chatapi.models import (
    ApiSource,
    GlobalToolAuthConfig,
    Skill,
    SkillTool,
    Tool,
)
from chatapi.schemas.skills import SkillResponse, SkillWriteRequest
from chatapi.schemas.tools import ToolSummary

router = APIRouter(tags=["skills"])


def _skill(context: AdminContext, skill_id: int) -> Skill:
    skill = context.db.get(Skill, skill_id)
    if skill is None or skill.deleted_at is not None:
        raise ApiError(404, "skills.not_found")
    return skill


def _eligible_tools(context: AdminContext, tool_ids: list[int]) -> list[Tool]:
    if len(tool_ids) != len(set(tool_ids)):
        raise ApiError(409, "skills.tool_duplicate")
    config = context.db.get(GlobalToolAuthConfig, 1)
    login_tool_id = config.login_tool_id if config is not None and config.enabled else None
    tools: list[Tool] = []
    for tool_id in tool_ids:
        tool = context.db.get(Tool, tool_id)
        source = context.db.get(ApiSource, tool.api_source_id) if tool is not None else None
        if (
            tool is None
            or tool.deleted_at is not None
            or not tool.enabled
            or tool.id == login_tool_id
            or source is None
            or source.deleted_at is not None
            or not source.enabled
        ):
            raise ApiError(409, "skills.tool_unavailable", tool_id=tool_id)
        tools.append(tool)
    return tools


def _response(db: Session, skill: Skill) -> SkillResponse:
    tools = db.scalars(
        select(Tool)
        .join(SkillTool, SkillTool.tool_id == Tool.id)
        .where(SkillTool.skill_id == skill.id)
        .order_by(SkillTool.position)
    ).all()
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        system_prompt=skill.system_prompt,
        running=skill.running,
        tools=[ToolSummary.model_validate(tool) for tool in tools],
    )


def _write_skill(
    context: AdminContext,
    payload: SkillWriteRequest,
    skill: Skill | None = None,
) -> SkillResponse:
    tools = _eligible_tools(context, payload.tool_ids)
    if skill is None:
        skill = Skill(
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
        )
        context.db.add(skill)
        context.db.flush()
    else:
        skill.name = payload.name
        skill.description = payload.description
        skill.system_prompt = payload.system_prompt
        skill.running = False
        context.db.execute(delete(SkillTool).where(SkillTool.skill_id == skill.id))
        context.db.flush()
    context.db.add_all(
        SkillTool(skill_id=skill.id, tool_id=tool.id, position=position)
        for position, tool in enumerate(tools)
    )
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "skills.name_conflict") from exc
    return _response(context.db, skill)


@router.get("/api/admin/skills", response_model=list[SkillResponse])
def list_admin_skills(
    context: AdminContext = Depends(require_admin),
) -> list[SkillResponse]:
    skills = context.db.scalars(
        select(Skill).where(Skill.deleted_at.is_(None)).order_by(Skill.id)
    ).all()
    return [_response(context.db, skill) for skill in skills]


@router.get("/api/admin/skills/eligible-tools", response_model=list[ToolSummary])
def list_eligible_tools(
    context: AdminContext = Depends(require_admin),
) -> list[ToolSummary]:
    config = context.db.get(GlobalToolAuthConfig, 1)
    login_tool_id = config.login_tool_id if config is not None and config.enabled else None
    statement = (
        select(Tool)
        .join(ApiSource, ApiSource.id == Tool.api_source_id)
        .where(
            Tool.deleted_at.is_(None),
            Tool.enabled.is_(True),
            ApiSource.deleted_at.is_(None),
            ApiSource.enabled.is_(True),
        )
        .order_by(Tool.id)
    )
    if login_tool_id is not None:
        statement = statement.where(Tool.id != login_tool_id)
    return [ToolSummary.model_validate(tool) for tool in context.db.scalars(statement)]


@router.post("/api/admin/skills", response_model=SkillResponse, status_code=201)
def create_skill(
    payload: SkillWriteRequest, context: AdminContext = Depends(require_csrf)
) -> SkillResponse:
    return _write_skill(context, payload)


@router.put("/api/admin/skills/{skill_id}", response_model=SkillResponse)
def update_skill(
    skill_id: int,
    payload: SkillWriteRequest,
    context: AdminContext = Depends(require_csrf),
) -> SkillResponse:
    return _write_skill(context, payload, _skill(context, skill_id))


@router.post("/api/admin/skills/{skill_id}/start", response_model=SkillResponse)
def start_skill(
    skill_id: int, context: AdminContext = Depends(require_csrf)
) -> SkillResponse:
    skill = _skill(context, skill_id)
    binding_ids = list(
        context.db.scalars(
            select(SkillTool.tool_id)
            .where(SkillTool.skill_id == skill.id)
            .order_by(SkillTool.position)
        )
    )
    _eligible_tools(context, binding_ids)
    skill.running = True
    context.db.commit()
    return _response(context.db, skill)


@router.post("/api/admin/skills/{skill_id}/stop", response_model=SkillResponse)
def stop_skill(
    skill_id: int, context: AdminContext = Depends(require_csrf)
) -> SkillResponse:
    skill = _skill(context, skill_id)
    skill.running = False
    context.db.commit()
    return _response(context.db, skill)


@router.delete("/api/admin/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: int, context: AdminContext = Depends(require_csrf)) -> None:
    skill = _skill(context, skill_id)
    skill.running = False
    skill.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    context.db.commit()


@router.get("/api/skills", response_model=list[SkillResponse])
def list_running_skills(db: Session = Depends(get_db_session)) -> list[SkillResponse]:
    skills = db.scalars(
        select(Skill)
        .where(Skill.deleted_at.is_(None), Skill.running.is_(True))
        .order_by(Skill.id)
    ).all()
    return [_response(db, skill) for skill in skills]
