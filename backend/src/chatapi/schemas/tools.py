from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    document: str | dict[str, Any]
    base_url: str | None = Field(default=None, max_length=2048)
    allow_private_networks: bool = False


class SourceUrlImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=2048)
    base_url: str | None = Field(default=None, max_length=2048)
    allow_private_networks: bool = False


class ApiSourceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: str
    base_url: str
    document_url: str | None
    allow_private_networks: bool
    enabled: bool
    created_at: datetime


class ApiSourceUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=2048)
    document_url: str | None = Field(default=None, max_length=2048)
    allow_private_networks: bool = False


class ApiSourceEnabledRequest(BaseModel):
    enabled: bool


class SourceRefreshResponse(BaseModel):
    created: int
    updated: int
    unchanged: int


class ToolSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    api_source_id: int
    operation_key: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    execution_schema: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    enabled: bool


class SourceImportResponse(BaseModel):
    source: ApiSourceSummary
    tools: list[ToolSummary]


class ToolEnabledRequest(BaseModel):
    enabled: bool


class ToolUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=4000)


class ToolAuthConfigRequest(BaseModel):
    enabled: bool
    login_tool_id: int | None = None
    username_field: str = Field(default="username", min_length=1, max_length=128)
    password_field: str = Field(default="password", min_length=1, max_length=128)
    token_json_path: str | None = Field(default=None, max_length=512)
    expires_json_path: str | None = Field(default=None, max_length=512)
    auth_type: str = Field(default="bearer", pattern="^(bearer|header|cookie|query)$")
    auth_name: str = Field(default="Authorization", min_length=1, max_length=128)
    auth_prefix: str = Field(default="Bearer", max_length=64)
    idle_minutes: int = Field(default=30, ge=1, le=1440)
    absolute_hours: int = Field(default=8, ge=1, le=720)


class ToolAuthConfigResponse(ToolAuthConfigRequest):
    id: int = 1


class ToolSessionLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)


class ToolSessionStatus(BaseModel):
    authenticated: bool = True
    idle_expires_at: datetime
    absolute_expires_at: datetime


class ToolSessionCreated(ToolSessionStatus):
    tool_session_id: str | None = None


class ToolInvokeRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_session_id: str | None = None


class ToolInvokeResponse(BaseModel):
    status_code: int
    data: Any
    content_type: str
