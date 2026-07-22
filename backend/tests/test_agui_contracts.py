import json

import pytest
from pydantic import ValidationError

from chat4openapi.agui.contracts import AguiRunInput, AguiTool


def _tool(**overrides: object) -> dict[str, object]:
    return {
        "name": "web__select-row",
        "description": "Select a row in the host page.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
        **overrides,
    }


def _run(**overrides: object) -> dict[str, object]:
    return {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": [{"id": "message-1", "role": "user", "content": "Select row 42"}],
        "tools": [_tool()],
        "context": [],
        **overrides,
    }


def test_run_input_accepts_standard_camel_case_fields() -> None:
    value = AguiRunInput.model_validate(_run())

    assert value.thread_id == "thread-1"
    assert value.run_id == "run-1"
    assert value.messages[0].role == "user"
    assert value.tools[0].name == "web__select-row"


@pytest.mark.parametrize("name", ["select-row", "web__", "web__bad name", "web__/path"])
def test_client_tool_requires_reserved_safe_name(name: str) -> None:
    with pytest.raises(ValidationError):
        AguiTool.model_validate(_tool(name=name))


def test_run_rejects_more_than_64_client_tools() -> None:
    tools = [_tool(name=f"web__tool-{index}") for index in range(65)]

    with pytest.raises(ValidationError) as error:
        AguiRunInput.model_validate(_run(tools=tools))

    assert error.value.errors()[0]["loc"] == ("tools",)


def test_run_rejects_catalog_larger_than_256_kib() -> None:
    tools = [
        _tool(name=f"web__tool-{index}", description="x" * 4096)
        for index in range(64)
    ]

    assert len(json.dumps(tools).encode()) > 256 * 1024
    with pytest.raises(ValidationError, match="catalog exceeds"):
        AguiRunInput.model_validate(_run(tools=tools))


def test_tool_rejects_schema_deeper_than_16_levels() -> None:
    schema: dict[str, object] = {"type": "string"}
    for _ in range(17):
        schema = {"type": "array", "items": schema}

    with pytest.raises(ValidationError, match="schema depth"):
        AguiTool.model_validate(_tool(parameters=schema))


def test_tool_rejects_schema_larger_than_64_kib() -> None:
    with pytest.raises(ValidationError, match="schema size"):
        AguiTool.model_validate(
            _tool(parameters={"type": "object", "description": "x" * (64 * 1024)})
        )
