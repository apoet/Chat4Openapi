from dataclasses import asdict, dataclass
from typing import Any, Sequence

from chat4openapi.tools.candidates import ToolCandidate


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
                    operation.get("description") or candidate.description, 2_000
                ),
                input_fields=fields[:128],
            )
        )
    return items


def catalog_batches(
    items: Sequence[OperationCatalogItem],
    maximum: int = 200,
) -> list[list[OperationCatalogItem]]:
    if maximum < 1:
        raise ValueError("maximum must be positive")
    ordered = sorted(items, key=lambda item: (item.tags, item.path, item.method))
    return [
        ordered[index : index + maximum]
        for index in range(0, len(ordered), maximum)
    ]


def is_high_impact(item: OperationCatalogItem) -> bool:
    return item.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}

