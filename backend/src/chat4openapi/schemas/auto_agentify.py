from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from chat4openapi.schemas.tools import ApiSourceSummary


class SkillPlan(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4_000)
    system_prompt: str = Field(min_length=1, max_length=100_000)
    operation_keys: list[str] = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4_000)


class AgentPlan(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    responsibility: str = Field(min_length=1, max_length=4_000)
    system_prompt: str = Field(min_length=1, max_length=100_000)
    skill_names: list[str] = Field(min_length=1, max_length=20)
    mode: Literal["human_in_loop", "react"]
    max_iterations: int = Field(ge=2, le=32)
    value: str = Field(min_length=1, max_length=4_000)
    use_cases: list[str] = Field(min_length=1, max_length=10)


class CapabilitySummary(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2_000)
    value: str = Field(min_length=1, max_length=2_000)
    workflow: list[str] = Field(min_length=1, max_length=12)
    operation_keys: list[str] = Field(min_length=1, max_length=200)
    candidate_skills: list[str] = Field(min_length=1, max_length=20)
    high_impact: bool


class CapabilityBatch(BaseModel):
    capabilities: list[CapabilitySummary] = Field(min_length=1, max_length=50)

    def validate_references(self, operation_keys: set[str]) -> None:
        for capability in self.capabilities:
            unknown = set(capability.operation_keys) - operation_keys
            if unknown:
                raise ValueError(
                    f"unknown capability operation: {sorted(unknown)[0]}"
                )


class GenerationPlan(BaseModel):
    skills: list[SkillPlan] = Field(min_length=1, max_length=20)
    agents: list[AgentPlan] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "GenerationPlan":
        skill_names = [item.name for item in self.skills]
        agent_names = [item.name for item in self.agents]
        if len(set(skill_names)) != len(skill_names):
            raise ValueError("duplicate skill name")
        if len(set(agent_names)) != len(agent_names):
            raise ValueError("duplicate agent name")
        return self

    def validate_references(self, operation_keys: set[str]) -> None:
        skill_names = {item.name for item in self.skills}
        for skill in self.skills:
            unknown = set(skill.operation_keys) - operation_keys
            if unknown:
                raise ValueError(f"unknown operation: {sorted(unknown)[0]}")
        for agent in self.agents:
            unknown = set(agent.skill_names) - skill_names
            if unknown:
                raise ValueError(f"unknown skill: {sorted(unknown)[0]}")


class AutoAgentifyUrlRequest(BaseModel):
    provider_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=2048)
    base_url: str | None = Field(default=None, max_length=2048)
    allow_private_networks: bool = False


class GeneratedSkillResponse(BaseModel):
    id: int
    name: str
    tool_ids: list[int]
    value: str


class GeneratedAgentResponse(BaseModel):
    id: int
    name: str
    skill_ids: list[int]
    mode: Literal["human_in_loop", "react"]
    provider_id: int
    value: str
    use_cases: list[str]


class AutoAgentifyResponse(BaseModel):
    source: ApiSourceSummary
    imported_tool_count: int
    enabled_tool_count: int
    skills: list[GeneratedSkillResponse]
    agents: list[GeneratedAgentResponse]


class AutoAgentifyJobEventResponse(BaseModel):
    sequence: int
    kind: str
    phase: str
    progress: int
    message_key: str
    params: dict[str, Any]
    capability: dict[str, Any] | None
    created_at: datetime


class AutoAgentifyJobResponse(BaseModel):
    public_id: str
    provider_id: int
    input_mode: Literal["url", "file"]
    source_name: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: str
    progress: int
    metrics: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_params: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
