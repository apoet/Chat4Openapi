import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp.server.providers.openapi import MCPType, OpenAPIProvider, RouteMap

from chatapi.tools.openapi_v2 import HTTP_METHODS


@dataclass(frozen=True, slots=True)
class ToolCandidate:
    operation_key: str
    name: str
    description: str
    input_schema: dict[str, Any]
    execution_schema: dict[str, Any]


def _generated_name(method: str, path: str) -> str:
    parts: list[str] = [method.lower()]
    for segment in path.strip("/").split("/"):
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            parts.extend(("by", segment[1:-1]))
        else:
            parts.append(segment)
    return re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9_]", "_", "_".join(parts))).strip("_")


def _prepare_operations(spec: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any]]]]:
    prepared = deepcopy(spec)
    operations: list[tuple[str, str, dict[str, Any]]] = []
    used: dict[str, int] = {}
    for path, path_item in prepared.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            base_name = operation.get("operationId") or _generated_name(method, path)
            count = used.get(base_name, 0) + 1
            used[base_name] = count
            name = base_name if count == 1 else f"{base_name}_{count}"
            operation["operationId"] = name
            operations.append((path, method.lower(), operation))
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
        if body_arguments:
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
