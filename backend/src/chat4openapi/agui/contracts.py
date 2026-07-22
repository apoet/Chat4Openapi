import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CLIENT_TOOLS = 64
MAX_CATALOG_BYTES = 256 * 1024
MAX_SCHEMA_BYTES = 64 * 1024
MAX_SCHEMA_DEPTH = 16


def _json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


class AguiMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(min_length=1, max_length=256)
    role: Literal["system", "developer", "user", "assistant", "tool", "activity"]
    content: Any = None
    tool_call_id: str | None = Field(default=None, alias="toolCallId", max_length=256)


class AguiTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^web__[A-Za-z0-9_.-]{1,128}$", max_length=133)
    description: str = Field(min_length=1, max_length=4096)
    parameters: dict[str, Any]

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if _depth(value) > MAX_SCHEMA_DEPTH:
            raise ValueError("client Tool schema depth exceeds 16")
        if _json_size(value) > MAX_SCHEMA_BYTES:
            raise ValueError("client Tool schema size exceeds 64 KiB")
        return value


class AguiRunInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    run_id: str = Field(alias="runId", min_length=1, max_length=256)
    state: Any = Field(default_factory=dict)
    messages: list[AguiMessage] = Field(default_factory=list, max_length=1000)
    tools: list[AguiTool] = Field(default_factory=list, max_length=MAX_CLIENT_TOOLS)
    context: list[Any] = Field(default_factory=list, max_length=128)
    forwarded_props: dict[str, Any] = Field(default_factory=dict, alias="forwardedProps")

    @model_validator(mode="after")
    def validate_tool_catalog_size(self) -> "AguiRunInput":
        catalog = [tool.model_dump(mode="json") for tool in self.tools]
        if _json_size(catalog) > MAX_CATALOG_BYTES:
            raise ValueError("client Tool catalog exceeds 256 KiB")
        return self
