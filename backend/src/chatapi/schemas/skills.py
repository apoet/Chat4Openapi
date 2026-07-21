from pydantic import BaseModel, ConfigDict, Field

from chatapi.schemas.tools import ToolSummary


class SkillWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    system_prompt: str = Field(min_length=1, max_length=100_000)
    tool_ids: list[int] = Field(default_factory=list, max_length=128)


class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    system_prompt: str
    running: bool
    tools: list[ToolSummary] = Field(default_factory=list)
