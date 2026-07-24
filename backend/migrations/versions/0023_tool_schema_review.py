"""Mark tools whose request schema needs review."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_tool_schema_review"
down_revision: str | Sequence[str] | None = "0022_auto_agentify_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tools") as batch:
        batch.add_column(
            sa.Column(
                "needs_schema_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tools") as batch:
        batch.drop_column("needs_schema_review")
