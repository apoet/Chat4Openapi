import json
from pathlib import Path

import pytest

from chatapi.tools.candidates import build_candidates
from chatapi.tools.openapi_loader import OpenAPIImportError, load_openapi, normalize_openapi

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_loads_json_and_yaml_and_rejects_oversized_documents() -> None:
    yaml_spec = load_openapi(fixture_bytes("openapi3.yaml"))
    json_spec = load_openapi(json.dumps(yaml_spec).encode())

    assert yaml_spec == json_spec
    with pytest.raises(OpenAPIImportError, match="too large"):
        load_openapi(b" " * (5 * 1024 * 1024 + 1))


def test_rejects_external_references() -> None:
    spec = fixture_bytes("openapi3.yaml").replace(
        b'"#/components/schemas/PetInput"', b'"https://example.test/Pet.yaml"', 1
    )

    with pytest.raises(OpenAPIImportError, match="External references"):
        load_openapi(spec)


def test_normalizes_swagger_body_query_and_internal_refs() -> None:
    normalized = normalize_openapi(load_openapi(fixture_bytes("openapi2.yaml")))
    operation = normalized["paths"]["/pets"]["post"]

    assert normalized["openapi"] == "3.0.3"
    assert normalized["servers"] == [{"url": "https://api.example.test/v1"}]
    assert operation["parameters"][0] == {
        "name": "trace",
        "in": "query",
        "required": False,
        "schema": {"type": "string"},
    }
    body = operation["requestBody"]
    assert body["required"] is True
    assert body["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/PetInput"
    )
    assert normalized["components"]["schemas"]["Pet"]["allOf"][0]["$ref"] == (
        "#/components/schemas/PetInput"
    )


@pytest.mark.asyncio
async def test_swagger_and_openapi_build_equivalent_fastmcp_candidates() -> None:
    swagger = normalize_openapi(load_openapi(fixture_bytes("openapi2.yaml")))
    openapi = normalize_openapi(load_openapi(fixture_bytes("openapi3.yaml")))

    swagger_candidates = await build_candidates(swagger, "https://api.example.test/v1")
    openapi_candidates = await build_candidates(openapi, "https://api.example.test/v1")

    assert len(swagger_candidates) == len(openapi_candidates) == 1
    left, right = swagger_candidates[0], openapi_candidates[0]
    assert left.operation_key == right.operation_key == "POST /pets"
    assert left.name == right.name == "createPet"
    assert left.input_schema == right.input_schema
    assert left.input_schema["type"] == "object"
    assert {"trace", "name"} <= set(left.input_schema["properties"])
    assert left.execution_schema == right.execution_schema
    assert left.execution_schema["parameters"][0]["in"] == "query"
    assert left.execution_schema["request_body"]["arguments"] == ["name"]


@pytest.mark.asyncio
async def test_candidate_names_are_deterministic_and_unique_without_operation_ids() -> None:
    spec = load_openapi(fixture_bytes("openapi3.yaml"))
    operation = spec["paths"]["/pets"]["post"]
    operation.pop("operationId")
    spec["paths"]["/pets/{id}"] = {
        "post": {
            **operation,
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
        }
    }

    candidates = await build_candidates(spec, "https://api.example.test/v1")

    assert [candidate.name for candidate in candidates] == ["post_pets", "post_pets_by_id"]
