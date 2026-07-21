from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_admin"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    locale: Mapped[str] = mapped_column(String(16), default="en-US")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
