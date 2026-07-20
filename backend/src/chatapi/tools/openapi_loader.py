from copy import deepcopy
from typing import Any

import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from chatapi.tools.openapi_v2 import convert_swagger_v2

MAX_OPENAPI_BYTES = 5 * 1024 * 1024


class OpenAPIImportError(ValueError):
    pass


def _reject_external_refs(value: Any) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#/"):
            raise OpenAPIImportError("External references are not supported")
        for item in value.values():
            _reject_external_refs(item)
    elif isinstance(value, list):
        for item in value:
            _reject_external_refs(item)


def load_openapi(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_OPENAPI_BYTES:
        raise OpenAPIImportError("OpenAPI document is too large")
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise OpenAPIImportError("OpenAPI document is not valid JSON or YAML") from exc
    if not isinstance(document, dict):
        raise OpenAPIImportError("OpenAPI document must be an object")
    _reject_external_refs(document)
    try:
        validate(document)
    except OpenAPIValidationError as exc:
        raise OpenAPIImportError(f"Invalid OpenAPI document: {exc}") from exc
    return document


def normalize_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    if str(spec.get("swagger", "")).startswith("2."):
        normalized = convert_swagger_v2(spec)
        try:
            validate(normalized)
        except OpenAPIValidationError as exc:
            raise OpenAPIImportError(f"Unable to normalize Swagger document: {exc}") from exc
        return normalized
    if str(spec.get("openapi", "")).startswith("3."):
        return deepcopy(spec)
    raise OpenAPIImportError("Only Swagger 2.0 and OpenAPI 3.x documents are supported")
