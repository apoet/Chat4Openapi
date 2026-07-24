from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AutoAgentifyJob(Base):
    __tablename__ = "auto_agentify_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_auto_agentify_job_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_auto_agentify_job_progress",
        ),
        CheckConstraint(
            "input_mode IN ('url', 'file')",
            name="ck_auto_agentify_job_input_mode",
        ),
        Index(
            "uq_auto_agentify_active_source",
            "source_id",
            unique=True,
            sqlite_where=text(
                "source_id IS NOT NULL AND status IN ('queued', 'running')"
            ),
        ),
        Index(
            "uq_auto_agentify_active_legacy_creator",
            "creator_admin_id",
            unique=True,
            sqlite_where=text(
                "source_id IS NULL AND status IN ('queued', 'running')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    creator_admin_id: Mapped[int] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    input_mode: Mapped[str] = mapped_column(String(16))
    source_name: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    allow_private_networks: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    phase: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutoAgentifyJobEvent(Base):
    __tablename__ = "auto_agentify_job_events"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_auto_agentify_job_event_sequence",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_auto_agentify_job_event_progress",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("auto_agentify_jobs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(80))
    phase: Mapped[str] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer)
    message_key: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capability: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
