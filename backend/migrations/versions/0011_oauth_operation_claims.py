"""Add durable claims for concurrent OAuth polling and refresh."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_oauth_operation_claims"
down_revision: str | Sequence[str] | None = "0010_tool_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tool_oauth_authorizations") as batch:
        batch.add_column(
            sa.Column(
                "operation_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "operation_in_progress",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("operation_started_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_oauth_authorizations") as batch:
        batch.drop_column("operation_started_at")
        batch.drop_column("operation_in_progress")
        batch.drop_column("operation_generation")
