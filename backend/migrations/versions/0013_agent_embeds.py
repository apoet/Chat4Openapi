"""Add Agent embeds, anonymous sessions, and Embed-owned resources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_agent_embeds"
down_revision: str | Sequence[str] | None = "0012_conversation_owners"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CONVERSATION_OWNER_CHECK = (
    "(deleted_at IS NOT NULL AND agent_key_id IS NULL AND "
    "browser_chat_session_id IS NULL AND embed_session_id IS NULL) OR "
    "((agent_key_id IS NOT NULL AND browser_chat_session_id IS NULL AND "
    "embed_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND browser_chat_session_id IS NOT NULL AND "
    "embed_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND browser_chat_session_id IS NULL AND "
    "embed_session_id IS NOT NULL))"
)

TOOL_SESSION_OWNER_CHECK = (
    "(agent_key_id IS NOT NULL AND admin_session_id IS NULL AND "
    "embed_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND admin_session_id IS NOT NULL AND "
    "embed_session_id IS NULL) OR "
    "(agent_key_id IS NULL AND admin_session_id IS NULL AND "
    "embed_session_id IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(sa.Column("base_url", sa.String(2048), nullable=True))

    op.create_table(
        "agent_embeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("public_id", sa.String(43), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_origins", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "position", sa.String(16), nullable=False, server_default="bottom_right"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "position IN ('bottom_right', 'bottom_left')",
            name="ck_agent_embed_position",
        ),
    )
    op.create_index("ix_agent_embeds_agent_id", "agent_embeds", ["agent_id"])
    op.create_index("ix_agent_embeds_public_id", "agent_embeds", ["public_id"], unique=True)

    op.create_table(
        "embed_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_subject_id", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "embed_id",
            sa.Integer(),
            sa.ForeignKey("agent_embeds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_origin", sa.String(2048), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idle_expires_at", sa.DateTime(), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "public_subject_id",
        "embed_id",
        "agent_id",
        "token_hash",
        "idle_expires_at",
        "absolute_expires_at",
    ):
        op.create_index(
            f"ix_embed_sessions_{column}",
            "embed_sessions",
            [column],
            unique=column in {"public_subject_id", "token_hash"},
        )

    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversation_exactly_one_active_owner", type_="check")
        batch.add_column(sa.Column("embed_session_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_embed_session_id_embed_sessions",
            "embed_sessions",
            ["embed_session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_conversations_embed_session_id", ["embed_session_id"])
        batch.create_check_constraint(
            "ck_conversation_exactly_one_active_owner", CONVERSATION_OWNER_CHECK
        )

    with op.batch_alter_table("tool_user_sessions") as batch:
        batch.drop_constraint("ck_tool_session_one_owner", type_="check")
        batch.add_column(sa.Column("embed_session_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_tool_user_sessions_embed_session_id_embed_sessions",
            "embed_sessions",
            ["embed_session_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_tool_user_sessions_embed_session_id", ["embed_session_id"])
        batch.create_check_constraint("ck_tool_session_one_owner", TOOL_SESSION_OWNER_CHECK)

    op.create_table(
        "embed_auth_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "embed_session_id",
            sa.Integer(),
            sa.ForeignKey("embed_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for column in (
        "code_hash",
        "embed_session_id",
        "tool_session_id",
        "api_source_id",
        "expires_at",
    ):
        op.create_index(
            f"ix_embed_auth_grants_{column}",
            "embed_auth_grants",
            [column],
            unique=column == "code_hash",
        )


def downgrade() -> None:
    op.drop_table("embed_auth_grants")

    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM conversations WHERE embed_session_id IS NOT NULL"))
    connection.execute(sa.text("DELETE FROM tool_user_sessions WHERE embed_session_id IS NOT NULL"))

    with op.batch_alter_table("tool_user_sessions") as batch:
        batch.drop_constraint("ck_tool_session_one_owner", type_="check")
        batch.drop_index("ix_tool_user_sessions_embed_session_id")
        batch.drop_constraint(
            "fk_tool_user_sessions_embed_session_id_embed_sessions", type_="foreignkey"
        )
        batch.drop_column("embed_session_id")
        batch.create_check_constraint(
            "ck_tool_session_one_owner",
            "(agent_key_id IS NOT NULL AND admin_session_id IS NULL) OR "
            "(agent_key_id IS NULL AND admin_session_id IS NOT NULL)",
        )

    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversation_exactly_one_active_owner", type_="check")
        batch.drop_index("ix_conversations_embed_session_id")
        batch.drop_constraint(
            "fk_conversations_embed_session_id_embed_sessions", type_="foreignkey"
        )
        batch.drop_column("embed_session_id")
        batch.create_check_constraint(
            "ck_conversation_exactly_one_active_owner",
            "(deleted_at IS NOT NULL AND agent_key_id IS NULL AND "
            "browser_chat_session_id IS NULL) OR "
            "((agent_key_id IS NULL AND browser_chat_session_id IS NOT NULL) OR "
            "(agent_key_id IS NOT NULL AND browser_chat_session_id IS NULL))",
        )

    op.drop_table("embed_sessions")
    op.drop_table("agent_embeds")
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("base_url")
