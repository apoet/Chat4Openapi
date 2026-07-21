from datetime import datetime

from sqlalchemy import Boolean, DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    provider_type: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(2048))
    encrypted_api_key: Mapped[bytes] = mapped_column(LargeBinary)
    default_model: Mapped[str] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
