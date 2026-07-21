"""Migrate singleton Agent persistence to multi-Agent tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_multi_agent"
down_revision: str | Sequence[str] | None = "0007_agent_runtime_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False, server_default="human_in_loop"),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("mode IN ('human_in_loop', 'react')", name="ck_agent_mode"),
        sa.CheckConstraint("max_iterations BETWEEN 2 AND 32", name="ck_agent_max_iterations"),
    )
    op.create_index("ix_agents_provider_id", "agents", ["provider_id"])
    op.create_index(
        "uq_agents_active_default",
        "agents",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1 AND deleted_at IS NULL"),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO agents
                (id, name, enabled, is_default, system_prompt, provider_id,
                 model, mode, max_iterations, created_at, updated_at)
            SELECT
                id, name, enabled, true, system_prompt, provider_id,
                model, mode, max_iterations, created_at, updated_at
            FROM agent_config
            WHERE id = 1
            """
        )
    )

    op.create_table(
        "agent_skills",
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            sa.Integer(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill"),
    )
    op.create_index("ix_agent_skills_skill_id", "agent_skills", ["skill_id"])
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_skills (agent_id, skill_id, position)
            SELECT 1, id, row_number() OVER (ORDER BY id) - 1
            FROM skills
            WHERE deleted_at IS NULL
            ORDER BY id
            """
        )
    )

    op.create_table(
        "agent_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agent_api_keys_agent_id", "agent_api_keys", ["agent_id"])
    op.create_index("ix_agent_api_keys_key_prefix", "agent_api_keys", ["key_prefix"])

    op.add_column("conversations", sa.Column("agent_id", sa.Integer(), nullable=True))
    connection.execute(sa.text("UPDATE conversations SET agent_id = 1"))
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.alter_column("agent_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_conversations_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_conversations_agent_id", ["agent_id"])

    op.drop_table("agent_config")


def downgrade() -> None:
    op.create_table(
        "agent_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, server_default="Chat4Openapi Agent"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False, server_default="human_in_loop"),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_single_agent_config"),
        sa.CheckConstraint("mode IN ('human_in_loop', 'react')", name="ck_agent_mode"),
        sa.CheckConstraint("max_iterations BETWEEN 2 AND 32", name="ck_agent_max_iterations"),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_config
                (id, name, enabled, system_prompt, provider_id, model, mode,
                 max_iterations, created_at, updated_at)
            SELECT
                1, name, enabled, system_prompt, provider_id, model, mode,
                max_iterations, created_at, updated_at
            FROM agents
            ORDER BY
                CASE WHEN is_default = true AND deleted_at IS NULL THEN 0 ELSE 1 END,
                id
            LIMIT 1
            """
        )
    )

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_index("ix_conversations_agent_id")
        batch_op.drop_constraint("fk_conversations_agent_id_agents", type_="foreignkey")
        batch_op.drop_column("agent_id")

    op.drop_index("ix_agent_api_keys_key_prefix", table_name="agent_api_keys")
    op.drop_index("ix_agent_api_keys_agent_id", table_name="agent_api_keys")
    op.drop_table("agent_api_keys")
    op.drop_index("ix_agent_skills_skill_id", table_name="agent_skills")
    op.drop_table("agent_skills")
    op.drop_index("uq_agents_active_default", table_name="agents")
    op.drop_index("ix_agents_provider_id", table_name="agents")
    op.drop_table("agents")
