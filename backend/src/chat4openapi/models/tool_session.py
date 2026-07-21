from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class ToolUserSession(Base):
    __tablename__ = "tool_user_sessions"
    __table_args__ = (
        CheckConstraint(
            "(agent_key_id IS NOT NULL AND admin_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NOT NULL)",
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
