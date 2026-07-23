"""Bind OAuth Tool Sessions to browser Chat sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_browser_chat_tool_sessions"
down_revision: str | Sequence[str] | None = "0015_system_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OWNER_CHECK = (
    "(agent_key_id IS NOT NULL AND admin_session_id IS NULL AND "
    "embed_session_id IS NULL AND browser_chat_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND admin_session_id IS NOT NULL AND "
    "embed_session_id IS NULL AND browser_chat_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
    "embed_session_id IS NOT NULL AND browser_chat_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
    "embed_session_id IS NULL AND browser_chat_session_id IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("tool_user_sessions") as batch:
        batch.drop_constraint("ck_tool_session_one_owner", type_="check")
        batch.add_column(sa.Column("browser_chat_session_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_tool_user_sessions_browser_chat_session_id_browser_chat_sessions",
            "browser_chat_sessions",
            ["browser_chat_session_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_tool_user_sessions_browser_chat_session_id",
            ["browser_chat_session_id"],
        )
        batch.create_check_constraint("ck_tool_session_one_owner", OWNER_CHECK)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM tool_user_sessions "
            "WHERE browser_chat_session_id IS NOT NULL"
        )
    )
    with op.batch_alter_table("tool_user_sessions") as batch:
        batch.drop_constraint("ck_tool_session_one_owner", type_="check")
        batch.drop_index("ix_tool_user_sessions_browser_chat_session_id")
        batch.drop_constraint(
            "fk_tool_user_sessions_browser_chat_session_id_browser_chat_sessions",
            type_="foreignkey",
        )
        batch.drop_column("browser_chat_session_id")
        batch.create_check_constraint(
            "ck_tool_session_one_owner",
            "(agent_key_id IS NOT NULL AND admin_session_id IS NULL AND "
            "embed_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NOT NULL AND "
            "embed_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
            "embed_session_id IS NOT NULL)",
        )
