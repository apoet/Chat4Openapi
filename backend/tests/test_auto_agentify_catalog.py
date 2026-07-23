from chat4openapi.auto_agentify.catalog import (
    OperationCatalogItem,
    build_operation_catalog,
    catalog_batches,
    is_high_impact,
)
from chat4openapi.tools.candidates import ToolCandidate


def _candidate(index: int, method: str = "GET") -> ToolCandidate:
    return ToolCandidate(
        operation_key=f"{method} /projects/{index}",
        name=f"{method.lower()}Project{index}",
        description=f"Operate on project {index}",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "verbose": {"type": "boolean"},
            },
        },
        execution_schema={},
    )


def test_builds_compact_catalog_from_openapi_operations() -> None:
    spec = {
        "paths": {
            "/projects/0": {
                "get": {
                    "operationId": "getProject0",
                    "tags": ["Projects"],
                    "summary": "Get a project",
                    "description": "Returns one project.",
                }
            }
        }
    }

    items = build_operation_catalog(spec, [_candidate(0)])

    assert items == [
        OperationCatalogItem(
            operation_key="GET /projects/0",
            name="getProject0",
            method="GET",
            path="/projects/0",
            tags=("Projects",),
            summary="Get a project",
            description="Returns one project.",
            input_fields=("project_id", "verbose"),
        )
    ]


def test_batches_catalog_deterministically_without_losing_operations() -> None:
    items = [
        OperationCatalogItem(
            operation_key=f"GET /projects/{index}",
            name=f"getProject{index}",
            method="GET",
            path=f"/projects/{index}",
            tags=("Projects",),
            summary="",
            description="",
            input_fields=(),
        )
        for index in range(201)
    ]

    batches = catalog_batches(list(reversed(items)), maximum=200)

    assert [len(batch) for batch in batches] == [200, 1]
    assert {item.operation_key for batch in batches for item in batch} == {
        item.operation_key for item in items
    }


def test_classifies_mutating_operations_as_high_impact() -> None:
    def item(method: str) -> OperationCatalogItem:
        return OperationCatalogItem(
            operation_key=f"{method} /projects/1",
            name="operation",
            method=method,
            path="/projects/1",
            tags=(),
            summary="",
            description="",
            input_fields=(),
        )

    assert is_high_impact(item("DELETE"))
    assert is_high_impact(item("POST"))
    assert is_high_impact(item("PUT"))
    assert is_high_impact(item("PATCH"))
    assert not is_high_impact(item("GET"))

