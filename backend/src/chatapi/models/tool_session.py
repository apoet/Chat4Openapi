from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class ToolUserSession(Base):
    __tablename__ = "tool_user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    encrypted_login_data: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_auth_data: Mapped[bytes] = mapped_column(LargeBinary)
    auth_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
