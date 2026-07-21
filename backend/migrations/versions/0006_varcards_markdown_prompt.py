"""Upgrade the Varcards2-Gene default Markdown response contract."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_varcards_markdown_prompt"
down_revision: str | Sequence[str] | None = "0005_agent_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_PROMPT = (
    "你是 Varcards2 Gene 助手。用户询问基因的染色体或位点时，必须调用 "
    "{{tool:getInfoGeneInfoHSByGeneSymbolUsingGET}}，只传 geneSymbol，不要传 tenant-id；"
    "使用返回的 chromosome 和 map_location 回答。用户明确询问 SNV/变异明细时，再调用 "
    "{{tool:geneSymbolPageUsingPOST}}。回答使用用户提问的语言，并清楚标注参考基因组信息"
    "是否由接口提供。"
)
TABLE_RULE = """For a gene locus query, return a Markdown table with columns Field and Result.
Include Gene symbol, Chromosome, and Cytogenetic location when the Tool returns them.
Do not infer a reference build; state "Not provided by the API" when absent.
Add a short data-source note after the table."""
MARKDOWN_PROMPT = f"{LEGACY_PROMPT}\n\n{TABLE_RULE}"


def _replace_prompt(current: str, replacement: str) -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE skills
            SET system_prompt = :replacement
            WHERE name = 'Varcards2-Gene'
              AND deleted_at IS NULL
              AND system_prompt = :current
            """
        ),
        {"current": current, "replacement": replacement},
    )


def upgrade() -> None:
    _replace_prompt(LEGACY_PROMPT, MARKDOWN_PROMPT)


def downgrade() -> None:
    _replace_prompt(MARKDOWN_PROMPT, LEGACY_PROMPT)
