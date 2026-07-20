from copy import deepcopy
from typing import Any
from urllib.parse import urlunsplit

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


def _rewrite_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/definitions/", "#/components/schemas/")
                if key == "$ref" and isinstance(item, str)
                else _rewrite_refs(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    return value


def _parameter_schema(parameter: dict[str, Any]) -> dict[str, Any]:
    schema_keys = {
        "type",
        "format",
        "items",
        "default",
        "enum",
        "maximum",
        "minimum",
        "maxLength",
        "minLength",
        "pattern",
        "maxItems",
        "minItems",
        "uniqueItems",
    }
    return {key: deepcopy(value) for key, value in parameter.items() if key in schema_keys}


def _convert_operation(
    operation: dict[str, Any],
    *,
    consumes: list[str],
    produces: list[str],
) -> dict[str, Any]:
    converted = {
        key: deepcopy(value)
        for key, value in operation.items()
        if key not in {"consumes", "produces", "parameters", "responses", "schemes"}
    }
    parameters: list[dict[str, Any]] = []
    body_parameter: dict[str, Any] | None = None
    form_parameters: list[dict[str, Any]] = []
    for parameter in operation.get("parameters", []):
        if "$ref" in parameter:
            parameters.append(deepcopy(parameter))
        elif parameter.get("in") == "body":
            body_parameter = parameter
        elif parameter.get("in") == "formData":
            form_parameters.append(parameter)
        else:
            converted_parameter = {
                key: deepcopy(value)
                for key, value in parameter.items()
                if key in {"name", "in", "description", "required", "deprecated", "allowEmptyValue"}
            }
            converted_parameter["schema"] = _parameter_schema(parameter)
            parameters.append(converted_parameter)
    if parameters:
        converted["parameters"] = parameters

    media_types = operation.get("consumes", consumes) or ["application/json"]
    if body_parameter is not None:
        schema = deepcopy(body_parameter.get("schema", {}))
        converted["requestBody"] = {
            "required": body_parameter.get("required", False),
            "content": {media_type: {"schema": deepcopy(schema)} for media_type in media_types},
        }
        if body_parameter.get("description"):
            converted["requestBody"]["description"] = body_parameter["description"]
    elif form_parameters:
        properties = {item["name"]: _parameter_schema(item) for item in form_parameters}
        required = [item["name"] for item in form_parameters if item.get("required")]
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        content_type = (
            "multipart/form-data"
            if "multipart/form-data" in media_types
            else "application/x-www-form-urlencoded"
        )
        converted["requestBody"] = {
            "required": bool(required),
            "content": {content_type: {"schema": schema}},
        }

    response_media_types = operation.get("produces", produces) or ["application/json"]
    responses: dict[str, Any] = {}
    for status, response in operation.get("responses", {}).items():
        converted_response = {
            key: deepcopy(value) for key, value in response.items() if key != "schema"
        }
        if "schema" in response:
            converted_response["content"] = {
                media_type: {"schema": deepcopy(response["schema"])}
                for media_type in response_media_types
            }
        responses[str(status)] = converted_response
    converted["responses"] = responses
    return converted


def convert_swagger_v2(spec: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(spec)
    schemes = source.get("schemes") or ["https"]
    host = source.get("host", "localhost")
    base_path = source.get("basePath", "")
    server_url = urlunsplit((schemes[0], host, base_path.rstrip("/"), "", ""))
    converted: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": deepcopy(source["info"]),
        "servers": [{"url": server_url}],
        "paths": {},
    }
    consumes = source.get("consumes", ["application/json"])
    produces = source.get("produces", ["application/json"])
    for path, path_item in source.get("paths", {}).items():
        converted_path: dict[str, Any] = {}
        for key, value in path_item.items():
            if key.lower() in HTTP_METHODS:
                converted_path[key.lower()] = _convert_operation(
                    value, consumes=consumes, produces=produces
                )
            else:
                converted_path[key] = deepcopy(value)
        converted["paths"][path] = converted_path
    components: dict[str, Any] = {}
    if source.get("definitions"):
        components["schemas"] = deepcopy(source["definitions"])
    if components:
        converted["components"] = components
    return _rewrite_refs(converted)
