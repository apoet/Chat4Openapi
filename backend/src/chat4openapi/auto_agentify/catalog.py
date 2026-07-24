import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from chat4openapi.tools.candidates import ToolCandidate

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


@dataclass(frozen=True, slots=True)
class BodySchemaIssue:
    operation_key: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class OperationCatalogItem:
    operation_key: str
    name: str
    method: str
    path: str
    tags: tuple[str, ...]
    summary: str
    description: str
    input_fields: tuple[str, ...]

    def as_prompt_data(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def _resolve_local_schema(
    schema: Any,
    spec: dict[str, Any],
    *,
    depth: int = 0,
) -> dict[str, Any]:
    if not isinstance(schema, dict) or depth > 8:
        return {}
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    current: Any = spec
    for part in reference[2:].split("/"):
        if not isinstance(current, dict):
            return {}
        current = current.get(part.replace("~1", "/").replace("~0", "~"))
    return _resolve_local_schema(current, spec, depth=depth + 1)


def _body_schema_reasons(
    schema: Any,
    spec: dict[str, Any],
) -> tuple[str, ...]:
    resolved = _resolve_local_schema(schema, spec)
    if not resolved:
        return ("missing_schema",)
    for composition in ("allOf", "oneOf", "anyOf"):
        branches = resolved.get(composition)
        if isinstance(branches, list) and branches:
            branch_reasons = [
                _body_schema_reasons(branch, spec) for branch in branches
            ]
            if any(not reasons for reasons in branch_reasons):
                return ()
            return min(branch_reasons, key=len)
    if resolved.get("type") == "array":
        item_reasons = _body_schema_reasons(resolved.get("items"), spec)
        return (
            ("missing_item_schema",)
            if item_reasons == ("missing_schema",)
            else item_reasons
        )
    properties = resolved.get("properties")
    is_object = resolved.get("type") == "object" or isinstance(properties, dict)
    if not is_object:
        return () if resolved.get("type") else ("missing_schema",)
    if not isinstance(properties, dict) or not properties:
        return ("missing_properties",)
    missing_types = 0
    missing_descriptions = 0
    for field_schema in properties.values():
        field = _resolve_local_schema(field_schema, spec)
        if not field or not any(
            key in field
            for key in ("type", "$ref", "allOf", "oneOf", "anyOf", "properties")
        ):
            missing_types += 1
        if not _clean_text(field.get("description"), 500):
            missing_descriptions += 1
    reasons: list[str] = []
    if missing_types:
        reasons.append("missing_field_types")
    if missing_descriptions * 2 >= len(properties):
        reasons.append("missing_field_descriptions")
    return tuple(reasons)


def find_body_schema_issues(spec: dict[str, Any]) -> list[BodySchemaIssue]:
    issues: list[BodySchemaIssue] = []
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_reasons: list[str] = []
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if not isinstance(content, dict) or not content:
                    operation_reasons.append("missing_schema")
                else:
                    json_media = next(
                        (
                            media
                            for content_type, media in content.items()
                            if isinstance(content_type, str)
                            and (
                                content_type.split(";", 1)[0]
                                .strip()
                                .endswith("/json")
                                or "+json"
                                in content_type.split(";", 1)[0]
                            )
                        ),
                        None,
                    )
                    media = json_media or next(
                        (
                            item
                            for item in content.values()
                            if isinstance(item, dict)
                        ),
                        {},
                    )
                    operation_reasons.extend(
                        _body_schema_reasons(media.get("schema"), spec)
                    )
            parameters = [
                *(
                    path_item.get("parameters", [])
                    if isinstance(path_item.get("parameters"), list)
                    else []
                ),
                *(
                    operation.get("parameters", [])
                    if isinstance(operation.get("parameters"), list)
                    else []
                ),
            ]
            for raw_parameter in parameters:
                parameter = _resolve_local_schema(raw_parameter, spec)
                schema = _resolve_local_schema(parameter.get("schema"), spec)
                schema_type = str(schema.get("type", "")).casefold()
                schema_format = str(schema.get("format", "")).casefold()
                named_body = str(parameter.get("name", "")).casefold() == "body"
                is_body_like = (
                    parameter.get("in") == "body"
                    or named_body
                    or schema_type in {"object", "json"}
                    or schema_format == "json"
                )
                if not is_body_like:
                    continue
                parameter_reasons = list(_body_schema_reasons(schema, spec))
                if (
                    not parameter_reasons
                    and (named_body or schema_type == "json" or schema_format == "json")
                    and schema_type not in {"object", "array"}
                ):
                    parameter_reasons.append("missing_schema")
                operation_reasons.extend(parameter_reasons)
            reasons = tuple(dict.fromkeys(operation_reasons))
            if reasons:
                issues.append(
                    BodySchemaIssue(
                        operation_key=f"{method.upper()} {path}",
                        reasons=reasons,
                    )
                )
    return issues


def find_candidate_schema_issues(
    candidates: Sequence[ToolCandidate],
) -> list[BodySchemaIssue]:
    issues: list[BodySchemaIssue] = []
    for candidate in candidates:
        properties = candidate.input_schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        schemas: list[Any] = []
        request_body = candidate.execution_schema.get("request_body")
        if isinstance(request_body, dict):
            argument = request_body.get("argument")
            arguments = request_body.get("arguments")
            if isinstance(argument, str):
                schemas.append(properties.get(argument))
            elif isinstance(arguments, list):
                schemas.append(
                    {
                        "type": "object",
                        "properties": {
                            name: properties.get(name)
                            for name in arguments
                            if isinstance(name, str)
                        },
                    }
                )
            else:
                schemas.append(None)
        for parameter in candidate.execution_schema.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            argument = parameter.get("argument")
            parameter_schema = properties.get(argument)
            schema_type = (
                str(parameter_schema.get("type", "")).casefold()
                if isinstance(parameter_schema, dict)
                else ""
            )
            schema_format = (
                str(parameter_schema.get("format", "")).casefold()
                if isinstance(parameter_schema, dict)
                else ""
            )
            if (
                parameter.get("in") == "body"
                or str(parameter.get("name", "")).casefold() == "body"
                or schema_type in {"object", "json"}
                or schema_format == "json"
            ):
                schemas.append(parameter_schema)
        if not schemas:
            for name, schema in properties.items():
                if not isinstance(schema, dict):
                    continue
                if (
                    str(name).casefold() == "body"
                    or str(schema.get("type", "")).casefold() == "json"
                    or str(schema.get("format", "")).casefold() == "json"
                ):
                    schemas.append(schema)
        reasons = tuple(
            dict.fromkeys(
                reason
                for schema in schemas
                for reason in _body_schema_reasons(schema, {})
            )
        )
        if reasons:
            issues.append(
                BodySchemaIssue(
                    operation_key=candidate.operation_key,
                    reasons=reasons,
                )
            )
    return issues


def candidate_needs_schema_review(candidate: ToolCandidate) -> bool:
    return bool(find_candidate_schema_issues([candidate]))


def build_operation_catalog(
    spec: dict[str, Any],
    candidates: Sequence[ToolCandidate],
) -> list[OperationCatalogItem]:
    operations: dict[str, dict[str, Any]] = {}
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if isinstance(operation, dict):
                operations[f"{method.upper()} {path}"] = operation

    items: list[OperationCatalogItem] = []
    for candidate in candidates:
        method, path = candidate.operation_key.split(" ", 1)
        operation = operations.get(candidate.operation_key, {})
        properties = candidate.input_schema.get("properties", {})
        fields = tuple(str(name)[:160] for name in properties) if isinstance(properties, dict) else ()
        raw_tags = operation.get("tags", [])
        tags = tuple(
            _clean_text(tag, 160)
            for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        )
        items.append(
            OperationCatalogItem(
                operation_key=candidate.operation_key,
                name=candidate.name,
                method=method,
                path=path,
                tags=tags,
                summary=_clean_text(operation.get("summary"), 500),
                description=_clean_text(
                    operation.get("description") or candidate.description, 800
                ),
                input_fields=fields[:24],
            )
        )
    return items


def build_candidate_operation_catalog(
    candidates: Sequence[ToolCandidate],
) -> list[OperationCatalogItem]:
    items: list[OperationCatalogItem] = []
    for candidate in candidates:
        method, path = candidate.operation_key.split(" ", 1)
        properties = candidate.input_schema.get("properties", {})
        fields = (
            tuple(str(name)[:160] for name in properties)
            if isinstance(properties, dict)
            else ()
        )
        items.append(
            OperationCatalogItem(
                operation_key=candidate.operation_key,
                name=candidate.name,
                method=method,
                path=path,
                tags=(),
                summary="",
                description=_clean_text(candidate.description, 800),
                input_fields=fields[:24],
            )
        )
    return items


def catalog_batches(
    items: Sequence[OperationCatalogItem],
    maximum: int = 150,
) -> list[list[OperationCatalogItem]]:
    if maximum < 1:
        raise ValueError("maximum must be positive")
    ordered = sorted(items, key=lambda item: (item.tags, item.path, item.method))
    return [
        ordered[index : index + maximum]
        for index in range(0, len(ordered), maximum)
    ]


def catalog_analysis_domains(
    items: Sequence[OperationCatalogItem],
    maximum_chars: int = 60_000,
) -> list[list[OperationCatalogItem]]:
    if maximum_chars < 1:
        raise ValueError("maximum_chars must be positive")
    ordered = sorted(items, key=lambda item: (item.tags, item.path, item.method))
    if _catalog_chars(ordered) <= maximum_chars:
        return [ordered]

    domains: list[list[OperationCatalogItem]] = []
    current: list[OperationCatalogItem] = []
    current_tag: tuple[str, ...] | None = None
    for item in ordered:
        item_tag = item.tags[:1]
        if current and (
            item_tag != current_tag
            or _catalog_chars([*current, item]) > maximum_chars
        ):
            domains.append(current)
            current = []
        current.append(item)
        current_tag = item_tag
    if current:
        domains.append(current)
    return domains


def catalog_prompt_chars(items: Sequence[OperationCatalogItem]) -> int:
    return _catalog_chars(items)


def _catalog_chars(items: Sequence[OperationCatalogItem]) -> int:
    return len(
        json.dumps(
            [item.as_prompt_data() for item in items],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def is_high_impact(item: OperationCatalogItem) -> bool:
    return item.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
