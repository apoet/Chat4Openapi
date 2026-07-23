from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chat4openapi.schemas.auth import validate_password_strength


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=256)
    password_confirm: str = Field(min_length=6, max_length=256)
    locale: Literal["en-US", "zh-CN"] = "en-US"
    enabled: bool = True

    _password_strength = field_validator("password")(validate_password_strength)

    @model_validator(mode="after")
    def passwords_match(self) -> "UserCreateRequest":
        if self.password != self.password_confirm:
            raise ValueError("password confirmation does not match")
        return self


class UserUpdateRequest(BaseModel):
    username: str | None = Field(
        default=None, min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    locale: Literal["en-US", "zh-CN"] | None = None
    enabled: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["user"]
    locale: Literal["en-US", "zh-CN"]
    enabled: bool
    created_at: datetime
