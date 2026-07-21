from typing import Any

from sqlalchemy.orm import Session

from chatapi.chat.agent import (
    AgentError,
    AgentRuntime,
    AgentTurnRequest,
    AgentTurnResult,
    LlmCompleter,
    ToolRunner,
)
from chatapi.llm.client import CanonicalMessage
from chatapi.security.encryption import SecretCipher

ChatError = AgentError
ChatResult = AgentTurnResult


class ChatOrchestrator:
    """Compatibility shim for callers that still select one Skill as a model."""

    def __init__(
        self,
        session: Session,
        cipher: SecretCipher,
        llm: LlmCompleter,
        tool_runner: ToolRunner,
        *,
        max_iterations: int | None = None,
    ) -> None:
        self._runtime = AgentRuntime(
            session,
            cipher,
            llm,
            tool_runner,
            max_iterations=max_iterations,
        )

    async def run(
        self,
        *,
        skill_id: int,
        messages: list[dict[str, Any]],
        tool_session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult:
        user_message = next(
            (message for message in reversed(messages) if message.get("role") == "user"),
            None,
        )
        if user_message is None:
            raise ValueError("Compatibility chat requires a user message")
        content = user_message.get("content", "")
        incoming_messages = [
            CanonicalMessage(
                role=str(message.get("role", "user")),
                content=(
                    message.get("content", "")
                    if isinstance(message.get("content", ""), str)
                    else str(message.get("content", ""))
                ),
            )
            for message in messages
            if message.get("role") in {"system", "user", "assistant"}
        ]
        return await self._runtime.run(
            AgentTurnRequest(
                conversation_id=conversation_id,
                user_content=content if isinstance(content, str) else str(content),
                candidate_skill_ids=[skill_id],
                interactive=False,
                tool_session_id=tool_session_id,
                incoming_messages=incoming_messages,
                candidate_scope_source="explicit",
            )
        )
