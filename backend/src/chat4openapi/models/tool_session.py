from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class ToolUserSession(Base):
    __tablename__ = "tool_user_sessions"
    __table_args__ = (
        CheckConstraint(
            "(agent_key_id IS NOT NULL AND admin_session_id IS NULL AND "
            "embed_session_id IS NULL AND browser_chat_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NOT NULL AND "
            "embed_session_id IS NULL AND browser_chat_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
            "embed_session_id IS NOT NULL AND browser_chat_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
            "embed_session_id IS NULL AND browser_chat_session_id IS NOT NULL)",
            name="ck_tool_session_one_owner",
        ),
        CheckConstraint(
            "status IN ('authorization_required', 'pending', 'ready', "
            "'expired', 'revoked', 'failed')",
            name="ck_tool_session_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    agent_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_api_keys.id", ondelete="CASCADE"), nullable=True, index=True
    )
    admin_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    embed_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("embed_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    browser_chat_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("browser_chat_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="ready")
    encrypted_login_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_auth_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    auth_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolSessionCredential(Base):
    __tablename__ = "tool_session_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tool_session_id", "api_source_id", name="uq_tool_session_credential_source"
        ),
        CheckConstraint(
            "status IN ('authorization_required', 'pending', 'ready', "
            "'expired', 'revoked', 'failed')",
            name="ck_tool_session_credential_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_session_id: Mapped[int] = mapped_column(
        ForeignKey("tool_user_sessions.id", ondelete="CASCADE"), index=True
    )
    api_source_id: Mapped[int] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), index=True
    )
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApiSourceOAuthConfig(Base):
    __tablename__ = "api_source_oauth_configs"

    api_source_id: Mapped[int] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_config: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ToolOAuthAuthorization(Base):
    __tablename__ = "tool_oauth_authorizations"
    __table_args__ = (
        CheckConstraint("flow_type IN ('device', 'pkce')", name="ck_tool_oauth_flow_type"),
        CheckConstraint(
            "status IN ('pending', 'ready', 'expired', 'failed')",
            name="ck_tool_oauth_status",
        ),
        UniqueConstraint("tool_session_id", "api_source_id", name="uq_tool_oauth_session_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_session_id: Mapped[int] = mapped_column(
        ForeignKey("tool_user_sessions.id", ondelete="CASCADE"), index=True
    )
    api_source_id: Mapped[int] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), index=True
    )
    flow_type: Mapped[str] = mapped_column(String(16))
    state_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    encrypted_flow_data: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operation_generation: Mapped[int] = mapped_column(Integer, default=0)
    operation_in_progress: Mapped[bool] = mapped_column(Boolean, default=False)
    operation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
