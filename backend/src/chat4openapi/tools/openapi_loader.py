from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import yaml

from chat4openapi.tools.openapi_v2 import convert_swagger_v2

MAX_OPENAPI_BYTES = 5 * 1024 * 1024
SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


class OpenAPIImportError(ValueError):
    pass


def _sanitize_schema(schema: dict[str, Any]) -> None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type not in SCHEMA_TYPES:
        schema.pop("type")
    elif isinstance(schema_type, list):
        supported = [item for item in schema_type if item in SCHEMA_TYPES]
        if len(supported) == 1:
            schema["type"] = supported[0]
        elif not supported:
            schema.pop("type")

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for value in properties.values():
            if isinstance(value, dict):
                _sanitize_schema(value)

    for key in ("items", "additionalProperties", "not"):
        value = schema.get(key)
        if isinstance(value, dict):
            _sanitize_schema(value)

    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        value = schema.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _sanitize_schema(item)


def _sanitize_nonstandard_schema_types(value: Any) -> None:
    if isinstance(value, dict):
        schema = value.get("schema")
        if isinstance(schema, dict):
            _sanitize_schema(schema)
        for key in ("schemas", "definitions"):
            schemas = value.get(key)
            if isinstance(schemas, dict):
                for item in schemas.values():
                    if isinstance(item, dict):
                        _sanitize_schema(item)
        for item in value.values():
            _sanitize_nonstandard_schema_types(item)
    elif isinstance(value, list):
        for item in value:
            _sanitize_nonstandard_schema_types(item)


def _supply_missing_parameter_schemas(document: dict[str, Any]) -> None:
    parameter_lists: list[Any] = []
    components = document.get("components")
    if isinstance(components, dict):
        parameters = components.get("parameters")
        if isinstance(parameters, dict):
            parameter_lists.append(list(parameters.values()))

    paths = document.get("paths")
    if isinstance(paths, dict):
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            parameter_lists.append(path_item.get("parameters", []))
            for method in ("get", "put", "post", "delete", "options", "head", "patch", "trace"):
                operation = path_item.get(method)
                if isinstance(operation, dict):
                    parameter_lists.append(operation.get("parameters", []))

    for parameters in parameter_lists:
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if (
                isinstance(parameter, dict)
                and "$ref" not in parameter
                and isinstance(parameter.get("name"), str)
                and parameter.get("in") in {"query", "header", "path", "cookie"}
                and "schema" not in parameter
                and "content" not in parameter
            ):
                parameter["schema"] = {"type": "string"}


def _sanitize_references(value: Any) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#/"):
            lowered = reference.lower()
            if (
                "/" in reference
                or "#" in reference
                or lowered.endswith((".json", ".yaml", ".yml"))
            ):
                raise OpenAPIImportError("External references are not supported")
            value.pop("$ref")
        for item in value.values():
            _sanitize_references(item)
    elif isinstance(value, list):
        for item in value:
            _sanitize_references(item)


def load_openapi(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_OPENAPI_BYTES:
        raise OpenAPIImportError("OpenAPI document is too large")
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise OpenAPIImportError("OpenAPI document is not valid JSON or YAML") from exc
    if not isinstance(document, dict):
        raise OpenAPIImportError("OpenAPI document must be an object")
    _sanitize_references(document)
    if str(document.get("swagger", "")).startswith("2."):
        _sanitize_nonstandard_schema_types(document)
        return document
    if str(document.get("openapi", "")).startswith("3."):
        _supply_missing_parameter_schemas(document)
        _sanitize_nonstandard_schema_types(document)
    return document


def normalize_openapi(
    spec: dict[str, Any], *, source_url: str | None = None
) -> dict[str, Any]:
    if str(spec.get("swagger", "")).startswith("2."):
        source = deepcopy(spec)
        if source_url:
            parsed_source_url = urlsplit(source_url)
            if not source.get("schemes") and parsed_source_url.scheme in {"http", "https"}:
                source["schemes"] = [parsed_source_url.scheme]
            if not source.get("host") and parsed_source_url.netloc:
                source["host"] = parsed_source_url.netloc
        normalized = convert_swagger_v2(source)
        _sanitize_nonstandard_schema_types(normalized)
        return normalized
    if str(spec.get("openapi", "")).startswith("3."):
        normalized = deepcopy(spec)
        if source_url and not normalized.get("servers"):
            parsed_source_url = urlsplit(source_url)
            if (
                parsed_source_url.scheme in {"http", "https"}
                and parsed_source_url.netloc
            ):
                normalized["servers"] = [
                    {"url": f"{parsed_source_url.scheme}://{parsed_source_url.netloc}"}
                ]
        return normalized
    raise OpenAPIImportError("Only Swagger 2.0 and OpenAPI 3.x documents are supported")
