from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class AgentConfig(Base):
    __tablename__ = "agent_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_agent_config"),)

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
