import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from chat4openapi.agui.contracts import AguiMessage, AguiRunInput
from chat4openapi.agui.events import (
    custom_event,
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
from chat4openapi.chat.agent import AgentError, AgentRuntime, AgentTurnRequest
from chat4openapi.llm.client import CanonicalMessage, CanonicalTool, LlmProviderError
from chat4openapi.models import EmbedSession


class AguiRuntime:
    def __init__(self, agent_runtime: AgentRuntime) -> None:
        self._agent_runtime = agent_runtime

    async def run(
        self, payload: AguiRunInput, owner: EmbedSession
    ) -> AsyncIterator[dict[str, Any]]:
        yield run_started(payload.thread_id, payload.run_id)
        try:
            result = await self._agent_runtime.run(self._turn(payload, owner))
        except AgentError as exc:
            yield run_error("Agent execution failed.", exc.code)
            return
        except LlmProviderError:
            yield run_error("Agent provider request failed.", "chat.failed")
            return

        yield custom_event(
            "chat4openapi:conversation",
            {"conversationId": result.conversation_id},
        )
        message_id = str(uuid.uuid4())
        if result.content:
            yield text_message_start(message_id)
            yield text_message_content(message_id, result.content)
            yield text_message_end(message_id)

        if result.status == "client_tool_required" and result.pending is not None:
            tool_call_id = str(result.pending["tool_call_id"])
            yield tool_call_start(
                tool_call_id,
                str(result.pending["name"]),
                message_id,
            )
            yield tool_call_args(
                tool_call_id,
                json.dumps(
                    result.pending["arguments"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            yield tool_call_end(tool_call_id)

        if result.status == "authorization_required" and result.pending is not None:
            yield custom_event("authorization_required", result.pending)

        yield run_finished(payload.thread_id, payload.run_id)

    @classmethod
    def _turn(cls, payload: AguiRunInput, owner: EmbedSession) -> AgentTurnRequest:
        latest = payload.messages[-1] if payload.messages else None
        incoming = cls._incoming_messages(latest)
        return AgentTurnRequest(
            agent_id=owner.agent_id,
            user_content=cls._user_content(latest),
            candidate_skill_ids=[],
            conversation_id=cls._conversation_id(payload),
            embed_session_id=owner.id,
            incoming_messages=incoming,
            client_tools=[
                CanonicalTool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.parameters,
                )
                for tool in payload.tools
            ],
            interactive=False,
        )

    @staticmethod
    def _conversation_id(payload: AguiRunInput) -> str | None:
        for container in (payload.forwarded_props, payload.state):
            if isinstance(container, dict):
                value = container.get("conversationId")
                if isinstance(value, str) and value:
                    return value
        return None

    @classmethod
    def _incoming_messages(cls, latest: AguiMessage | None) -> list[CanonicalMessage]:
        if latest is None or latest.role != "tool":
            return []
        return [
            CanonicalMessage(
                role="tool",
                content=cls._text(latest.content),
                tool_call_id=latest.tool_call_id,
            )
        ]

    @classmethod
    def _user_content(cls, latest: AguiMessage | None) -> str:
        if latest is None or latest.role != "user":
            return ""
        return cls._text(latest.content)

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
