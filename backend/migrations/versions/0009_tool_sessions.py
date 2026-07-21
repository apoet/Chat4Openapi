"""Bind encrypted Tool Sessions to owners, Agents, and API Sources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_tool_sessions"
down_revision: str | Sequence[str] | None = "0008_multi_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'authorization_required', 'pending', 'ready', 'expired', 'revoked', 'failed'"


def upgrade() -> None:
    with op.batch_alter_table("tool_user_sessions") as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("agent_key_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("admin_session_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="ready")
        )
        batch_op.create_foreign_key(
            "fk_tool_user_sessions_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_tool_user_sessions_agent_key_id_agent_api_keys",
            "agent_api_keys",
            ["agent_key_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_tool_user_sessions_admin_session_id_admin_sessions",
            "admin_sessions",
            ["admin_session_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Pre-M6 sessions have no authenticated platform owner. Deleting them is the only
    # safe migration: assigning them to a shared owner would make their opaque tokens
    # reusable across Agents or browser sessions.
    op.get_bind().execute(sa.text("DELETE FROM tool_user_sessions"))
    with op.batch_alter_table("tool_user_sessions") as batch_op:
        batch_op.alter_column("agent_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "encrypted_login_data", existing_type=sa.LargeBinary(), nullable=True
        )
        batch_op.alter_column(
            "encrypted_auth_data", existing_type=sa.LargeBinary(), nullable=True
        )
        batch_op.create_check_constraint(
            "ck_tool_session_one_owner",
            "(agent_key_id IS NOT NULL AND admin_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_tool_session_status", f"status IN ({STATUSES})"
        )
        batch_op.create_index("ix_tool_user_sessions_agent_id", ["agent_id"])
        batch_op.create_index("ix_tool_user_sessions_agent_key_id", ["agent_key_id"])
        batch_op.create_index("ix_tool_user_sessions_admin_session_id", ["admin_session_id"])

    op.create_table(
        "tool_session_credentials",
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
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_tool_session_credential_status"),
        sa.UniqueConstraint(
            "tool_session_id", "api_source_id", name="uq_tool_session_credential_source"
        ),
    )
    op.create_index(
        "ix_tool_session_credentials_tool_session_id",
        "tool_session_credentials",
        ["tool_session_id"],
    )
    op.create_index(
        "ix_tool_session_credentials_api_source_id",
        "tool_session_credentials",
        ["api_source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_session_credentials_api_source_id", table_name="tool_session_credentials"
    )
    op.drop_index(
        "ix_tool_session_credentials_tool_session_id", table_name="tool_session_credentials"
    )
    op.drop_table("tool_session_credentials")
    op.get_bind().execute(sa.text("DELETE FROM tool_user_sessions"))
    with op.batch_alter_table("tool_user_sessions") as batch_op:
        batch_op.drop_index("ix_tool_user_sessions_admin_session_id")
        batch_op.drop_index("ix_tool_user_sessions_agent_key_id")
        batch_op.drop_index("ix_tool_user_sessions_agent_id")
        batch_op.drop_constraint("ck_tool_session_status", type_="check")
        batch_op.drop_constraint("ck_tool_session_one_owner", type_="check")
        batch_op.drop_constraint(
            "fk_tool_user_sessions_admin_session_id_admin_sessions", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_tool_user_sessions_agent_key_id_agent_api_keys", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_tool_user_sessions_agent_id_agents", type_="foreignkey"
        )
        batch_op.alter_column(
            "encrypted_auth_data", existing_type=sa.LargeBinary(), nullable=False
        )
        batch_op.alter_column(
            "encrypted_login_data", existing_type=sa.LargeBinary(), nullable=False
        )
        batch_op.drop_column("status")
        batch_op.drop_column("admin_session_id")
        batch_op.drop_column("agent_key_id")
        batch_op.drop_column("agent_id")
