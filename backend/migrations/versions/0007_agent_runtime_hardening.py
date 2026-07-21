"""Harden Agent defaults, state, constraints, and Tool name scoping."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_agent_runtime_hardening"
down_revision: str | Sequence[str] | None = "0006_varcards_markdown_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_AGENT_PROMPT = (
    "You are ChatAPI Agent, the built-in assistant. Use the available Skills "
    "and Tools to help the user, and return clear Markdown responses."
)
DEFAULT_AGENT_PROMPT = """You are ChatAPI Agent, the built-in assistant.

Operating rules:
- Choose Skills only from the provided Skill catalog, using their declared names and descriptions.
- Always load a Skill before using its Tools.
- Never invent required Tool arguments or claim a Tool result that was not observed.
- In human-in-loop mode, ask the user to clarify material missing, ambiguous, or choice-dependent business inputs before making an unreliable call.
- In non-interactive ReAct mode, make a reasonable supported assumption when necessary and disclose it in the final response.
- Respond in the user's language.
- Prefer clear, structured Markdown, including tables for structured results.
- If retry attempts are exhausted, a Skill is unavailable, or Tool failures prevent completion, explain the limitation clearly and do not fabricate success."""


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE agent_config
            SET system_prompt = :replacement
            WHERE id = 1
              AND (trim(system_prompt) = '' OR system_prompt = :legacy)
            """
        ),
        {"replacement": DEFAULT_AGENT_PROMPT, "legacy": LEGACY_AGENT_PROMPT},
    )

    op.add_column(
        "agent_config",
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "agent_config",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    connection.execute(
        sa.text(
            "UPDATE agent_config SET created_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP"
        )
    )
    existing_checks = {
        item["name"]
        for item in sa.inspect(connection).get_check_constraints("agent_config")
    }
    with op.batch_alter_table("agent_config") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        )
        if "ck_agent_mode" not in existing_checks:
            batch_op.create_check_constraint(
                "ck_agent_mode", "mode IN ('human_in_loop', 'react')"
            )
        if "ck_agent_max_iterations" not in existing_checks:
            batch_op.create_check_constraint(
                "ck_agent_max_iterations", "max_iterations BETWEEN 2 AND 32"
            )

    op.add_column(
        "conversations",
        sa.Column(
            "candidate_scope_source",
            sa.String(32),
            nullable=False,
            server_default="automatic",
        ),
    )
    connection.execute(
        sa.text(
            "UPDATE conversations SET candidate_scope_source = 'explicit' "
            "WHERE skill_id IS NOT NULL"
        )
    )
    op.add_column(
        "conversations",
        sa.Column("latest_failure_summary", sa.Text(), nullable=True),
    )

    tool_uniques = sa.inspect(connection).get_unique_constraints("tools")
    if any(item["column_names"] == ["name"] for item in tool_uniques):
        with op.batch_alter_table(
            "tools", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
        ) as batch_op:
            batch_op.drop_constraint("uq_tools_name", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("tools") as batch_op:
        batch_op.create_unique_constraint("uq_tools_name", ["name"])

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("latest_failure_summary")
        batch_op.drop_column("candidate_scope_source")

    with op.batch_alter_table("agent_config") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
