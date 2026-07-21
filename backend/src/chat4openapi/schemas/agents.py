from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    system_prompt: str = Field(min_length=1, max_length=100_000)
    provider_id: int | None = None
    model: str | None = Field(default=None, max_length=256)
    mode: Literal["human_in_loop", "react"] = "human_in_loop"
    max_iterations: int = Field(default=8, ge=2, le=32)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    enabled: bool
    is_default: bool
    system_prompt: str
    provider_id: int | None
    model: str | None
    mode: Literal["human_in_loop", "react"]
    max_iterations: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    skill_ids: list[int] = Field(default_factory=list)


class AgentSkillsWrite(BaseModel):
    skill_ids: list[int]


class AgentApiKeyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    expires_at: datetime | None = None


class AgentApiKeyUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def reject_null_label(self) -> Self:
        if "label" in self.model_fields_set and self.label is None:
            raise ValueError("label cannot be null")
        return self


class AgentApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    label: str
    key_prefix: str
    enabled: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class AgentApiKeyCreated(AgentApiKeyResponse):
    secret: str
