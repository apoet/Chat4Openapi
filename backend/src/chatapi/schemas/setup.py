from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    locale: str = Field(pattern=r"^(en-US|zh-CN)$")


class SetupStatus(BaseModel):
    initialized: bool
    locale: str | None = None
