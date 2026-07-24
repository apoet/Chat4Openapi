from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from chat4openapi.schemas.tools import ApiSourceSummary

BUILTIN_SYSTEM_CAPABILITIES = {
    "system_configuration": "system configuration / 系统配置",
    "user_permissions": "users and permissions / 用户与权限",
    "organization_management": "organization management / 组织管理",
    "file_management": "file management / 文件管理",
    "messaging_notifications": "messaging and notifications / 消息通知",
    "task_scheduling": "task scheduling / 任务调度",
    "audit_compliance": "audit logs and compliance / 审计日志与合规",
    "reference_data": "reference data and dictionaries / 数据字典",
    "monitoring_operations": "monitoring and operations / 监控运维",
    "authentication_authorization": "authentication and authorization / 认证授权",
    "developer_tools": "developer tools / 开发工具",
    "ai_platform": "AI platform configuration / AI 平台",
}


class CapabilityPreferences(BaseModel):
    allowed_system_capabilities: list[str] = Field(
        default_factory=list, max_length=len(BUILTIN_SYSTEM_CAPABILITIES)
    )
    custom_capability_labels: list[str] = Field(
        default_factory=list, max_length=20
    )

    @field_validator("allowed_system_capabilities")
    @classmethod
    def validate_system_capabilities(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value))
        unknown = set(normalized) - BUILTIN_SYSTEM_CAPABILITIES.keys()
        if unknown:
            raise ValueError(f"unknown system capability: {sorted(unknown)[0]}")
        return normalized

    @field_validator("custom_capability_labels")
    @classmethod
    def normalize_custom_capabilities(cls, value: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(item.strip() for item in value if item.strip())
        )
        if any(len(item) > 80 for item in normalized):
            raise ValueError("custom capability label is too long")
        return normalized


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
    capabilities: list[CapabilitySummary] = Field(min_length=1, max_length=6)

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
    allowed_system_capabilities: list[str] = Field(default_factory=list)
    custom_capability_labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capability_preferences(self) -> "AutoAgentifyUrlRequest":
        preferences = CapabilityPreferences(
            allowed_system_capabilities=self.allowed_system_capabilities,
            custom_capability_labels=self.custom_capability_labels,
        )
        self.allowed_system_capabilities = (
            preferences.allowed_system_capabilities
        )
        self.custom_capability_labels = preferences.custom_capability_labels
        return self


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
