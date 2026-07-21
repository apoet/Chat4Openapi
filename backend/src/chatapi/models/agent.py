from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class AgentConfig(Base):
    __tablename__ = "agent_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_single_agent_config"),
        CheckConstraint(
            "mode IN ('human_in_loop', 'react')", name="ck_agent_mode"
        ),
        CheckConstraint(
            "max_iterations BETWEEN 2 AND 32", name="ck_agent_max_iterations"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(160), default="ChatAPI Agent")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="human_in_loop")
    max_iterations: Mapped[int] = mapped_column(Integer, default=8)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
