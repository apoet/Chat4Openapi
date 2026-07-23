from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from chat4openapi.embed.urls import normalize_origin

NormalizedOrigin = Annotated[str, AfterValidator(normalize_origin)]


class AgentEmbedWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    allowed_origins: list[NormalizedOrigin] = Field(default_factory=list, max_length=64)
    position: Literal["bottom_right", "bottom_left"] = "bottom_right"

    @field_validator("allowed_origins")
    @classmethod
    def deduplicate_origins(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AgentEmbedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    name: str
    public_id: str
    enabled: bool
    allowed_origins: list[str]
    position: Literal["bottom_right", "bottom_left"]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    script: str | None = None


class AgentEmbedScriptResponse(BaseModel):
    script: str


class EmbedSessionCreate(BaseModel):
    parent_origin: NormalizedOrigin | None = None


class EmbedAgentSummary(BaseModel):
    id: int
    name: str


class EmbedSessionCreated(BaseModel):
    session_id: str
    token: str
    parent_origin: str
    agent: EmbedAgentSummary
