"""Add managed Tool Runtime persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_tool_runtime"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="openapi"),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("spec_snapshot", sa.Text(), nullable=True),
        sa.Column("spec_hash", sa.String(64), nullable=True),
        sa.Column("allow_private_networks", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "api_source_id",
            sa.Integer(),
            sa.ForeignKey("api_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_key", sa.String(1024), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("execution_schema", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("api_source_id", "operation_key", name="uq_tool_source_operation"),
    )
    op.create_index("ix_tools_api_source_id", "tools", ["api_source_id"])
    op.create_table(
        "global_tool_auth_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "login_tool_id",
            sa.Integer(),
            sa.ForeignKey("tools.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("username_field", sa.String(128), nullable=False, server_default="username"),
        sa.Column("password_field", sa.String(128), nullable=False, server_default="password"),
        sa.Column("token_json_path", sa.String(512), nullable=True),
        sa.Column("expires_json_path", sa.String(512), nullable=True),
        sa.Column("auth_type", sa.String(32), nullable=False, server_default="bearer"),
        sa.Column("auth_name", sa.String(128), nullable=False, server_default="Authorization"),
        sa.Column("auth_prefix", sa.String(64), nullable=False, server_default="Bearer"),
        sa.Column("idle_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("absolute_hours", sa.Integer(), nullable=False, server_default="8"),
        sa.CheckConstraint("id = 1", name="ck_single_global_tool_auth"),
    )
    op.create_table(
        "tool_user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_login_data", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_auth_data", sa.LargeBinary(), nullable=False),
        sa.Column("auth_expires_at", sa.DateTime(), nullable=True),
        sa.Column("idle_expires_at", sa.DateTime(), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tool_user_sessions_token_hash", "tool_user_sessions", ["token_hash"])
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("tools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tool_session_id",
            sa.Integer(),
            sa.ForeignKey("tool_user_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("arguments_summary", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tool_invocations_request_id", "tool_invocations", ["request_id"])
    op.create_index("ix_tool_invocations_tool_id", "tool_invocations", ["tool_id"])
    op.create_index("ix_tool_invocations_tool_session_id", "tool_invocations", ["tool_session_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_invocations_tool_session_id", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_tool_id", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_request_id", table_name="tool_invocations")
    op.drop_table("tool_invocations")
    op.drop_index("ix_tool_user_sessions_token_hash", table_name="tool_user_sessions")
    op.drop_table("tool_user_sessions")
    op.drop_table("global_tool_auth_config")
    op.drop_index("ix_tools_api_source_id", table_name="tools")
    op.drop_table("tools")
    op.drop_table("api_sources")
