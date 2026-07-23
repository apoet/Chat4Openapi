from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_password(password: str | None) -> str | None:
    if password is None:
        return None
    has_letter = any(character.isascii() and character.isalpha() for character in password)
    has_number = any(character.isascii() and character.isdigit() for character in password)
    if not has_letter or not has_number:
        raise ValueError("password must contain letters and numbers")
    return password


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=256)
    locale: Literal["en-US", "zh-CN"] = "en-US"
    enabled: bool = True

    _password_strength = field_validator("password")(_validate_password)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(
        default=None, min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    password: str | None = Field(default=None, min_length=6, max_length=256)
    locale: Literal["en-US", "zh-CN"] | None = None
    enabled: bool | None = None

    _password_strength = field_validator("password")(_validate_password)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Literal["user"]
    locale: Literal["en-US", "zh-CN"]
    enabled: bool
    created_at: datetime
