from chat4openapi.auto_agentify.catalog import (
    OperationCatalogItem,
    build_operation_catalog,
    catalog_batches,
    find_body_schema_issues,
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


def test_default_batches_reduce_large_api_round_trips() -> None:
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
        for index in range(151)
    ]

    assert [len(batch) for batch in catalog_batches(items)] == [150, 1]


def test_catalog_limits_prompt_only_description_and_input_field_size() -> None:
    properties = {
        f"field_{index}": {"type": "string"}
        for index in range(40)
    }
    candidate = ToolCandidate(
        operation_key="GET /projects/0",
        name="getProject0",
        description="fallback",
        input_schema={"type": "object", "properties": properties},
        execution_schema={},
    )
    spec = {
        "paths": {
            "/projects/0": {
                "get": {
                    "tags": ["Projects"],
                    "description": "x" * 1_200,
                }
            }
        }
    }

    item = build_operation_catalog(spec, [candidate])[0]

    assert len(item.description) == 800
    assert len(item.input_fields) == 24


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


def test_finds_missing_and_underspecified_json_body_schemas() -> None:
    spec = {
        "paths": {
            "/missing": {
                "post": {
                    "requestBody": {
                        "content": {"application/json": {}},
                    }
                }
            },
            "/vague": {
                "patch": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        }
                    }
                }
            },
        }
    }

    issues = find_body_schema_issues(spec)

    assert [issue.operation_key for issue in issues] == [
        "POST /missing",
        "PATCH /vague",
    ]
    assert issues[0].reasons == ("missing_schema",)
    assert issues[1].reasons == (
        "missing_field_types",
        "missing_field_descriptions",
    )


def test_accepts_detailed_referenced_json_body_schema() -> None:
    spec = {
        "components": {
            "schemas": {
                "ProjectInput": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-readable project name.",
                        },
                        "status": {
                            "type": "string",
                            "description": "Current lifecycle state.",
                        },
                    },
                }
            }
        },
        "paths": {
            "/projects": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ProjectInput"
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    assert find_body_schema_issues(spec) == []


def test_finds_body_named_and_json_formatted_parameters_without_structure() -> None:
    spec = {
        "paths": {
            "/legacy": {
                "post": {
                    "parameters": [
                        {
                            "name": "body",
                            "in": "body",
                            "schema": {"type": "object"},
                        }
                    ]
                }
            },
            "/encoded": {
                "post": {
                    "parameters": [
                        {
                            "name": "payload",
                            "in": "query",
                            "schema": {"type": "string", "format": "json"},
                        }
                    ]
                }
            },
        }
    }

    issues = find_body_schema_issues(spec)

    assert [(issue.operation_key, issue.reasons) for issue in issues] == [
        ("POST /legacy", ("missing_properties",)),
        ("POST /encoded", ("missing_schema",)),
    ]
