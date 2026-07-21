import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chatapi.llm.client import (
    CanonicalMessage,
    CanonicalResponse,
    CanonicalTool,
)
from chatapi.models import (
    ApiSource,
    ChatMessage,
    Conversation,
    GlobalToolAuthConfig,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chatapi.security.encryption import SecretCipher
from chatapi.tool_sessions.service import ToolSessionService
from chatapi.tools.executor import RequestAuth, ToolExecutionResult


class LlmCompleter(Protocol):
    async def complete(self, **kwargs: Any) -> CanonicalResponse: ...


class ToolRunner(Protocol):
    async def execute(
        self,
        tool: Tool,
        source: ApiSource,
        arguments: Mapping[str, Any],
        auth: RequestAuth,
    ) -> ToolExecutionResult: ...


class ChatError(RuntimeError):
    pass


class SkillNotRunning(ChatError):
    pass


class ToolLoopLimitExceeded(ChatError):
    pass


class ChatToolSessionRequired(ChatError):
    pass


class ChatToolUnavailable(ChatError):
    pass


@dataclass(frozen=True, slots=True)
class ChatResult:
    conversation_id: str
    content: str
    input_tokens: int
    output_tokens: int


class ChatOrchestrator:
    def __init__(
        self,
        session: Session,
        cipher: SecretCipher,
        llm: LlmCompleter,
        tool_runner: ToolRunner,
        *,
        max_iterations: int = 8,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._llm = llm
        self._tool_runner = tool_runner
        self._max_iterations = max_iterations

    async def run(
        self,
        *,
        skill_id: int,
        messages: list[dict[str, Any]],
        tool_session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult:
        skill = self._session.get(Skill, skill_id)
        if skill is None or skill.deleted_at is not None or not skill.running:
            raise SkillNotRunning("Skill is not running")
        provider = (
            self._session.get(LlmProvider, skill.provider_id)
            if skill.provider_id is not None
            else None
        )
        if provider is None or provider.deleted_at is not None or not provider.enabled:
            raise SkillNotRunning("Skill provider is unavailable")
        tools = self._bound_tools(skill.id)
        canonical_tools = [
            CanonicalTool(
                name=tool.name,
                description=tool.description or tool.operation_key,
                input_schema=tool.input_schema,
            )
            for tool in tools
        ]
        tool_map = {tool.name: tool for tool in tools}
        provider_secret = self._cipher.decrypt_json(provider.encrypted_api_key)["api_key"]
        canonical_messages = [CanonicalMessage(role="system", content=skill.system_prompt)]
        canonical_messages.extend(
            CanonicalMessage(role=message["role"], content=message.get("content", ""))
            for message in messages
        )
        conversation = self._conversation(skill.id, conversation_id)
        self._persist_incoming(conversation.id, messages)
        input_tokens = 0
        output_tokens = 0
        for _iteration in range(self._max_iterations):
            response = await self._llm.complete(
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=provider_secret,
                model=skill.model or provider.default_model,
                messages=canonical_messages,
                tools=canonical_tools,
            )
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            if not response.tool_calls:
                self._persist_message(conversation.id, "assistant", {"text": response.content})
                return ChatResult(
                    conversation.id, response.content, input_tokens, output_tokens
                )
            canonical_messages.append(
                CanonicalMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                tool = tool_map.get(call.name)
                if tool is None:
                    raise ChatToolUnavailable(f"Tool is not bound to Skill: {call.name}")
                result = await self._execute_tool(tool, call.arguments, tool_session_id)
                canonical_messages.append(
                    CanonicalMessage(
                        role="tool",
                        content=result.data,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
        raise ToolLoopLimitExceeded("Skill exceeded the Tool iteration limit")

    def _bound_tools(self, skill_id: int) -> list[Tool]:
        return list(
            self._session.scalars(
                select(Tool)
                .join(SkillTool, SkillTool.tool_id == Tool.id)
                .join(ApiSource, ApiSource.id == Tool.api_source_id)
                .where(
                    SkillTool.skill_id == skill_id,
                    Tool.enabled.is_(True),
                    Tool.deleted_at.is_(None),
                    ApiSource.enabled.is_(True),
                    ApiSource.deleted_at.is_(None),
                )
                .order_by(SkillTool.position)
            )
        )

    async def _execute_tool(
        self, tool: Tool, arguments: dict[str, Any], tool_session_id: str | None
    ) -> ToolExecutionResult:
        config = self._session.get(GlobalToolAuthConfig, 1)
        if config is not None and config.enabled:
            if not tool_session_id:
                raise ChatToolSessionRequired("Original API Tool Session is required")
            return await ToolSessionService(
                self._session, self._cipher, self._tool_runner
            ).execute(tool, arguments, tool_session_id)
        source = self._session.get(ApiSource, tool.api_source_id)
        if source is None:
            raise ChatToolUnavailable("Tool API Source is unavailable")
        return await self._tool_runner.execute(tool, source, arguments, RequestAuth())

    def _conversation(self, skill_id: int, conversation_id: str | None) -> Conversation:
        if conversation_id:
            conversation = self._session.get(Conversation, conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                raise ChatError("Conversation was not found")
            if conversation.skill_id != skill_id:
                raise ChatError("Conversation belongs to a different Skill")
            return conversation
        conversation = Conversation(id=str(uuid.uuid4()), skill_id=skill_id)
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def _next_sequence(self, conversation_id: str) -> int:
        current = self._session.scalar(
            select(func.max(ChatMessage.sequence)).where(
                ChatMessage.conversation_id == conversation_id
            )
        )
        return (current if current is not None else -1) + 1

    def _persist_incoming(
        self, conversation_id: str, messages: list[dict[str, Any]]
    ) -> None:
        for message in messages:
            self._persist_message(
                conversation_id,
                message["role"],
                {"text": message.get("content", "")},
                commit=False,
            )
        self._session.commit()

    def _persist_message(
        self,
        conversation_id: str,
        role: str,
        content: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        self._session.add(
            ChatMessage(
                conversation_id=conversation_id,
                sequence=self._next_sequence(conversation_id),
                role=role,
                content=content,
            )
        )
        self._session.flush()
        if commit:
            self._session.commit()
