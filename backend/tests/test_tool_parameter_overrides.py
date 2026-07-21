from sqlalchemy.orm import Session, sessionmaker

from chatapi.models import ApiSource, Tool, ToolParameterOverride
from chatapi.tools.effective_schema import (
    effective_input_schema,
    reconcile_parameter_overrides,
)


def make_tool(session: Session) -> Tool:
    source = ApiSource(
        name="Gene API",
        source_type="openapi",
        base_url="https://api.test",
    )
    session.add(source)
    session.flush()
    tool = Tool(
        api_source_id=source.id,
        operation_key="GET /genes/{gene}",
        name="get_gene",
        input_schema={
            "type": "object",
            "properties": {
                "gene": {"type": "string", "description": "Swagger text"}
            },
            "required": ["gene"],
        },
        execution_schema={
            "method": "GET",
            "path": "/genes/{gene}",
            "parameters": [],
        },
    )
    session.add(tool)
    session.flush()
    return tool


def test_effective_input_schema_merges_parameter_guidance_without_changing_structure(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        tool = make_tool(session)
        session.add(
            ToolParameterOverride(
                tool_id=tool.id,
                argument_name="gene",
                description="HGNC gene symbol",
                example="ABCA4",
            )
        )
        session.flush()

        effective = effective_input_schema(session, tool)

        assert effective["properties"]["gene"] == {
            "type": "string",
            "description": "HGNC gene symbol",
            "example": "ABCA4",
        }
        assert effective["required"] == ["gene"]
        assert tool.input_schema["properties"]["gene"] == {
            "type": "string",
            "description": "Swagger text",
        }


def test_reconcile_preserves_guidance_for_an_argument_that_still_exists(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        tool = make_tool(session)
        override = ToolParameterOverride(
            tool_id=tool.id,
            argument_name="gene",
            description="HGNC gene symbol",
            example="ABCA4",
        )
        session.add(override)
        session.flush()
        override_id = override.id
        tool.input_schema = {
            "type": "object",
            "properties": {"gene": {"type": "string", "description": "Updated Swagger"}},
            "required": ["gene"],
        }

        reconcile_parameter_overrides(session, tool)
        session.flush()

        preserved = session.get(ToolParameterOverride, override_id)
        assert preserved is not None
        assert preserved.description == "HGNC gene symbol"
        assert preserved.example == "ABCA4"


def test_reconcile_deletes_guidance_for_an_argument_removed_by_refresh(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        tool = make_tool(session)
        override = ToolParameterOverride(
            tool_id=tool.id,
            argument_name="gene",
            description="HGNC gene symbol",
        )
        session.add(override)
        session.flush()
        override_id = override.id
        tool.input_schema = {"type": "object", "properties": {}}

        reconcile_parameter_overrides(session, tool)
        session.flush()

        assert session.get(ToolParameterOverride, override_id) is None
