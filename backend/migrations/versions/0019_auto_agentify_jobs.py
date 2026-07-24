"""Persist Auto-Agentify background jobs and ordered progress events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_auto_agentify_jobs"
down_revision: str | Sequence[str] | None = "0018_source_auth_request_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auto_agentify_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("creator_admin_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("input_mode", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "allow_private_networks",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "phase",
            sa.String(length=64),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "progress",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("error_params", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_auto_agentify_job_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_auto_agentify_job_progress",
        ),
        sa.CheckConstraint(
            "input_mode IN ('url', 'file')",
            name="ck_auto_agentify_job_input_mode",
        ),
        sa.ForeignKeyConstraint(
            ["creator_admin_id"], ["admin_users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["llm_providers.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_auto_agentify_jobs_public_id",
        "auto_agentify_jobs",
        ["public_id"],
    )
    op.create_index(
        "ix_auto_agentify_jobs_creator_admin_id",
        "auto_agentify_jobs",
        ["creator_admin_id"],
    )
    op.create_index(
        "ix_auto_agentify_jobs_provider_id",
        "auto_agentify_jobs",
        ["provider_id"],
    )
    op.create_index(
        "uq_auto_agentify_active_creator",
        "auto_agentify_jobs",
        ["creator_admin_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "auto_agentify_job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message_key", sa.String(length=200), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("capability", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100",
            name="ck_auto_agentify_job_event_progress",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["auto_agentify_jobs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_auto_agentify_job_event_sequence",
        ),
    )
    op.create_index(
        "ix_auto_agentify_job_events_job_id",
        "auto_agentify_job_events",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_table("auto_agentify_job_events")
    op.drop_table("auto_agentify_jobs")
