from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tool_id: Mapped[int | None] = mapped_column(
        ForeignKey("tools.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("tool_user_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    arguments_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
