from chatapi.skills.defaults import VARCARDS2_GENE_SYSTEM_PROMPT


def test_varcards2_gene_default_prompt_requires_a_stable_markdown_table() -> None:
    assert (
        "For a gene locus query, return a Markdown table with columns Field and Result."
        in VARCARDS2_GENE_SYSTEM_PROMPT
    )
    assert (
        "Include Gene symbol, Chromosome, and Cytogenetic location when the Tool returns them."
        in VARCARDS2_GENE_SYSTEM_PROMPT
    )
    assert (
        'Do not infer a reference build; state "Not provided by the API" when absent.'
        in VARCARDS2_GENE_SYSTEM_PROMPT
    )
    assert "Add a short data-source note after the table." in VARCARDS2_GENE_SYSTEM_PROMPT
