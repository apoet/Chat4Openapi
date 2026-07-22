import json
from typing import Any


def encode_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


def run_started(thread_id: str, run_id: str) -> dict[str, Any]:
    return {"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id}


def run_finished(thread_id: str, run_id: str) -> dict[str, Any]:
    return {"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id}


def run_error(message: str, code: str) -> dict[str, Any]:
    return {"type": "RUN_ERROR", "message": message, "code": code}


def text_message_start(message_id: str) -> dict[str, Any]:
    return {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"}


def text_message_content(message_id: str, delta: str) -> dict[str, Any]:
    return {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": delta}


def text_message_end(message_id: str) -> dict[str, Any]:
    return {"type": "TEXT_MESSAGE_END", "messageId": message_id}


def tool_call_start(
    tool_call_id: str,
    tool_name: str,
    parent_message_id: str,
) -> dict[str, Any]:
    return {
        "type": "TOOL_CALL_START",
        "toolCallId": tool_call_id,
        "toolCallName": tool_name,
        "parentMessageId": parent_message_id,
    }


def tool_call_args(tool_call_id: str, delta: str) -> dict[str, Any]:
    return {"type": "TOOL_CALL_ARGS", "toolCallId": tool_call_id, "delta": delta}


def tool_call_end(tool_call_id: str) -> dict[str, Any]:
    return {"type": "TOOL_CALL_END", "toolCallId": tool_call_id}


def custom_event(name: str, value: Any) -> dict[str, Any]:
    return {"type": "CUSTOM", "name": name, "value": value}
