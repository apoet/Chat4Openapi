"""Store encrypted custom request configuration for API Source authentication."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_source_auth_request_config"
down_revision: str | Sequence[str] | None = "0017_api_source_auth_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_source_tool_auth_configs") as batch:
        batch.add_column(
            sa.Column("encrypted_request_config", sa.LargeBinary(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("api_source_tool_auth_configs") as batch:
        batch.drop_column("encrypted_request_config")
