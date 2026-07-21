from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chatapi.db.base import Base


class ToolParameterOverride(Base):
    __tablename__ = "tool_parameter_overrides"
    __table_args__ = (
        UniqueConstraint("tool_id", "argument_name", name="uq_tool_parameter_override"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), index=True
    )
    argument_name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    example: Mapped[Any | None] = mapped_column(JSON, nullable=True)
