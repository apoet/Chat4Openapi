from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: str | None = None
    candidate_skill_ids: list[int] = Field(default_factory=list, max_length=32)


class ChatTurnResponse(BaseModel):
    status: Literal["completed", "needs_input"]
    conversation_id: str
    message: str
    loaded_skill_ids: list[int]
    pending: dict[str, Any] | None = None
