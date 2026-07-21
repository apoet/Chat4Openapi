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


def test_ignores_broken_named_references_from_swagger_generators() -> None:
    spec = fixture_bytes("openapi3.yaml").replace(
        b'"#/components/schemas/Pet"',
        b'"Error-ModelName{namespace=\'java.time\', name=\'LocalDateTime\'}"',
        1,
    )

    document = load_openapi(spec)

    response_schema = document["paths"]["/pets"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert response_schema == {}


def test_normalizes_swagger_header_parameters_missing_a_type() -> None:
    spec = fixture_bytes("openapi2.yaml").replace(b"\r\n", b"\n").replace(
        b"        - name: trace\n          in: query\n          required: false\n          type: string",
        b"        - name: tenant-id\n          in: header\n          required: false",
        1,
    )

    normalized = normalize_openapi(load_openapi(spec))

    parameter = normalized["paths"]["/pets"]["post"]["parameters"][0]
    assert parameter == {
        "name": "tenant-id",
        "in": "header",
        "required": False,
        "schema": {},
    }


def test_normalizes_misplaced_swagger_file_parameters() -> None:
    spec = fixture_bytes("openapi2.yaml").replace(
        b"          type: string",
        b"          type: file",
        1,
    )

    normalized = normalize_openapi(load_openapi(spec))

    schema = normalized["paths"]["/pets"]["post"]["parameters"][0]["schema"]
    assert schema == {"type": "string", "format": "binary"}


def test_escapes_slashes_in_swagger_definition_references() -> None:
    spec = load_openapi(fixture_bytes("openapi2.yaml"))
    spec["definitions"]["Pet/Input"] = spec["definitions"]["PetInput"]
    spec["paths"]["/pets"]["post"]["parameters"][1]["schema"]["$ref"] = (
        "#/definitions/Pet/Input"
    )

    normalized = normalize_openapi(spec)

    reference = normalized["paths"]["/pets"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert reference == "#/components/schemas/Pet~1Input"


def test_aligns_a_single_mismatched_swagger_path_parameter() -> None:
    spec = load_openapi(fixture_bytes("openapi2.yaml"))
    spec["paths"]["/pets/{petId}"] = spec["paths"].pop("/pets")
    parameter = spec["paths"]["/pets/{petId}"]["post"]["parameters"][0]
    parameter.update({"name": "varId", "in": "path", "required": True})

    normalized = normalize_openapi(spec)

    converted = normalized["paths"]["/pets/{petId}"]["post"]["parameters"][0]
    assert converted["name"] == "petId"


def test_drops_extra_swagger_path_parameters_not_in_the_path() -> None:
    spec = load_openapi(fixture_bytes("openapi2.yaml"))
    spec["paths"]["/pets/{petId}"] = spec["paths"].pop("/pets")
    parameters = spec["paths"]["/pets/{petId}"]["post"]["parameters"]
    parameters[0].update({"name": "petId", "in": "path", "required": True})
    parameters.insert(
        1,
        {"name": "varId", "in": "path", "required": True, "type": "string"},
    )

    normalized = normalize_openapi(spec)

    converted = normalized["paths"]["/pets/{petId}"]["post"]["parameters"]
    assert [item["name"] for item in converted] == ["petId"]


def test_uses_the_import_url_scheme_when_swagger_omits_schemes() -> None:
    spec = load_openapi(fixture_bytes("openapi2.yaml"))
    spec.pop("schemes")

    normalized = normalize_openapi(
        spec, source_url="http://localhost:48080/v2/api-docs"
    )

    assert normalized["servers"] == [{"url": "http://api.example.test/v1"}]


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
