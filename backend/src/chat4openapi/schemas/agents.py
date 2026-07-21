from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    system_prompt: str = Field(min_length=1, max_length=100_000)
    provider_id: int
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


# Temporary M2 aliases keep singleton-era API routes stable. M3 replaces those
# routes with explicit multi-Agent administration using the primary schema names.
AgentConfigWrite = AgentWrite


class AgentConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    enabled: bool
    system_prompt: str
    provider_id: int | None
    model: str | None
    mode: Literal["human_in_loop", "react"]
    max_iterations: int
    created_at: datetime
    updated_at: datetime
