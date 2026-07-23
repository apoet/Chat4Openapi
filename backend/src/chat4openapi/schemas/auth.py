from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def validate_password_strength(password: str) -> str:
    has_letter = any(
        character.isascii() and character.isalpha() for character in password
    )
    has_number = any(
        character.isascii() and character.isdigit() for character in password
    )
    if not has_letter or not has_number:
        raise ValueError("password must contain letters and numbers")
    return password


class NewPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=256)
    new_password_confirm: str = Field(min_length=6, max_length=256)

    _new_password_strength = field_validator("new_password")(
        validate_password_strength
    )

    @model_validator(mode="after")
    def passwords_match(self) -> "NewPasswordRequest":
        if self.new_password != self.new_password_confirm:
            raise ValueError("password confirmation does not match")
        return self


class PasswordChangeRequest(NewPasswordRequest):
    current_password: str = Field(min_length=1, max_length=256)


class AdminPasswordResetRequest(NewPasswordRequest):
    key: str = Field(min_length=1, max_length=512)


class AdminPasswordResetIssued(BaseModel):
    credential_path: str
    expires_at: datetime


class AdminSummary(BaseModel):
    username: str
    locale: str
    role: Literal["admin", "user"]


class AuthResponse(BaseModel):
    admin: AdminSummary
    csrf_token: str
