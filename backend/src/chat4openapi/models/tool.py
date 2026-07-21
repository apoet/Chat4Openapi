from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (
        UniqueConstraint("api_source_id", "operation_key", name="uq_tool_source_operation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    api_source_id: Mapped[int] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), index=True
    )
    operation_key: Mapped[str] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    execution_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
