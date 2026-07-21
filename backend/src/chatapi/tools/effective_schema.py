from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatapi.models import Tool, ToolParameterOverride


def effective_input_schema(db: Session, tool: Tool) -> dict[str, Any]:
    schema = deepcopy(tool.input_schema)
    properties = schema.setdefault("properties", {})
    overrides = db.scalars(
        select(ToolParameterOverride).where(ToolParameterOverride.tool_id == tool.id)
    ).all()
    for override in overrides:
        parameter = properties.get(override.argument_name)
        if not isinstance(parameter, dict):
            continue
        if override.description is not None:
            parameter["description"] = override.description
        if override.example is not None:
            parameter["example"] = override.example
    return schema


def reconcile_parameter_overrides(db: Session, tool: Tool) -> None:
    properties = tool.input_schema.get("properties", {})
    argument_names = set(properties) if isinstance(properties, dict) else set()
    overrides = db.scalars(
        select(ToolParameterOverride).where(ToolParameterOverride.tool_id == tool.id)
    ).all()
    for override in overrides:
        if override.argument_name not in argument_names:
            db.delete(override)
