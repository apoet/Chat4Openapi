"""Bind Auto-Agentify jobs to imported API sources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_auto_agentify_source_jobs"
down_revision: str | Sequence[str] | None = "0020_agent_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_auto_agentify_active_creator",
        table_name="auto_agentify_jobs",
    )
    with op.batch_alter_table("auto_agentify_jobs") as batch:
        batch.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_auto_agentify_jobs_source_id",
            "api_sources",
            ["source_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        "ix_auto_agentify_jobs_source_id",
        "auto_agentify_jobs",
        ["source_id"],
    )
    op.create_index(
        "uq_auto_agentify_active_source",
        "auto_agentify_jobs",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text(
            "source_id IS NOT NULL AND status IN ('queued', 'running')"
        ),
    )
    op.create_index(
        "uq_auto_agentify_active_legacy_creator",
        "auto_agentify_jobs",
        ["creator_admin_id"],
        unique=True,
        sqlite_where=sa.text(
            "source_id IS NULL AND status IN ('queued', 'running')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_auto_agentify_active_legacy_creator",
        table_name="auto_agentify_jobs",
    )
    op.drop_index(
        "uq_auto_agentify_active_source",
        table_name="auto_agentify_jobs",
    )
    op.drop_index(
        "ix_auto_agentify_jobs_source_id",
        table_name="auto_agentify_jobs",
    )
    with op.batch_alter_table("auto_agentify_jobs") as batch:
        batch.drop_constraint(
            "fk_auto_agentify_jobs_source_id",
            type_="foreignkey",
        )
        batch.drop_column("source_id")
    op.create_index(
        "uq_auto_agentify_active_creator",
        "auto_agentify_jobs",
        ["creator_admin_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )
