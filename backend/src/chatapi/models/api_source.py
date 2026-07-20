from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class ApiSource(Base):
    __tablename__ = "api_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    source_type: Mapped[str] = mapped_column(String(32), default="openapi")
    base_url: Mapped[str] = mapped_column(String(2048))
    spec_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    allow_private_networks: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
