"""Scope authentication mode and login Tool configuration to API Sources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_api_source_auth_mode"
down_revision: str | Sequence[str] | None = "0016_browser_chat_tool_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_sources") as batch:
        batch.add_column(
            sa.Column(
                "auth_mode",
                sa.String(length=16),
                nullable=False,
                server_default="none",
            )
        )
        batch.create_check_constraint(
            "ck_api_source_auth_mode",
            "auth_mode IN ('none', 'oauth', 'tool')",
        )

    op.create_table(
        "api_source_tool_auth_configs",
        sa.Column("api_source_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("login_tool_id", sa.Integer(), nullable=True),
        sa.Column("username_field", sa.String(length=128), nullable=False),
        sa.Column("password_field", sa.String(length=128), nullable=False),
        sa.Column("token_json_path", sa.String(length=512), nullable=True),
        sa.Column("expires_json_path", sa.String(length=512), nullable=True),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("auth_name", sa.String(length=128), nullable=False),
        sa.Column("auth_prefix", sa.String(length=64), nullable=False),
        sa.Column("idle_minutes", sa.Integer(), nullable=False),
        sa.Column("absolute_hours", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["api_source_id"], ["api_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["login_tool_id"], ["tools.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("api_source_id"),
        sa.UniqueConstraint("login_tool_id"),
    )

    op.execute(
        """
        INSERT INTO api_source_tool_auth_configs (
            api_source_id, enabled, login_tool_id, username_field,
            password_field, token_json_path, expires_json_path, auth_type,
            auth_name, auth_prefix, idle_minutes, absolute_hours
        )
        SELECT
            t.api_source_id,
            CASE WHEN EXISTS (
                SELECT 1 FROM api_source_oauth_configs oauth
                WHERE oauth.api_source_id = t.api_source_id
                  AND oauth.enabled = TRUE
            ) THEN 0 ELSE legacy.enabled END,
            legacy.login_tool_id, legacy.username_field,
            legacy.password_field, legacy.token_json_path,
            legacy.expires_json_path, legacy.auth_type,
            legacy.auth_name, legacy.auth_prefix,
            legacy.idle_minutes, legacy.absolute_hours
        FROM global_tool_auth_config legacy
        JOIN tools t ON t.id = legacy.login_tool_id
        WHERE legacy.enabled = 1
        """
    )
    op.execute(
        """
        UPDATE api_sources
        SET auth_mode = 'tool'
        WHERE id IN (
            SELECT api_source_id
            FROM api_source_tool_auth_configs
            WHERE enabled = TRUE
        )
        """
    )
    op.execute(
        """
        UPDATE api_sources
        SET auth_mode = 'oauth'
        WHERE id IN (
            SELECT api_source_id
            FROM api_source_oauth_configs
            WHERE enabled = TRUE
        )
        """
    )


def downgrade() -> None:
    op.drop_table("api_source_tool_auth_configs")
    with op.batch_alter_table("api_sources") as batch:
        batch.drop_constraint("ck_api_source_auth_mode", type_="check")
        batch.drop_column("auth_mode")
