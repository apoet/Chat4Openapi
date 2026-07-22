from chat4openapi.agui.events import (
    custom_event,
    encode_sse,
    run_error,
    run_finished,
    run_started,
    text_message_content,
    text_message_end,
    text_message_start,
    tool_call_args,
    tool_call_end,
    tool_call_start,
)


def test_encode_sse_uses_compact_utf8_safe_json() -> None:
    assert encode_sse(
        {"type": "RUN_FINISHED", "threadId": "线程", "runId": "run-1"}
    ) == 'data: {"type":"RUN_FINISHED","threadId":"线程","runId":"run-1"}\n\n'


def test_lifecycle_and_text_event_factories_match_agui_fields() -> None:
    assert run_started("thread-1", "run-1") == {
        "type": "RUN_STARTED",
        "threadId": "thread-1",
        "runId": "run-1",
    }
    assert text_message_start("message-1") == {
        "type": "TEXT_MESSAGE_START",
        "messageId": "message-1",
        "role": "assistant",
    }
    assert text_message_content("message-1", "Hello") == {
        "type": "TEXT_MESSAGE_CONTENT",
        "messageId": "message-1",
        "delta": "Hello",
    }
    assert text_message_end("message-1") == {
        "type": "TEXT_MESSAGE_END",
        "messageId": "message-1",
    }
    assert run_finished("thread-1", "run-1") == {
        "type": "RUN_FINISHED",
        "threadId": "thread-1",
        "runId": "run-1",
    }
    assert run_error("message", "code") == {
        "type": "RUN_ERROR",
        "message": "message",
        "code": "code",
    }


def test_tool_and_custom_event_factories_match_agui_fields() -> None:
    assert tool_call_start("call-1", "web__select-row", "message-1") == {
        "type": "TOOL_CALL_START",
        "toolCallId": "call-1",
        "toolCallName": "web__select-row",
        "parentMessageId": "message-1",
    }
    assert tool_call_args("call-1", '{"id":"42"}') == {
        "type": "TOOL_CALL_ARGS",
        "toolCallId": "call-1",
        "delta": '{"id":"42"}',
    }
    assert tool_call_end("call-1") == {
        "type": "TOOL_CALL_END",
        "toolCallId": "call-1",
    }
    assert custom_event("authorization_required", {"api_source_id": 7}) == {
        "type": "CUSTOM",
        "name": "authorization_required",
        "value": {"api_source_id": 7},
    }
