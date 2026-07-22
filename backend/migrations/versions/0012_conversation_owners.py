"""Bind conversations to stable API-key or browser-session owners."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_conversation_owners"
down_revision: str | Sequence[str] | None = "0011_oauth_operation_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("public_subject_id", sa.String(36), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_browser_chat_sessions_token_hash",
        "browser_chat_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_browser_chat_sessions_public_subject_id",
        "browser_chat_sessions",
        ["public_subject_id"],
        unique=True,
    )
    op.create_index(
        "ix_browser_chat_sessions_expires_at",
        "browser_chat_sessions",
        ["expires_at"],
    )

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("agent_key_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("browser_chat_session_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_agent_key_id_agent_api_keys",
            "agent_api_keys",
            ["agent_key_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_conversations_browser_chat_session_id_browser_chat_sessions",
            "browser_chat_sessions",
            ["browser_chat_session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_conversations_agent_key_id", ["agent_key_id"])
        batch.create_index(
            "ix_conversations_browser_chat_session_id", ["browser_chat_session_id"]
        )

    # This product has not shipped with resumable ownerless conversations. Preserve
    # their audit rows, but make them explicitly unresumable before enforcing owners.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE conversations
            SET agent_status = CASE
                    WHEN deleted_at IS NULL THEN 'revoked'
                    ELSE agent_status
                END,
                latest_failure_summary = CASE
                    WHEN latest_failure_summary IS NULL
                    THEN 'Conversation predates owner isolation and cannot be resumed.'
                    ELSE latest_failure_summary
                END,
                deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP)
            WHERE agent_key_id IS NULL AND browser_chat_session_id IS NULL
            """
        )
    )

    with op.batch_alter_table("conversations") as batch:
        batch.create_check_constraint(
            "ck_conversation_exactly_one_active_owner",
            "(deleted_at IS NOT NULL AND agent_key_id IS NULL AND "
            "browser_chat_session_id IS NULL) OR "
            "((agent_key_id IS NULL AND browser_chat_session_id IS NOT NULL) OR "
            "(agent_key_id IS NOT NULL AND browser_chat_session_id IS NULL))",
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversation_exactly_one_active_owner", type_="check")
        batch.drop_index("ix_conversations_browser_chat_session_id")
        batch.drop_index("ix_conversations_agent_key_id")
        batch.drop_constraint(
            "fk_conversations_browser_chat_session_id_browser_chat_sessions",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_conversations_agent_key_id_agent_api_keys", type_="foreignkey"
        )
        batch.drop_column("browser_chat_session_id")
        batch.drop_column("agent_key_id")

    op.drop_index(
        "ix_browser_chat_sessions_expires_at", table_name="browser_chat_sessions"
    )
    op.drop_index(
        "ix_browser_chat_sessions_public_subject_id", table_name="browser_chat_sessions"
    )
    op.drop_index(
        "ix_browser_chat_sessions_token_hash", table_name="browser_chat_sessions"
    )
    op.drop_table("browser_chat_sessions")
