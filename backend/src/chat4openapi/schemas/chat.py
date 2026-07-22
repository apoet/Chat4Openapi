from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentId = Annotated[int, Field(strict=True, gt=0)]


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: str | None = None
    agent_id: AgentId | None = None


class ChatTurnResponse(BaseModel):
    status: Literal["completed", "needs_input"]
    conversation_id: str
    agent_id: AgentId
    agent_name: str
    message: str
    loaded_skill_ids: list[int]
    pending: dict[str, Any] | None = None


class ChatAgentSummary(BaseModel):
    id: AgentId
    name: str
    is_default: bool
    skill_ids: list[int]


class ChatBootstrapResponse(BaseModel):
    subject_id: str
    agents: list[ChatAgentSummary]
