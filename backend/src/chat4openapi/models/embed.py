from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AgentEmbed(Base):
    __tablename__ = "agent_embeds"
    __table_args__ = (
        CheckConstraint(
            "position IN ('bottom_right', 'bottom_left')",
            name="ck_agent_embed_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    public_id: Mapped[str] = mapped_column(String(43), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list)
    position: Mapped[str] = mapped_column(String(16), default="bottom_right")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmbedSession(Base):
    __tablename__ = "embed_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_subject_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    embed_id: Mapped[int] = mapped_column(
        ForeignKey("agent_embeds.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    parent_origin: Mapped[str] = mapped_column(String(2048))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmbedAuthGrant(Base):
    __tablename__ = "embed_auth_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    embed_session_id: Mapped[int] = mapped_column(
        ForeignKey("embed_sessions.id", ondelete="CASCADE"), index=True
    )
    tool_session_id: Mapped[int] = mapped_column(
        ForeignKey("tool_user_sessions.id", ondelete="CASCADE"), index=True
    )
    api_source_id: Mapped[int] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
