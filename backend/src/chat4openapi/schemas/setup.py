from pydantic import BaseModel, Field, field_validator


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=256)
    locale: str = Field(pattern=r"^(en-US|zh-CN)$")

    @field_validator("password")
    @classmethod
    def password_contains_letters_and_numbers(cls, password: str) -> str:
        has_letter = any(character.isascii() and character.isalpha() for character in password)
        has_number = any(character.isascii() and character.isdigit() for character in password)
        if not has_letter or not has_number:
            raise ValueError("password must contain letters and numbers")
        return password


class SetupStatus(BaseModel):
    initialized: bool
    locale: str | None = None
