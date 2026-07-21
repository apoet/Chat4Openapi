from pydantic import BaseModel, ConfigDict, Field


class ProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider_type: str = Field(pattern="^(openai|anthropic)$")
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=4096)
    default_model: str = Field(min_length=1, max_length=256)
    enabled: bool = True


class ProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    provider_type: str | None = Field(default=None, pattern="^(openai|anthropic)$")
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    default_model: str | None = Field(default=None, min_length=1, max_length=256)
    enabled: bool | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: str
    base_url: str
    default_model: str
    enabled: bool
    has_api_key: bool = True
