from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class GlobalToolAuthConfig(Base):
    __tablename__ = "global_tool_auth_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_global_tool_auth"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    login_tool_id: Mapped[int | None] = mapped_column(
        ForeignKey("tools.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    username_field: Mapped[str] = mapped_column(String(128), default="username")
    password_field: Mapped[str] = mapped_column(String(128), default="password")
    token_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(32), default="bearer")
    auth_name: Mapped[str] = mapped_column(String(128), default="Authorization")
    auth_prefix: Mapped[str] = mapped_column(String(64), default="Bearer")
    idle_minutes: Mapped[int] = mapped_column(Integer, default=30)
    absolute_hours: Mapped[int] = mapped_column(Integer, default=8)
