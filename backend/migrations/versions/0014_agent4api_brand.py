"""Rename shipped user-visible Agent defaults to Agent4API."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_agent4api_brand"
down_revision: str | Sequence[str] | None = "0013_agent_embeds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_NAME = "Chat4Openapi Agent"
NEW_NAME = "Agent4API Agent"
OLD_PROMPT_PREFIX = "You are Chat4Openapi Agent,"
NEW_PROMPT_PREFIX = "You are Agent4API Agent,"


def _rename(old_name: str, new_name: str, old_prefix: str, new_prefix: str) -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE agents SET name = :new_name WHERE name = :old_name"),
        {"old_name": old_name, "new_name": new_name},
    )
    connection.execute(
        sa.text(
            "UPDATE agents SET system_prompt = :new_prefix || "
            "substr(system_prompt, length(:old_prefix) + 1) "
            "WHERE substr(system_prompt, 1, length(:old_prefix)) = :old_prefix"
        ),
        {"old_prefix": old_prefix, "new_prefix": new_prefix},
    )


def upgrade() -> None:
    _rename(OLD_NAME, NEW_NAME, OLD_PROMPT_PREFIX, NEW_PROMPT_PREFIX)


def downgrade() -> None:
    _rename(NEW_NAME, OLD_NAME, NEW_PROMPT_PREFIX, OLD_PROMPT_PREFIX)
