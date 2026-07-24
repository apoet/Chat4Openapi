import hashlib
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp.server.providers.openapi import MCPType, OpenAPIProvider, RouteMap

from chat4openapi.tools.openapi_v2 import HTTP_METHODS


@dataclass(frozen=True, slots=True)
class ToolCandidate:
    operation_key: str
    name: str
    description: str
    input_schema: dict[str, Any]
    execution_schema: dict[str, Any]


MAX_FASTMCP_TOOL_NAME_LENGTH = 56
_SAFE_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _generated_name(index: int, method: str, path: str) -> str:
    operation_key = f"{method.upper()} {path}"
    digest = hashlib.sha256(operation_key.encode()).hexdigest()[:6]
    return f"op_{index:04d}_{digest}"


def _prepare_operations(
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any]]]]:
    prepared = deepcopy(spec)
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in prepared.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operations.append((path, method.lower(), operation))

    supplied_names = Counter(
        operation.get("operationId")
        for _, _, operation in operations
        if isinstance(operation.get("operationId"), str)
    )
    for index, (path, method, operation) in enumerate(operations, start=1):
        supplied_name = operation.get("operationId")
        name_is_compatible = (
            isinstance(supplied_name, str)
            and len(supplied_name) <= MAX_FASTMCP_TOOL_NAME_LENGTH
            and _SAFE_TOOL_NAME.fullmatch(supplied_name) is not None
            and supplied_names[supplied_name] == 1
        )
        name = supplied_name if name_is_compatible else _generated_name(index, method, path)
        operation["operationId"] = name
    return prepared, operations


def _execution_schema(
    path: str,
    method: str,
    operation: dict[str, Any],
    path_item: dict[str, Any],
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    parameters = []
    for parameter in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        parameters.append(
            {
                "name": parameter.get("name"),
                "in": parameter.get("in"),
                "required": parameter.get("required", False),
                "argument": parameter.get("name"),
            }
        )
    result: dict[str, Any] = {"method": method.upper(), "path": path, "parameters": parameters}
    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        content_type = "application/json" if "application/json" in content else next(iter(content), None)
        parameter_arguments = {item["argument"] for item in parameters}
        body_arguments = [
            name for name in input_schema.get("properties", {}) if name not in parameter_arguments
        ]
        if body_arguments == ["body"]:
            # Swagger 2 body parameters are normalized to one `body` argument by
            # FastMCP. Send that value as the request body itself instead of
            # wrapping it again as {"body": ...}.
            result["request_body"] = {
                "content_type": content_type,
                "argument": "body",
            }
        elif body_arguments:
            result["request_body"] = {
                "content_type": content_type,
                "arguments": body_arguments,
            }
        else:
            result["request_body"] = {"content_type": content_type, "argument": "body"}
    return result


async def build_candidates(spec: dict[str, Any], base_url: str) -> list[ToolCandidate]:
    prepared, operations = _prepare_operations(spec)
    client = httpx.AsyncClient(base_url=base_url)
    try:
        provider = OpenAPIProvider(
            prepared,
            client,
            route_maps=[RouteMap(methods="*", pattern=r".*", mcp_type=MCPType.TOOL)],
        )
        provider_tools = {tool.name: tool for tool in await provider.list_tools()}
        candidates: list[ToolCandidate] = []
        for path, method, operation in operations:
            name = operation["operationId"]
            provider_tool = provider_tools[name]
            input_schema = deepcopy(provider_tool.parameters)
            candidates.append(
                ToolCandidate(
                    operation_key=f"{method.upper()} {path}",
                    name=name,
                    description=provider_tool.description or f"Executes {method.upper()} {path}",
                    input_schema=input_schema,
                    execution_schema=_execution_schema(
                        path, method, operation, prepared["paths"][path], input_schema
                    ),
                )
            )
        return candidates
    finally:
        await client.aclose()
