from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from chat4openapi.tools.openapi_v2 import convert_swagger_v2

MAX_OPENAPI_BYTES = 5 * 1024 * 1024


class OpenAPIImportError(ValueError):
    pass


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
        return document
    try:
        validate(document)
    except OpenAPIValidationError as exc:
        raise OpenAPIImportError(f"Invalid OpenAPI document: {exc}") from exc
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
        try:
            validate(normalized)
        except OpenAPIValidationError as exc:
            raise OpenAPIImportError(f"Unable to normalize Swagger document: {exc}") from exc
        return normalized
    if str(spec.get("openapi", "")).startswith("3."):
        return deepcopy(spec)
    raise OpenAPIImportError("Only Swagger 2.0 and OpenAPI 3.x documents are supported")
