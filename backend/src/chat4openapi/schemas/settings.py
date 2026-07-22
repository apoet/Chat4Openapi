from pydantic import BaseModel, ConfigDict, field_validator

from chat4openapi.embed.urls import normalize_base_url


class AppSettingsWrite(BaseModel):
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return normalize_base_url(value) if value is not None else None


class AppSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_url: str | None
    default_locale: str
    tool_login_enabled: bool
