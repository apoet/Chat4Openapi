import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chatapi.chat.context import build_agent_context
from chatapi.llm.client import CanonicalResponse, CanonicalTool, CanonicalToolCall
from chatapi.models import (
    AgentConfig,
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
from chatapi.tool_sessions.service import ToolSessionError, ToolSessionService
from chatapi.tools.effective_schema import effective_input_schema
from chatapi.tools.executor import RequestAuth, ToolExecutionResult
from chatapi.tools.errors import ToolExecutionError

DEFAULT_AGENT_PROMPT = (
    "You are ChatAPI Agent, the built-in assistant. Use the available Skills and Tools "
    "to help the user, and return clear Markdown responses."
)

LOAD_SKILLS_TOOL = CanonicalTool(
    name="load_skills",
    description="Load one or more Skills required for the current task.",
    input_schema={
        "type": "object",
        "properties": {"skill_ids": {"type": "array", "items": {"type": "integer"}}},
        "required": ["skill_ids"],
    },
)

ASK_USER_TOOL = CanonicalTool(
    name="ask_user",
    description="Pause and ask the user for missing or ambiguous business input.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "reason": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "choices": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question", "reason", "fields"],
    },
)


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


class AgentError(RuntimeError):
    def __init__(self, code: str, params: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.params = params or {}


@dataclass(frozen=True, slots=True)
class AgentTurnRequest:
    user_content: str
    candidate_skill_ids: list[int]
    interactive: bool
    conversation_id: str | None = None
    tool_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    conversation_id: str
    status: Literal["completed", "needs_input"]
    content: str
    loaded_skill_ids: list[int]
    pending: dict[str, Any] | None
    input_tokens: int
    output_tokens: int


class AgentRuntime:
    def __init__(
        self,
        session: Session,
        cipher: SecretCipher,
        llm: LlmCompleter,
        tool_runner: ToolRunner,
        *,
        max_iterations: int | None = None,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._llm = llm
        self._tool_runner = tool_runner
        self._max_iterations = max_iterations

    async def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        agent, provider = self._configuration()
        conversation, candidate_skills = self._conversation(request, agent)
        if conversation.pending_clarification is not None:
            pending = conversation.pending_clarification
            self._persist_message(
                conversation.id,
                "tool",
                {
                    "text": {"answer": request.user_content},
                    "tool_call_id": pending["tool_call_id"],
                    "name": ASK_USER_TOOL.name,
                },
            )
            conversation.pending_clarification = None
            conversation.agent_status = "running"
            self._session.commit()
        else:
            self._persist_message(conversation.id, "user", {"text": request.user_content})
        input_tokens = 0
        output_tokens = 0
        max_iterations = self._max_iterations or agent.max_iterations
        can_ask_user = request.interactive and agent.mode == "human_in_loop"

        for _iteration in range(max_iterations):
            tool_map = self._bound_tools(conversation.loaded_skill_ids)
            if conversation.loaded_skill_ids:
                tools = list(tool_map.canonical.values())
                if can_ask_user:
                    tools.append(ASK_USER_TOOL)
            else:
                tools = [LOAD_SKILLS_TOOL]
            response = await self._llm.complete(
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=self._cipher.decrypt_json(provider.encrypted_api_key)["api_key"],
                model=agent.model or provider.default_model,
                messages=build_agent_context(
                    self._session, agent, conversation, candidate_skills
                ),
                tools=tools,
            )
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            if not response.tool_calls:
                self._persist_message(conversation.id, "assistant", {"text": response.content})
                conversation.agent_status = "completed"
                self._session.commit()
                return AgentTurnResult(
                    conversation_id=conversation.id,
                    status="completed",
                    content=response.content,
                    loaded_skill_ids=list(conversation.loaded_skill_ids),
                    pending=None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            clarification = next(
                (
                    call
                    for call in response.tool_calls
                    if call.name == ASK_USER_TOOL.name and can_ask_user
                ),
                None,
            )
            persisted_calls = [clarification] if clarification is not None else response.tool_calls
            self._persist_message(
                conversation.id,
                "assistant",
                {
                    "text": response.content,
                    "tool_calls": [self._stored_call(call) for call in persisted_calls],
                },
            )
            if clarification is not None:
                pending = self._pending_clarification(clarification)
                conversation.pending_clarification = pending
                conversation.agent_status = "needs_input"
                self._session.commit()
                return AgentTurnResult(
                    conversation_id=conversation.id,
                    status="needs_input",
                    content=pending["question"],
                    loaded_skill_ids=list(conversation.loaded_skill_ids),
                    pending=pending,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            for call in response.tool_calls:
                if call.name == LOAD_SKILLS_TOOL.name:
                    observation = self._load_skills(
                        conversation, candidate_skills, call.arguments
                    )
                else:
                    tool = tool_map.models.get(call.name)
                    if tool is None:
                        observation = {"error": "tool_unavailable", "tool": call.name}
                    else:
                        observation = await self._execute_tool(
                            tool, call.arguments, request.tool_session_id
                        )
                self._persist_message(
                    conversation.id,
                    "tool",
                    {"text": observation, "tool_call_id": call.id, "name": call.name},
                )

        conversation.agent_status = "failed"
        self._session.commit()
        raise AgentError("agent.iteration_limit", {"max_iterations": max_iterations})

    def _configuration(self) -> tuple[AgentConfig, LlmProvider]:
        agent = self._session.get(AgentConfig, 1)
        if agent is None or not agent.enabled:
            raise AgentError("agent.unavailable")
        provider = (
            self._session.get(LlmProvider, agent.provider_id)
            if agent.provider_id is not None
            else None
        )
        if provider is None or provider.deleted_at is not None or not provider.enabled:
            raise AgentError("agent.provider_unavailable")
        return agent, provider

    def _conversation(
        self, request: AgentTurnRequest, agent: AgentConfig
    ) -> tuple[Conversation, list[Skill]]:
        if request.conversation_id is not None:
            conversation = self._session.get(Conversation, request.conversation_id)
            if conversation is None or conversation.deleted_at is not None:
                raise AgentError("agent.conversation_not_found")
            candidate_ids = list(conversation.candidate_skill_ids)
        else:
            candidate_ids = list(dict.fromkeys(request.candidate_skill_ids))

        query = select(Skill).where(Skill.running.is_(True), Skill.deleted_at.is_(None))
        if candidate_ids:
            query = query.where(Skill.id.in_(candidate_ids))
        available = list(self._session.scalars(query.order_by(Skill.id)))
        available_by_id = {skill.id: skill for skill in available}
        if candidate_ids:
            invalid = [skill_id for skill_id in candidate_ids if skill_id not in available_by_id]
            if invalid:
                raise AgentError("agent.skill_unavailable", {"skill_ids": invalid})
            candidate_skills = [available_by_id[skill_id] for skill_id in candidate_ids]
        else:
            candidate_skills = available
            candidate_ids = [skill.id for skill in available]
        if not candidate_skills:
            raise AgentError("agent.no_eligible_skills")

        if request.conversation_id is not None:
            return conversation, candidate_skills
        conversation = Conversation(
            id=str(uuid.uuid4()),
            candidate_skill_ids=candidate_ids,
            loaded_skill_ids=[],
            agent_mode=agent.mode if request.interactive else "react",
            agent_status="running",
        )
        self._session.add(conversation)
        self._session.commit()
        return conversation, candidate_skills

    def _load_skills(
        self,
        conversation: Conversation,
        candidate_skills: list[Skill],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        requested = arguments.get("skill_ids")
        candidate_ids = {skill.id for skill in candidate_skills}
        if (
            not isinstance(requested, list)
            or not requested
            or any(not isinstance(skill_id, int) for skill_id in requested)
            or any(skill_id not in candidate_ids for skill_id in requested)
        ):
            return {
                "error": "invalid_skill_ids",
                "requested_skill_ids": requested,
                "candidate_skill_ids": [skill.id for skill in candidate_skills],
            }
        conversation.loaded_skill_ids = list(
            dict.fromkeys([*conversation.loaded_skill_ids, *requested])
        )
        self._session.commit()
        return {"loaded_skill_ids": list(conversation.loaded_skill_ids)}

    @dataclass(frozen=True, slots=True)
    class _BoundTools:
        canonical: dict[str, CanonicalTool]
        models: dict[str, Tool]

    def _bound_tools(self, loaded_skill_ids: list[int]) -> _BoundTools:
        if not loaded_skill_ids:
            return self._BoundTools({}, {})
        rows = self._session.execute(
            select(SkillTool.skill_id, Tool)
            .join(Tool, Tool.id == SkillTool.tool_id)
            .join(ApiSource, ApiSource.id == Tool.api_source_id)
            .where(
                SkillTool.skill_id.in_(loaded_skill_ids),
                Tool.enabled.is_(True),
                Tool.deleted_at.is_(None),
                ApiSource.enabled.is_(True),
                ApiSource.deleted_at.is_(None),
            )
            .order_by(SkillTool.skill_id, SkillTool.position)
        ).all()
        by_skill: dict[int, list[Tool]] = {}
        skill_ids_by_tool_name: dict[str, set[int]] = {}
        for skill_id, tool in rows:
            by_skill.setdefault(skill_id, []).append(tool)
            skill_ids_by_tool_name.setdefault(tool.name, set()).add(skill_id)
        conflicts = [
            {"tool_name": tool_name, "skill_ids": sorted(skill_ids)}
            for tool_name, skill_ids in sorted(skill_ids_by_tool_name.items())
            if len(skill_ids) > 1
        ]
        if conflicts:
            raise AgentError("agent.tool_name_conflict", {"conflicts": conflicts})
        canonical: dict[str, CanonicalTool] = {}
        models: dict[str, Tool] = {}
        for skill_id in loaded_skill_ids:
            for tool in by_skill.get(skill_id, []):
                if tool.name in models:
                    continue
                models[tool.name] = tool
                canonical[tool.name] = CanonicalTool(
                    name=tool.name,
                    description=tool.description or tool.operation_key,
                    input_schema=effective_input_schema(self._session, tool),
                )
        return self._BoundTools(canonical, models)

    async def _execute_tool(
        self, tool: Tool, arguments: dict[str, Any], tool_session_id: str | None
    ) -> Any:
        try:
            config = self._session.get(GlobalToolAuthConfig, 1)
            if config is not None and config.enabled:
                if not tool_session_id:
                    return {"error": "tool_session_required", "tool": tool.name}
                result = await ToolSessionService(
                    self._session, self._cipher, self._tool_runner
                ).execute(tool, arguments, tool_session_id)
            else:
                source = self._session.get(ApiSource, tool.api_source_id)
                if source is None or source.deleted_at is not None or not source.enabled:
                    return {"error": "tool_unavailable", "tool": tool.name}
                result = await self._tool_runner.execute(tool, source, arguments, RequestAuth())
            return result.data
        except ToolExecutionError as exc:
            return {"error": exc.code, "message": str(exc), "tool": tool.name}
        except ToolSessionError as exc:
            return {
                "error": "tool_session_error",
                "message": str(exc),
                "tool": tool.name,
            }

    def _persist_message(
        self, conversation_id: str, role: str, content: dict[str, Any]
    ) -> None:
        current = self._session.scalar(
            select(func.max(ChatMessage.sequence)).where(
                ChatMessage.conversation_id == conversation_id
            )
        )
        self._session.add(
            ChatMessage(
                conversation_id=conversation_id,
                sequence=(current if current is not None else -1) + 1,
                role=role,
                content=content,
            )
        )
        self._session.commit()

    @staticmethod
    def _stored_call(call: CanonicalToolCall) -> dict[str, Any]:
        return {"id": call.id, "name": call.name, "arguments": call.arguments}

    @staticmethod
    def _pending_clarification(call: CanonicalToolCall) -> dict[str, Any]:
        arguments = call.arguments
        return {
            "tool_call_id": call.id,
            "question": str(arguments.get("question", "")),
            "reason": str(arguments.get("reason", "")),
            "fields": list(arguments.get("fields") or []),
            "choices": list(arguments.get("choices") or []),
        }
