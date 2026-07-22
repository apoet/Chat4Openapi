from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_app_setting"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_locale: Mapped[str] = mapped_column(String(16), default="en-US")
    tool_login_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
