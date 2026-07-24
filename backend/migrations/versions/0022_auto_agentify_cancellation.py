"""Allow Auto-Agentify jobs to be cancelled."""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_auto_agentify_cancellation"
down_revision: str | Sequence[str] | None = "0021_auto_agentify_source_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auto_agentify_jobs") as batch:
        batch.drop_constraint("ck_auto_agentify_job_status", type_="check")
        batch.create_check_constraint(
            "ck_auto_agentify_job_status",
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("auto_agentify_jobs") as batch:
        batch.drop_constraint("ck_auto_agentify_job_status", type_="check")
        batch.create_check_constraint(
            "ck_auto_agentify_job_status",
            "status IN ('queued', 'running', 'completed', 'failed')",
        )
