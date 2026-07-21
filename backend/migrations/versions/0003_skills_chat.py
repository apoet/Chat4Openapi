"""Add LLM providers, Skills, and conversations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_skills_chat"
down_revision: str | Sequence[str] | None = "0002_tool_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=False),
        sa.Column("default_model", sa.String(256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("running", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_skills_provider_id", "skills", ["provider_id"])
    op.create_table(
        "skill_tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "skill_id",
            sa.Integer(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("tools.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("skill_id", "tool_id", name="uq_skill_tool"),
        sa.UniqueConstraint("skill_id", "position", name="uq_skill_tool_position"),
    )
    op.create_index("ix_skill_tools_skill_id", "skill_tools", ["skill_id"])
    op.create_index("ix_skill_tools_tool_id", "skill_tools", ["tool_id"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "skill_id",
            sa.Integer(),
            sa.ForeignKey("skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_skill_id", "conversations", ["skill_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_chat_message_sequence"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_request_id", "chat_messages", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_request_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_skill_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_skill_tools_tool_id", table_name="skill_tools")
    op.drop_index("ix_skill_tools_skill_id", table_name="skill_tools")
    op.drop_table("skill_tools")
    op.drop_index("ix_skills_provider_id", table_name="skills")
    op.drop_table("skills")
    op.drop_table("llm_providers")
