import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    skill_id: Mapped[int | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    candidate_skill_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    candidate_scope_source: Mapped[str] = mapped_column(
        String(32), default="automatic"
    )
    loaded_skill_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    agent_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_status: Mapped[str] = mapped_column(String(32), default="running")
    pending_clarification: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    latest_failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_chat_message_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int]
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
