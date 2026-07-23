import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Literal, Protocol

from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chat4openapi.chat.context import build_agent_context
from chat4openapi.llm.client import (
    CanonicalMessage,
    CanonicalResponse,
    CanonicalTool,
    CanonicalToolCall,
    LlmProviderError,
)
from chat4openapi.models import (
    Agent,
    AgentSkill,
    ApiSource,
    ApiSourceOAuthConfig,
    ApiSourceToolAuthConfig,
    ChatMessage,
    Conversation,
    GlobalToolAuthConfig,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.oauth import OAuthFlowError, ToolOAuthService
from chat4openapi.tool_sessions.service import (
    ToolSessionError,
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionReauthorizationRequired,
    ToolSessionService,
)
from chat4openapi.tools.effective_schema import effective_input_schema
from chat4openapi.tools.executor import RequestAuth, ToolExecutionResult
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.execution_policy import (
    ToolUnavailableError,
    resolve_tool_execution_policy,
)

DEFAULT_AGENT_PROMPT = """You are Agent4API Agent, the built-in assistant.

Operating rules:
- Choose Skills only from the provided Skill catalog, using their declared names and descriptions.
- Always load a Skill before using its Tools.
- Never invent required Tool arguments or claim a Tool result that was not observed.
- In human-in-loop mode, ask the user to clarify material missing, ambiguous, or choice-dependent business inputs before making an unreliable call.
- In non-interactive ReAct mode, make a reasonable supported assumption when necessary and disclose it in the final response.
- Respond in the user's language.
- Prefer clear, structured Markdown, including tables for structured results.
- If retry attempts are exhausted, a Skill is unavailable, or Tool failures prevent completion, explain the limitation clearly and do not fabricate success."""

LOAD_SKILLS_TOOL = CanonicalTool(
    name="load_skills",
    description="Load one or more Skills required for the current task.",
    input_schema={
        "type": "object",
        "properties": {
            "skill_ids": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 1,
            }
        },
        "required": ["skill_ids"],
        "additionalProperties": False,
    },
)

ASK_USER_TOOL = CanonicalTool(
    name="ask_user",
    description="Pause and ask the user for missing or ambiguous business input.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
            "fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
            "choices": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        "required": ["question", "reason", "fields"],
        "additionalProperties": False,
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
    agent_id: int
    user_content: str
    candidate_skill_ids: list[int]
    interactive: bool
    conversation_id: str | None = None
    tool_session_id: str | None = None
    agent_key_id: int | None = None
    browser_chat_session_id: int | None = None
    embed_session_id: int | None = None
    admin_session_id: int | None = None
    tool_owner_agent_key_id: int | None = None
    incoming_messages: list[CanonicalMessage] = dataclass_field(default_factory=list)
    client_tools: list[CanonicalTool] = dataclass_field(default_factory=list)
    candidate_scope_source: Literal["automatic", "explicit"] = "automatic"


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    conversation_id: str
    status: Literal[
        "completed",
        "needs_input",
        "client_tool_required",
        "authorization_required",
    ]
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
        existing = (
            self._session.get(Conversation, request.conversation_id)
            if request.conversation_id is not None
            else None
        )
        resuming_authorization = bool(
            existing is not None
            and existing.agent_status == "authorization_required"
            and not request.user_content
        )
        if existing is not None and not self._request_owns(existing, request):
            raise AgentError("agent.conversation_not_found")
        try:
            agent, provider = self._configuration(request.agent_id)
        except AgentError as exc:
            if existing is not None and existing.deleted_at is None:
                summary = (
                    "Agent provider is unavailable."
                    if exc.code == "agent.provider_unavailable"
                    else "Agent configuration is unavailable."
                )
                self._fail(existing, summary)
            raise
        try:
            conversation, candidate_skills = self._conversation(request, agent)
        except AgentError as exc:
            if existing is not None and existing.deleted_at is None:
                summary = (
                    "No eligible Skills remain for this conversation."
                    if exc.code == "agent.no_eligible_skills"
                    else "Agent conversation setup failed."
                )
                self._fail(existing, summary)
            raise
        conversation.agent_status = "running"
        conversation.latest_failure_summary = None
        self._session.commit()
        if resuming_authorization:
            resumed = await self._resume_authorized_tool(conversation, request)
            if resumed is not None:
                return resumed
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
        elif request.incoming_messages:
            self._append_incoming_transcript(conversation, request.incoming_messages)
        elif request.user_content:
            self._persist_message(conversation.id, "user", {"text": request.user_content})
        input_tokens = 0
        output_tokens = 0
        max_iterations = self._max_iterations or agent.max_iterations
        can_ask_user = request.interactive and agent.mode == "human_in_loop"

        try:
            for _iteration in range(max_iterations):
                tool_map = self._bound_tools(agent.id, conversation.loaded_skill_ids)
                if conversation.loaded_skill_ids:
                    tools = list(tool_map.canonical.values())
                    if request.embed_session_id is not None:
                        tools = [tool for tool in tools if not tool.name.startswith("web__")]
                    if can_ask_user:
                        tools.append(ASK_USER_TOOL)
                else:
                    tools = [LOAD_SKILLS_TOOL]
                tools.extend(request.client_tools)
                client_tool_map = {tool.name: tool for tool in request.client_tools}
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
                if not isinstance(response, CanonicalResponse):
                    raise TypeError("LLM response was not canonical")
                result = await self._handle_response(
                    response=response,
                    request=request,
                    conversation=conversation,
                    candidate_skills=candidate_skills,
                    tool_map=tool_map,
                    client_tool_map=client_tool_map,
                    can_ask_user=can_ask_user,
                )
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
                if result is not None:
                    return AgentTurnResult(
                        conversation_id=result.conversation_id,
                        status=result.status,
                        content=result.content,
                        loaded_skill_ids=result.loaded_skill_ids,
                        pending=result.pending,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
        except AgentError as exc:
            if conversation.agent_status != "failed":
                summary = {
                    "agent.tool_name_conflict": "Loaded Tools have conflicting names.",
                }.get(exc.code, "Agent execution failed.")
                self._fail(conversation, summary)
            raise
        except LlmProviderError as exc:
            self._fail(conversation, "LLM provider request failed.")
            raise AgentError(
                "agent.provider_failed", {"reason": "LLM provider request failed."}
            ) from exc
        except Exception as exc:
            self._fail(conversation, "Agent runtime failed.")
            raise AgentError("agent.runtime_failed", {"reason": "Agent runtime failed."}) from exc

        summary = f"Agent stopped after reaching the {max_iterations}-iteration limit."
        self._fail(conversation, summary)
        raise AgentError("agent.iteration_limit", {"max_iterations": max_iterations})

    async def _handle_response(
        self,
        *,
        response: CanonicalResponse,
        request: AgentTurnRequest,
        conversation: Conversation,
        candidate_skills: list[Skill],
        tool_map: "AgentRuntime._BoundTools",
        client_tool_map: dict[str, CanonicalTool],
        can_ask_user: bool,
    ) -> AgentTurnResult | None:
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
                input_tokens=0,
                output_tokens=0,
            )

        clarification = next(
            (
                call
                for call in response.tool_calls
                if call.name == ASK_USER_TOOL.name
                and can_ask_user
                and not self._validation_errors(ASK_USER_TOOL.input_schema, call.arguments)
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
                input_tokens=0,
                output_tokens=0,
            )
        for call in response.tool_calls:
            if call.name.startswith("web__"):
                client_tool = client_tool_map.get(call.name)
                if client_tool is None:
                    observation = {
                        "error": "frontend_tool_unavailable",
                        "tool": call.name,
                    }
                else:
                    errors = self._validation_errors(
                        self._strict_tool_schema(client_tool.input_schema),
                        call.arguments,
                    )
                    if errors:
                        observation = self._invalid_arguments(
                            call.name, errors, control=False
                        )
                    else:
                        pending = self._pending_client_tool(call)
                        conversation.agent_status = "waiting_client_tool"
                        self._session.commit()
                        return AgentTurnResult(
                            conversation_id=conversation.id,
                            status="client_tool_required",
                            content=response.content,
                            loaded_skill_ids=list(conversation.loaded_skill_ids),
                            pending=pending,
                            input_tokens=0,
                            output_tokens=0,
                        )
            elif call.name == LOAD_SKILLS_TOOL.name:
                errors = self._validation_errors(LOAD_SKILLS_TOOL.input_schema, call.arguments)
                observation = (
                    self._invalid_arguments(call.name, errors, control=True)
                    if errors
                    else self._load_skills(conversation, candidate_skills, call.arguments)
                )
            elif call.name == ASK_USER_TOOL.name:
                errors = self._validation_errors(ASK_USER_TOOL.input_schema, call.arguments)
                observation = self._invalid_arguments(
                    call.name,
                    errors
                    or [
                        {
                            "path": "",
                            "validator": "availability",
                            "message": "ask_user is unavailable for this turn",
                        }
                    ],
                    control=True,
                )
            else:
                tool = tool_map.models.get(call.name)
                if tool is None or not self._tool_is_authorized(conversation, tool):
                    observation = {"error": "tool_unavailable", "tool": call.name}
                else:
                    schema = self._strict_tool_schema(effective_input_schema(self._session, tool))
                    errors = self._validation_errors(schema, call.arguments)
                    observation = (
                        self._invalid_arguments(call.name, errors, control=False)
                        if errors
                        else await self._execute_tool(
                            tool,
                            call.arguments,
                            request.tool_session_id,
                            agent_id=request.agent_id,
                            agent_key_id=(
                                request.tool_owner_agent_key_id or request.agent_key_id
                            ),
                            admin_session_id=request.admin_session_id,
                            embed_session_id=request.embed_session_id,
                            browser_chat_session_id=request.browser_chat_session_id,
                        )
                    )
            if (
                (
                    request.embed_session_id is not None
                    or request.browser_chat_session_id is not None
                )
                and isinstance(observation, dict)
                and observation.get("error")
                in {"tool_authorization_required", "tool_reauthorization_required"}
            ):
                self._persist_message(
                    conversation.id,
                    "tool",
                    {"text": observation, "tool_call_id": call.id, "name": call.name},
                )
                tool = tool_map.models.get(call.name)
                source = (
                    self._session.get(ApiSource, tool.api_source_id)
                    if tool is not None
                    else None
                )
                pending = {
                    "api_source_id": source.id if source is not None else None,
                    "api_source_name": source.name if source is not None else call.name,
                    "flows": self._authorization_flows(source),
                }
                conversation.agent_status = "authorization_required"
                self._session.commit()
                return AgentTurnResult(
                    conversation_id=conversation.id,
                    status="authorization_required",
                    content=response.content,
                    loaded_skill_ids=list(conversation.loaded_skill_ids),
                    pending=pending,
                    input_tokens=0,
                    output_tokens=0,
                )
            self._persist_message(
                conversation.id,
                "tool",
                {"text": observation, "tool_call_id": call.id, "name": call.name},
            )

        return None

    def _configuration(self, agent_id: int) -> tuple[Agent, LlmProvider]:
        agent = self._session.get(Agent, agent_id)
        if agent is None or agent.deleted_at is not None or not agent.enabled:
            raise AgentError("agent.unavailable")
        provider = (
            self._session.get(LlmProvider, agent.provider_id)
            if agent.provider_id is not None
            else None
        )
        if provider is None or provider.deleted_at is not None or not provider.enabled:
            raise AgentError("agent.provider_unavailable")
        return agent, provider

    def _authorization_flows(self, source: ApiSource | None) -> list[str]:
        if source is None:
            return []
        flows: list[str] = []
        oauth = self._session.get(ApiSourceOAuthConfig, source.id)
        if (
            source.auth_mode in {"none", "oauth"}
            and oauth is not None
            and oauth.enabled
        ):
            flows.append("pkce")
        login = self._session.get(ApiSourceToolAuthConfig, source.id)
        if source.auth_mode == "tool" and login is not None and login.enabled:
            flows.append("swagger")
        elif source.auth_mode == "none":
            login = self._session.get(GlobalToolAuthConfig, 1)
            login_tool = (
                self._session.get(Tool, login.login_tool_id)
                if login is not None and login.enabled and login.login_tool_id is not None
                else None
            )
            if login_tool is not None and login_tool.api_source_id == source.id:
                flows.append("swagger")
        return flows

    async def _resume_authorized_tool(
        self,
        conversation: Conversation,
        request: AgentTurnRequest,
    ) -> AgentTurnResult | None:
        pending = self._pending_authorization_call(conversation.id)
        if pending is None:
            return None
        tool_message, call = pending
        tool = self._bound_tools(
            conversation.agent_id, conversation.loaded_skill_ids
        ).models.get(call.name)
        if tool is None or not self._tool_is_authorized(conversation, tool):
            return None

        observation = await self._execute_tool(
            tool,
            call.arguments,
            request.tool_session_id,
            agent_id=request.agent_id,
            agent_key_id=request.tool_owner_agent_key_id or request.agent_key_id,
            admin_session_id=request.admin_session_id,
            embed_session_id=request.embed_session_id,
            browser_chat_session_id=request.browser_chat_session_id,
        )
        if (
            isinstance(observation, dict)
            and observation.get("error")
            in {"tool_authorization_required", "tool_reauthorization_required"}
        ):
            source = self._session.get(ApiSource, tool.api_source_id)
            authorization = {
                "api_source_id": source.id if source is not None else None,
                "api_source_name": source.name if source is not None else call.name,
                "flows": self._authorization_flows(source),
            }
            conversation.agent_status = "authorization_required"
            self._session.commit()
            return AgentTurnResult(
                conversation_id=conversation.id,
                status="authorization_required",
                content="",
                loaded_skill_ids=list(conversation.loaded_skill_ids),
                pending=authorization,
                input_tokens=0,
                output_tokens=0,
            )

        tool_message.content = {
            "text": observation,
            "tool_call_id": call.id,
            "name": call.name,
        }
        self._session.commit()
        return None

    def _pending_authorization_call(
        self, conversation_id: str
    ) -> tuple[ChatMessage, CanonicalToolCall] | None:
        tool_message = self._session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "tool",
            )
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
        if tool_message is None:
            return None
        observation = tool_message.content.get("text")
        if (
            not isinstance(observation, dict)
            or observation.get("error")
            not in {"tool_authorization_required", "tool_reauthorization_required"}
        ):
            return None
        call_id = tool_message.content.get("tool_call_id")
        assistant_message = self._session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.sequence < tool_message.sequence,
            )
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
        if assistant_message is None:
            return None
        stored_call = next(
            (
                item
                for item in assistant_message.content.get("tool_calls", [])
                if item.get("id") == call_id
            ),
            None,
        )
        if stored_call is None:
            return None
        return tool_message, CanonicalToolCall(
            id=str(stored_call["id"]),
            name=str(stored_call["name"]),
            arguments=dict(stored_call.get("arguments") or {}),
        )

    def _conversation(
        self, request: AgentTurnRequest, agent: Agent
    ) -> tuple[Conversation, list[Skill]]:
        if request.conversation_id is not None:
            conversation = self._session.get(Conversation, request.conversation_id)
            if (
                conversation is None
                or conversation.deleted_at is not None
                or conversation.agent_id != agent.id
                or not self._request_owns(conversation, request)
            ):
                raise AgentError("agent.conversation_not_found")
            candidate_ids = list(conversation.candidate_skill_ids)
        else:
            candidate_ids = list(dict.fromkeys(request.candidate_skill_ids))

        query = (
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(
                AgentSkill.agent_id == agent.id,
                Skill.running.is_(True),
                Skill.deleted_at.is_(None),
            )
        )
        if candidate_ids:
            query = query.where(Skill.id.in_(candidate_ids))
        available = list(self._session.scalars(query.order_by(AgentSkill.position, Skill.id)))
        available_by_id = {skill.id: skill for skill in available}
        if candidate_ids and request.conversation_id is None:
            invalid = [skill_id for skill_id in candidate_ids if skill_id not in available_by_id]
            if invalid:
                raise AgentError("agent.skill_unavailable", {"skill_ids": invalid})
            candidate_skills = available
        elif candidate_ids:
            candidate_skills = available
        else:
            candidate_skills = available
            candidate_ids = [skill.id for skill in available]
        if not candidate_skills:
            raise AgentError("agent.no_eligible_skills")

        if request.conversation_id is not None:
            remaining_ids = {skill.id for skill in candidate_skills}
            filtered_loaded = [
                skill_id for skill_id in conversation.loaded_skill_ids if skill_id in remaining_ids
            ]
            if filtered_loaded != conversation.loaded_skill_ids:
                conversation.loaded_skill_ids = filtered_loaded
                self._session.commit()
            return conversation, candidate_skills
        conversation = Conversation(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            candidate_skill_ids=candidate_ids,
            loaded_skill_ids=[],
            agent_mode=agent.mode if request.interactive else "react",
            agent_status="running",
            candidate_scope_source=request.candidate_scope_source,
            agent_key_id=request.agent_key_id,
            browser_chat_session_id=request.browser_chat_session_id,
            embed_session_id=request.embed_session_id,
        )
        self._session.add(conversation)
        self._session.commit()
        return conversation, candidate_skills

    @staticmethod
    def _request_owns(conversation: Conversation, request: AgentTurnRequest) -> bool:
        requested_owner_count = sum(
            owner_id is not None
            for owner_id in (
                request.agent_key_id,
                request.browser_chat_session_id,
                request.embed_session_id,
            )
        )
        if requested_owner_count != 1:
            return False
        return (
            request.agent_key_id is not None
            and conversation.agent_key_id == request.agent_key_id
            and conversation.browser_chat_session_id is None
            and conversation.embed_session_id is None
        ) or (
            request.browser_chat_session_id is not None
            and conversation.browser_chat_session_id == request.browser_chat_session_id
            and conversation.agent_key_id is None
            and conversation.embed_session_id is None
        ) or (
            request.embed_session_id is not None
            and conversation.embed_session_id == request.embed_session_id
            and conversation.agent_key_id is None
            and conversation.browser_chat_session_id is None
        )

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

    def _bound_tools(self, agent_id: int, loaded_skill_ids: list[int]) -> _BoundTools:
        if not loaded_skill_ids:
            return self._BoundTools({}, {})
        rows = self._session.execute(
            select(SkillTool.skill_id, Tool)
            .join(Skill, Skill.id == SkillTool.skill_id)
            .join(
                AgentSkill,
                (AgentSkill.skill_id == SkillTool.skill_id) & (AgentSkill.agent_id == agent_id),
            )
            .join(Tool, Tool.id == SkillTool.tool_id)
            .join(ApiSource, ApiSource.id == Tool.api_source_id)
            .where(
                SkillTool.skill_id.in_(loaded_skill_ids),
                Skill.running.is_(True),
                Skill.deleted_at.is_(None),
                Tool.enabled.is_(True),
                Tool.deleted_at.is_(None),
                ApiSource.enabled.is_(True),
                ApiSource.deleted_at.is_(None),
            )
            .order_by(SkillTool.skill_id, SkillTool.position)
        ).all()
        by_skill: dict[int, list[Tool]] = {}
        tool_ids_by_name: dict[str, set[int]] = {}
        skill_ids_by_tool_name: dict[str, set[int]] = {}
        for skill_id, tool in rows:
            by_skill.setdefault(skill_id, []).append(tool)
            tool_ids_by_name.setdefault(tool.name, set()).add(tool.id)
            skill_ids_by_tool_name.setdefault(tool.name, set()).add(skill_id)
        conflicts = [
            {
                "tool_name": tool_name,
                "tool_ids": sorted(tool_ids),
                "skill_ids": sorted(skill_ids_by_tool_name[tool_name]),
            }
            for tool_name, tool_ids in sorted(tool_ids_by_name.items())
            if len(tool_ids) > 1
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

    def _tool_is_authorized(self, conversation: Conversation, tool: Tool) -> bool:
        if not conversation.loaded_skill_ids:
            return False
        return (
            self._session.scalar(
                select(SkillTool.skill_id)
                .join(Skill, Skill.id == SkillTool.skill_id)
                .join(
                    AgentSkill,
                    (AgentSkill.skill_id == SkillTool.skill_id)
                    & (AgentSkill.agent_id == conversation.agent_id),
                )
                .join(Agent, Agent.id == AgentSkill.agent_id)
                .join(Tool, Tool.id == SkillTool.tool_id)
                .join(ApiSource, ApiSource.id == Tool.api_source_id)
                .where(
                    SkillTool.skill_id.in_(conversation.loaded_skill_ids),
                    SkillTool.tool_id == tool.id,
                    Agent.enabled.is_(True),
                    Agent.deleted_at.is_(None),
                    Skill.running.is_(True),
                    Skill.deleted_at.is_(None),
                    Tool.enabled.is_(True),
                    Tool.deleted_at.is_(None),
                    ApiSource.enabled.is_(True),
                    ApiSource.deleted_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    async def _execute_tool(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        tool_session_id: str | None,
        *,
        agent_id: int,
        agent_key_id: int | None,
        admin_session_id: int | None,
        embed_session_id: int | None = None,
        browser_chat_session_id: int | None = None,
    ) -> Any:
        try:
            policy = resolve_tool_execution_policy(self._session, tool)
            oauth_service = ToolOAuthService(self._session, self._cipher)
            if (
                policy.authorization_required
                and oauth_service.uses_client_credentials(policy.source.id)
            ):
                auth = await oauth_service.client_credentials_auth(policy.source.id)
                try:
                    result = await self._tool_runner.execute(
                        tool, policy.source, arguments, auth
                    )
                except ToolExecutionError as exc:
                    if exc.status_code != 401:
                        raise
                    auth = await oauth_service.client_credentials_auth(
                        policy.source.id, force_refresh=True
                    )
                    result = await self._tool_runner.execute(
                        tool, policy.source, arguments, auth
                    )
            elif browser_chat_session_id is not None and policy.authorization_required:
                result = await ToolSessionService(
                    self._session, self._cipher, self._tool_runner
                ).execute_for_browser(
                    tool,
                    arguments,
                    browser_chat_session_id=browser_chat_session_id,
                    agent_id=agent_id,
                )
            elif tool_session_id:
                result = await ToolSessionService(
                    self._session, self._cipher, self._tool_runner
                ).execute(
                    tool,
                    arguments,
                    tool_session_id,
                    agent_id=agent_id,
                    agent_key_id=agent_key_id,
                    admin_session_id=admin_session_id,
                )
            elif embed_session_id is not None and policy.authorization_required:
                result = await ToolSessionService(
                    self._session, self._cipher, self._tool_runner
                ).execute_for_embed(
                    tool,
                    arguments,
                    embed_session_id=embed_session_id,
                    agent_id=agent_id,
                )
            elif policy.authorization_required:
                return {"error": "tool_authorization_required", "tool": tool.name}
            else:
                result = await self._tool_runner.execute(
                    tool, policy.source, arguments, RequestAuth()
                )
            return result.data
        except ToolUnavailableError:
            return {"error": "tool_unavailable", "tool": tool.name}
        except ToolExecutionError as exc:
            return {"error": exc.code, "message": str(exc), "tool": tool.name}
        except ToolSessionNotFound:
            return {"error": "tool_authorization_required", "tool": tool.name}
        except (ToolSessionExpired, ToolSessionReauthorizationRequired):
            return {"error": "tool_reauthorization_required", "tool": tool.name}
        except ToolSessionError:
            return {"error": "tool_session_error", "tool": tool.name}
        except OAuthFlowError:
            return {"error": "oauth_client_credentials_failed", "tool": tool.name}

    def _persist_message(self, conversation_id: str, role: str, content: dict[str, Any]) -> None:
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

    def _fail(self, conversation: Conversation, summary: str) -> None:
        conversation.agent_status = "failed"
        conversation.latest_failure_summary = summary
        self._session.commit()

    def _append_incoming_transcript(
        self, conversation: Conversation, incoming: list[CanonicalMessage]
    ) -> None:
        stored = self._session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.sequence)
        ).all()
        external = [
            message_from_record
            for message_from_record in stored
            if message_from_record.role in {"system", "user", "assistant"}
            and not message_from_record.content.get("tool_calls")
        ]
        stored_pairs = [(message.role, message.content.get("text", "")) for message in external]
        incoming_pairs = [(message.role, message.content) for message in incoming]
        overlap = 0
        for size in range(min(len(stored_pairs), len(incoming_pairs)), 0, -1):
            if stored_pairs[-size:] == incoming_pairs[:size]:
                overlap = size
                break
        for message in incoming[overlap:]:
            content: dict[str, Any] = {"text": message.content}
            if message.tool_call_id is not None:
                content["tool_call_id"] = message.tool_call_id
            if message.name is not None:
                content["name"] = message.name
            if message.tool_calls:
                content["tool_calls"] = [self._stored_call(call) for call in message.tool_calls]
            self._persist_message(conversation.id, message.role, content)

    @staticmethod
    def _strict_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
        strict = deepcopy(schema)
        if strict.get("type") == "object":
            strict.setdefault("additionalProperties", False)
        return strict

    @staticmethod
    def _validation_errors(schema: dict[str, Any], arguments: Any) -> list[dict[str, str]]:
        validator = Draft202012Validator(schema)
        return [
            {
                "path": ".".join(str(part) for part in error.absolute_path),
                "validator": str(error.validator),
                "message": error.message,
            }
            for error in sorted(validator.iter_errors(arguments), key=str)
        ]

    @staticmethod
    def _invalid_arguments(
        tool_name: str,
        errors: list[dict[str, str]],
        *,
        control: bool,
    ) -> dict[str, Any]:
        return {
            "error": ("invalid_control_arguments" if control else "invalid_tool_arguments"),
            "tool": tool_name,
            "validation_errors": errors,
        }

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

    @staticmethod
    def _pending_client_tool(call: CanonicalToolCall) -> dict[str, Any]:
        return {
            "tool_call_id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }
