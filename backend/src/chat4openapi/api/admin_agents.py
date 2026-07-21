from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select, update

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import Agent, AgentSkill, LlmProvider, Skill
from chat4openapi.schemas.agents import AgentResponse, AgentSkillsWrite, AgentWrite

router = APIRouter(prefix="/api/admin/agents", tags=["admin-agents"])


def _agent(context: AdminContext, agent_id: int) -> Agent:
    agent = context.db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise ApiError(404, "agents.not_found")
    return agent


def _response(context: AdminContext, agent: Agent) -> AgentResponse:
    skill_ids = list(
        context.db.scalars(
            select(AgentSkill.skill_id)
            .where(AgentSkill.agent_id == agent.id)
            .order_by(AgentSkill.position, AgentSkill.skill_id)
        )
    )
    response = AgentResponse.model_validate(agent)
    return response.model_copy(update={"skill_ids": skill_ids})


def _validate_provider(context: AdminContext, agent: Agent) -> None:
    provider = (
        context.db.get(LlmProvider, agent.provider_id) if agent.provider_id is not None else None
    )
    if provider is None or provider.deleted_at is not None or not provider.enabled:
        raise ApiError(409, "agents.provider_unavailable")


def _validate_running_skill(context: AdminContext, agent: Agent) -> None:
    running_skill_id = context.db.scalar(
        select(AgentSkill.skill_id)
        .join(Skill, Skill.id == AgentSkill.skill_id)
        .where(
            AgentSkill.agent_id == agent.id,
            Skill.deleted_at.is_(None),
            Skill.running.is_(True),
        )
        .limit(1)
    )
    if running_skill_id is None:
        raise ApiError(409, "agents.no_running_skills")


def _validate_enable(context: AdminContext, agent: Agent) -> None:
    _validate_provider(context, agent)
    _validate_running_skill(context, agent)


def _binding_skills(context: AdminContext, skill_ids: list[int]) -> list[Skill]:
    if len(skill_ids) != len(set(skill_ids)):
        raise ApiError(409, "agents.skill_duplicate")
    skills: list[Skill] = []
    for skill_id in skill_ids:
        skill = context.db.get(Skill, skill_id)
        if skill is None or skill.deleted_at is not None:
            raise ApiError(409, "agents.skill_unavailable", skill_id=skill_id)
        skills.append(skill)
    return skills


@router.get("", response_model=list[AgentResponse])
def list_agents(context: AdminContext = Depends(require_admin)) -> list[AgentResponse]:
    agents = context.db.scalars(
        select(Agent).where(Agent.deleted_at.is_(None)).order_by(Agent.id)
    ).all()
    return [_response(context, agent) for agent in agents]


@router.post("", response_model=AgentResponse, status_code=201)
def create_agent(
    payload: AgentWrite, context: AdminContext = Depends(require_csrf)
) -> AgentResponse:
    with serialized_write(context.db):
        agent = Agent(**payload.model_dump(), is_default=False)
        context.db.add(agent)
        context.db.flush()
        if agent.provider_id is not None:
            _validate_provider(context, agent)
        elif agent.enabled:
            _validate_provider(context, agent)
        if agent.enabled:
            _validate_running_skill(context, agent)
    return _response(context, agent)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int, context: AdminContext = Depends(require_admin)) -> AgentResponse:
    return _response(context, _agent(context, agent_id))


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: int,
    payload: AgentWrite,
    context: AdminContext = Depends(require_csrf),
) -> AgentResponse:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        if agent.is_default and not payload.enabled:
            raise ApiError(409, "agents.default_cannot_disable")
        was_enabled = agent.enabled
        for field, value in payload.model_dump().items():
            setattr(agent, field, value)
        if agent.provider_id is not None:
            _validate_provider(context, agent)
        elif agent.enabled:
            _validate_provider(context, agent)
        if agent.enabled and not was_enabled:
            _validate_running_skill(context, agent)
    return _response(context, agent)


@router.put("/{agent_id}/skills", response_model=AgentResponse)
def replace_agent_skills(
    agent_id: int,
    payload: AgentSkillsWrite,
    context: AdminContext = Depends(require_csrf),
) -> AgentResponse:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        skills = _binding_skills(context, payload.skill_ids)
        context.db.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent.id))
        context.db.add_all(
            AgentSkill(agent_id=agent.id, skill_id=skill.id, position=position)
            for position, skill in enumerate(skills)
        )
    return _response(context, agent)


@router.post("/{agent_id}/enable", response_model=AgentResponse)
def enable_agent(agent_id: int, context: AdminContext = Depends(require_csrf)) -> AgentResponse:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        _validate_enable(context, agent)
        agent.enabled = True
    return _response(context, agent)


@router.post("/{agent_id}/disable", response_model=AgentResponse)
def disable_agent(agent_id: int, context: AdminContext = Depends(require_csrf)) -> AgentResponse:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        if agent.is_default:
            raise ApiError(409, "agents.default_cannot_disable")
        agent.enabled = False
    return _response(context, agent)


@router.post("/{agent_id}/set-default", response_model=AgentResponse)
def set_default_agent(
    agent_id: int, context: AdminContext = Depends(require_csrf)
) -> AgentResponse:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        _validate_enable(context, agent)
        context.db.execute(update(Agent).where(Agent.deleted_at.is_(None)).values(is_default=False))
        agent.is_default = True
        agent.enabled = True
    return _response(context, agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, context: AdminContext = Depends(require_csrf)) -> None:
    with serialized_write(context.db):
        agent = _agent(context, agent_id)
        if agent.is_default:
            raise ApiError(409, "agents.default_cannot_delete")
        agent.enabled = False
        agent.deleted_at = datetime.now(UTC).replace(tzinfo=None)
