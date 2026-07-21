"""Add encrypted per-source OAuth configuration and authorization state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_tool_oauth"
down_revision: str | Sequence[str] | None = "0009_tool_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_source_oauth_configs",
        sa.Column(
            "api_source_id",
            sa.Integer(),
            sa.ForeignKey("api_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("encrypted_config", sa.LargeBinary(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "tool_oauth_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tool_session_id",
            sa.Integer(),
            sa.ForeignKey("tool_user_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_source_id",
            sa.Integer(),
            sa.ForeignKey("api_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flow_type", sa.String(16), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=True),
        sa.Column("encrypted_flow_data", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("flow_type IN ('device', 'pkce')", name="ck_tool_oauth_flow_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'expired', 'failed')",
            name="ck_tool_oauth_status",
        ),
        sa.UniqueConstraint(
            "tool_session_id", "api_source_id", name="uq_tool_oauth_session_source"
        ),
        sa.UniqueConstraint("state_hash", name="uq_tool_oauth_state_hash"),
    )
    op.create_index(
        "ix_tool_oauth_authorizations_tool_session_id",
        "tool_oauth_authorizations",
        ["tool_session_id"],
    )
    op.create_index(
        "ix_tool_oauth_authorizations_api_source_id",
        "tool_oauth_authorizations",
        ["api_source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_oauth_authorizations_api_source_id",
        table_name="tool_oauth_authorizations",
    )
    op.drop_index(
        "ix_tool_oauth_authorizations_tool_session_id",
        table_name="tool_oauth_authorizations",
    )
    op.drop_table("tool_oauth_authorizations")
    op.drop_table("api_source_oauth_configs")
