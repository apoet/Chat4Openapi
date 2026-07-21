"""Remember source document URLs for manual refresh."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_api_source_refresh"
down_revision: str | Sequence[str] | None = "0003_skills_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_sources",
        sa.Column("document_url", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_sources", "document_url")
