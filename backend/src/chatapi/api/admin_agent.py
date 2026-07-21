from fastapi import APIRouter, Depends

from chatapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chatapi.api.errors import ApiError
from chatapi.chat.agent import DEFAULT_AGENT_PROMPT
from chatapi.models import AgentConfig, LlmProvider
from chatapi.schemas.agents import AgentConfigResponse, AgentConfigWrite

router = APIRouter(prefix="/api/admin/agent", tags=["admin-agent"])

def _agent(context: AdminContext) -> AgentConfig:
    agent = context.db.get(AgentConfig, 1)
    if agent is None:
        raise ApiError(404, "agent.not_found")
    return agent


def _validate_provider(context: AdminContext, provider_id: int | None) -> LlmProvider:
    if provider_id is None:
        raise ApiError(409, "agent.provider_unavailable")
    provider = context.db.get(LlmProvider, provider_id)
    if provider is None or provider.deleted_at is not None or not provider.enabled:
        raise ApiError(409, "agent.provider_unavailable")
    return provider


@router.get("", response_model=AgentConfigResponse)
def get_agent(context: AdminContext = Depends(require_admin)) -> AgentConfig:
    return _agent(context)


@router.put("", response_model=AgentConfigResponse)
def update_agent(
    payload: AgentConfigWrite,
    context: AdminContext = Depends(require_csrf),
) -> AgentConfig:
    _validate_provider(context, payload.provider_id)
    agent = _agent(context)
    for field, value in payload.model_dump().items():
        setattr(agent, field, value)
    context.db.commit()
    return agent


@router.post("/reset", response_model=AgentConfigResponse)
def reset_agent(context: AdminContext = Depends(require_csrf)) -> AgentConfig:
    agent = _agent(context)
    _validate_provider(context, agent.provider_id)
    agent.name = "ChatAPI Agent"
    agent.enabled = True
    agent.system_prompt = DEFAULT_AGENT_PROMPT
    agent.model = None
    agent.mode = "human_in_loop"
    agent.max_iterations = 8
    context.db.commit()
    return agent
