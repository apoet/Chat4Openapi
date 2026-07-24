"""Add a human-readable description to Agents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_agent_description"
down_revision: str | Sequence[str] | None = "0019_auto_agentify_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "description")
