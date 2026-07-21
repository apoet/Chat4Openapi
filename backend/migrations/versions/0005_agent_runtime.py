"""Add Agent runtime persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_agent_runtime"
down_revision: str | Sequence[str] | None = "0004_api_source_refresh"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "name", sa.String(160), nullable=False, server_default="ChatAPI Agent"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column(
            "mode", sa.String(32), nullable=False, server_default="human_in_loop"
        ),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="8"),
        sa.CheckConstraint("id = 1", name="ck_single_agent_config"),
    )

    connection = op.get_bind()
    provider_id = connection.execute(
        sa.text(
            """
            SELECT id
            FROM llm_providers
            WHERE enabled = true AND deleted_at IS NULL
            ORDER BY id
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_config
                (id, name, enabled, system_prompt, provider_id, model, mode, max_iterations)
            VALUES
                (1, 'ChatAPI Agent', true, '', :provider_id, NULL, 'human_in_loop', 8)
            """
        ),
        {"provider_id": provider_id},
    )

    op.create_table(
        "tool_parameter_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tool_id",
            sa.Integer(),
            sa.ForeignKey("tools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("argument_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("example", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "tool_id", "argument_name", name="uq_tool_parameter_override"
        ),
    )
    op.create_index(
        "ix_tool_parameter_overrides_tool_id",
        "tool_parameter_overrides",
        ["tool_id"],
    )

    op.add_column(
        "conversations",
        sa.Column(
            "candidate_skill_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "loaded_skill_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "conversations", sa.Column("agent_mode", sa.String(32), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column(
            "agent_status",
            sa.String(32),
            nullable=False,
            server_default="running",
        ),
    )
    op.add_column(
        "conversations", sa.Column("pending_clarification", sa.JSON(), nullable=True)
    )

    with op.batch_alter_table("skills") as batch_op:
        batch_op.drop_index("ix_skills_provider_id")
        batch_op.drop_column("provider_id")
        batch_op.drop_column("model")


def downgrade() -> None:
    with op.batch_alter_table("skills") as batch_op:
        batch_op.add_column(sa.Column("provider_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(256), nullable=True))
        batch_op.create_foreign_key(
            "fk_skills_provider_id_llm_providers",
            "llm_providers",
            ["provider_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_skills_provider_id", ["provider_id"])

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("pending_clarification")
        batch_op.drop_column("agent_status")
        batch_op.drop_column("agent_mode")
        batch_op.drop_column("loaded_skill_ids")
        batch_op.drop_column("candidate_skill_ids")

    op.drop_index(
        "ix_tool_parameter_overrides_tool_id",
        table_name="tool_parameter_overrides",
    )
    op.drop_table("tool_parameter_overrides")
    op.drop_table("agent_config")
