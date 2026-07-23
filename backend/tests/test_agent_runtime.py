import asyncio
import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from chat4openapi.chat.agent import (
    AgentError,
    AgentRuntime,
    AgentTurnRequest as RuntimeTurnRequest,
)
from chat4openapi.llm.client import CanonicalResponse, CanonicalToolCall, LlmProviderError
from chat4openapi.models import (
    Agent,
    AgentSkill,
    ApiSource,
    ApiSourceOAuthConfig,
    BrowserChatSession,
    ChatMessage,
    Conversation,
    GlobalToolAuthConfig,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tool_sessions.service import (
    ToolSessionError,
    ToolSessionExpired,
    ToolSessionNotFound,
    ToolSessionReauthorizationRequired,
)
from chat4openapi.tool_sessions.credentials import auth_to_json
from chat4openapi.tools.executor import RequestAuth
from chat4openapi.skills.defaults import (
    VARCARDS2_GENE_SYSTEM_PROMPT,
    VARCARDS2_GENE_TABLE_RULE,
)
from chat4openapi.tools.executor import ToolExecutionResult
from chat4openapi.tools.errors import ToolExecutionError

TEST_AGENT_ID = 1


class SequencedLlm:
    def __init__(self, responses: list[CanonicalResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class DeferredToolCallLlm(SequencedLlm):
    def __init__(self, responses: list[CanonicalResponse]) -> None:
        super().__init__(responses)
        self.tool_call_started = asyncio.Event()
        self.release_tool_call = asyncio.Event()

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 2:
            self.tool_call_started.set()
            await self.release_tool_call.wait()
        return self.responses.pop(0)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, tool, _source, arguments, auth):
        self.calls.append((tool.name, arguments, auth))
        return ToolExecutionResult(
            200,
            {"symbol": "ABCA4", "chromosome": "1", "location": "1p22.1"},
            "application/json",
        )


class StrictRecordingExecutor(RecordingExecutor):
    async def execute(self, tool, source, arguments, auth):
        return await super().execute(tool, source, arguments, auth)


class FailingExecutor:
    async def execute(self, _tool, _source, _arguments, _auth):
        raise ToolExecutionError("upstream_error", "Upstream API returned HTTP 403")


def turn(
    user_content: str,
    candidate_skill_ids: list[int],
    interactive: bool,
    *,
    agent_id: int = TEST_AGENT_ID,
    **kwargs,
) -> RuntimeTurnRequest:
    kwargs.setdefault("browser_chat_session_id", 1)
    return RuntimeTurnRequest(
        agent_id=agent_id,
        user_content=user_content,
        candidate_skill_ids=candidate_skill_ids,
        interactive=interactive,
        **kwargs,
    )


def seed_runtime(session, cipher: SecretCipher) -> tuple[Skill, Tool]:
    session.add(
        BrowserChatSession(
            id=1,
            token_hash="runtime-test-browser-token-hash",
            public_subject_id="runtime-test-browser-subject",
            expires_at=datetime(2099, 1, 1),
        )
    )
    provider = LlmProvider(
        name="Primary",
        provider_type="openai",
        base_url="https://llm.test/v1",
        encrypted_api_key=cipher.encrypt_json({"api_key": "provider-secret"}),
        default_model="gpt-test",
    )
    source = ApiSource(name="Gene API", source_type="openapi", base_url="https://api.test")
    session.add_all([provider, source])
    session.flush()
    session.add(
        Agent(
            id=1,
            name="Chat4Openapi Agent",
            enabled=True,
            system_prompt="Route through declared Skills.",
            provider_id=provider.id,
            mode="human_in_loop",
            max_iterations=8,
        )
    )
    tool = Tool(
        api_source_id=source.id,
        operation_key="GET /genes/{symbol}",
        name="get_gene",
        description="Get a gene locus",
        input_schema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
        execution_schema={"method": "GET", "path": "/genes/{symbol}", "parameters": []},
        enabled=True,
    )
    skill = Skill(
        name="Varcards2-Gene",
        description="Look up gene loci.",
        system_prompt=VARCARDS2_GENE_SYSTEM_PROMPT,
        running=True,
    )
    session.add_all([tool, skill])
    session.flush()
    session.add_all(
        [
            AgentSkill(agent_id=1, skill_id=skill.id, position=0),
            SkillTool(skill_id=skill.id, tool_id=tool.id, position=0),
        ]
    )
    session.commit()
    return skill, tool


def add_compound_skill(session) -> tuple[Skill, Tool]:
    source = session.scalar(select(ApiSource))
    tool = Tool(
        api_source_id=source.id,
        operation_key="GET /diseases/{symbol}",
        name="get_disease",
        description="Get associated diseases",
        input_schema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
        execution_schema={
            "method": "GET",
            "path": "/diseases/{symbol}",
            "parameters": [],
        },
        enabled=True,
    )
    skill = Skill(
        name="Disease lookup",
        description="Look up gene-disease associations.",
        system_prompt="Summarize disease associations.",
        running=True,
    )
    session.add_all([tool, skill])
    session.flush()
    position = session.scalar(
        select(AgentSkill.position)
        .where(AgentSkill.agent_id == 1)
        .order_by(AgentSkill.position.desc())
        .limit(1)
    )
    session.add_all(
        [
            AgentSkill(
                agent_id=1,
                skill_id=skill.id,
                position=(position if position is not None else -1) + 1,
            ),
            SkillTool(skill_id=skill.id, tool_id=tool.id, position=0),
        ]
    )
    session.commit()
    return skill, tool


def add_skill_sharing_tool(session, tool: Tool) -> Skill:
    skill = Skill(
        name="Shared gene lookup",
        description="Use the shared gene Tool.",
        system_prompt="Use the shared gene lookup.",
        running=True,
    )
    session.add(skill)
    session.flush()
    position = session.scalar(
        select(AgentSkill.position)
        .where(AgentSkill.agent_id == 1)
        .order_by(AgentSkill.position.desc())
        .limit(1)
    )
    session.add_all(
        [
            AgentSkill(
                agent_id=1,
                skill_id=skill.id,
                position=(position if position is not None else -1) + 1,
            ),
            SkillTool(skill_id=skill.id, tool_id=tool.id, position=0),
        ]
    )
    session.commit()
    return skill


@pytest.mark.asyncio
async def test_agent_catalog_is_ordered_and_cannot_load_another_agents_skill(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        first, _first_tool = seed_runtime(session, cipher)
        second, _second_tool = add_compound_skill(session)
        provider = session.scalar(select(LlmProvider))
        foreign = Skill(
            name="Foreign Skill",
            description="Only another Agent may load this.",
            system_prompt="Foreign prompt.",
            running=True,
        )
        stopped = Skill(
            name="Stopped Skill",
            system_prompt="Stopped prompt.",
            running=False,
        )
        agent = Agent(
            id=2,
            name="Other Agent",
            enabled=True,
            system_prompt="Other Agent prompt.",
            provider_id=provider.id,
            mode="react",
            max_iterations=8,
        )
        session.add_all([foreign, stopped, agent])
        session.flush()
        session.query(AgentSkill).filter_by(agent_id=1, skill_id=first.id).delete()
        session.query(AgentSkill).filter_by(agent_id=1, skill_id=second.id).delete()
        session.add_all(
            [
                AgentSkill(agent_id=1, skill_id=second.id, position=0),
                AgentSkill(agent_id=1, skill_id=first.id, position=1),
                AgentSkill(agent_id=1, skill_id=stopped.id, position=2),
                AgentSkill(agent_id=2, skill_id=foreign.id, position=0),
            ]
        )
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            "foreign-load",
                            "load_skills",
                            {"skill_ids": [foreign.id]},
                        )
                    ],
                ),
                CanonicalResponse(content="Foreign Skill was rejected."),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            turn("use foreign skill", [], False, agent_id=1)
        )

        assert result.loaded_skill_ids == []
        assert executor.calls == []
        catalog = json.loads(llm.calls[0]["messages"][1].content)
        assert [item["id"] for item in catalog["skills"]] == [second.id, first.id]
        observation = llm.calls[1]["messages"][-1].content
        assert observation == {
            "error": "invalid_skill_ids",
            "requested_skill_ids": [foreign.id],
            "candidate_skill_ids": [second.id, first.id],
        }


@pytest.mark.asyncio
async def test_routes_loads_skill_and_executes_only_bound_tools(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="gene_1",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        )
                    ],
                ),
                CanonicalResponse(
                    content=(
                        "| Field | Result |\n"
                        "|---|---|\n"
                        "| Gene | ABCA4 |\n"
                        "| Chromosome | 1 |\n"
                        "| Cytogenetic location | 1p22.1 |\n"
                        "| Reference build | Not provided by the API |\n\n"
                        "Source: Varcards2 API."
                    ),
                    stop_reason="stop",
                ),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            turn(
                user_content="查询 ABCA4 位点",
                candidate_skill_ids=[skill.id],
                interactive=False,
            )
        )

        assert result.status == "completed"
        assert result.loaded_skill_ids == [skill.id]
        assert "| Gene | ABCA4 |" in result.content
        assert "| Chromosome | 1 |" in result.content
        assert "| Cytogenetic location | 1p22.1 |" in result.content
        assert "| Reference build | Not provided by the API |" in result.content
        assert "Source:" in result.content
        assert [tool.name for tool in llm.calls[0]["tools"]] == ["load_skills"]
        catalog = json.loads(llm.calls[0]["messages"][1].content)
        assert catalog == {
            "skills": [
                {
                    "id": skill.id,
                    "name": "Varcards2-Gene",
                    "description": "Look up gene loci.",
                }
            ]
        }
        assert VARCARDS2_GENE_TABLE_RULE not in "\n".join(
            str(message.content) for message in llm.calls[0]["messages"]
        )
        assert [tool.name for tool in llm.calls[1]["tools"]] == ["get_gene"]
        loaded_system_prompts = [
            message.content for message in llm.calls[1]["messages"] if message.role == "system"
        ]
        assert any(VARCARDS2_GENE_TABLE_RULE in prompt for prompt in loaded_system_prompts)
        assert executor.calls[0][0:2] == ("get_gene", {"symbol": "ABCA4"})
    assert llm.calls[0]["api_key"] == "provider-secret"


@pytest.mark.asyncio
async def test_human_in_loop_pauses_and_resumes_without_tool_approval(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="clarify_1",
                            name="ask_user",
                            arguments={
                                "question": "请选择参考基因组：GRCh37 还是 GRCh38？",
                                "reason": "坐标依赖参考基因组。",
                                "fields": ["reference"],
                                "choices": ["GRCh37", "GRCh38"],
                            },
                        )
                    ],
                ),
                CanonicalResponse(content="已使用 GRCh38。", stop_reason="stop"),
            ]
        )
        executor = RecordingExecutor()
        runtime = AgentRuntime(session, cipher, llm, executor)

        paused = await runtime.run(
            turn(
                user_content="查询 ABCA4 位点",
                candidate_skill_ids=[skill.id],
                interactive=True,
            )
        )

        assert paused.status == "needs_input"
        assert paused.content == "请选择参考基因组：GRCh37 还是 GRCh38？"
        assert paused.pending == {
            "tool_call_id": "clarify_1",
            "question": "请选择参考基因组：GRCh37 还是 GRCh38？",
            "reason": "坐标依赖参考基因组。",
            "fields": ["reference"],
            "choices": ["GRCh37", "GRCh38"],
        }
        assert executor.calls == []

        resumed = await runtime.run(
            turn(
                conversation_id=paused.conversation_id,
                user_content="GRCh38",
                candidate_skill_ids=[],
                interactive=True,
            )
        )

        assert resumed.status == "completed"
        assert resumed.content == "已使用 GRCh38。"
        assert resumed.pending is None
        resume_messages = llm.calls[2]["messages"]
        assert resume_messages[-1].role == "tool"
        assert resume_messages[-1].tool_call_id == "clarify_1"
        assert resume_messages[-1].name == "ask_user"
        assert resume_messages[-1].content == {"answer": "GRCh38"}
        stored = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == paused.conversation_id)
            .order_by(ChatMessage.sequence)
        ).all()
        assert stored[-2].content == {
            "text": {"answer": "GRCh38"},
            "tool_call_id": "clarify_1",
            "name": "ask_user",
        }


@pytest.mark.asyncio
async def test_mixed_clarification_and_business_call_persists_only_clarification(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="gene_before_answer",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        ),
                        CanonicalToolCall(
                            id="clarify_reference",
                            name="ask_user",
                            arguments={
                                "question": "Which reference genome?",
                                "reason": "Coordinates depend on it.",
                                "fields": ["reference"],
                            },
                        ),
                    ],
                ),
                CanonicalResponse(content="Used GRCh38."),
            ]
        )
        executor = RecordingExecutor()
        runtime = AgentRuntime(session, cipher, llm, executor)

        paused = await runtime.run(turn("lookup", [skill.id], True))

        assert paused.status == "needs_input"
        assert executor.calls == []
        stored_before_resume = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == paused.conversation_id)
            .order_by(ChatMessage.sequence)
        ).all()
        assert stored_before_resume[-1].content["tool_calls"] == [
            {
                "id": "clarify_reference",
                "name": "ask_user",
                "arguments": {
                    "question": "Which reference genome?",
                    "reason": "Coordinates depend on it.",
                    "fields": ["reference"],
                },
            }
        ]

        resumed = await runtime.run(
            turn("GRCh38", [], True, conversation_id=paused.conversation_id)
        )

        assert resumed.status == "completed"
        assert executor.calls == []
        resume_history = llm.calls[2]["messages"]
        assistant = resume_history[-2]
        observation = resume_history[-1]
        assert [call.id for call in assistant.tool_calls] == ["clarify_reference"]
        assert observation.role == "tool"
        assert observation.tool_call_id == "clarify_reference"
        assert observation.content == {"answer": "GRCh38"}


@pytest.mark.asyncio
async def test_multiple_clarifications_persist_and_resume_only_the_first(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="clarify_reference",
                            name="ask_user",
                            arguments={
                                "question": "Which reference genome?",
                                "reason": "Coordinates depend on it.",
                                "fields": ["reference"],
                            },
                        ),
                        CanonicalToolCall(
                            id="clarify_format",
                            name="ask_user",
                            arguments={
                                "question": "Which output format?",
                                "reason": "Formatting is ambiguous.",
                                "fields": ["format"],
                            },
                        ),
                    ],
                ),
                CanonicalResponse(content="Used GRCh38."),
            ]
        )
        runtime = AgentRuntime(session, cipher, llm, RecordingExecutor())

        paused = await runtime.run(turn("lookup", [skill.id], True))

        assert paused.status == "needs_input"
        assert paused.pending is not None
        assert paused.pending["tool_call_id"] == "clarify_reference"
        stored_before_resume = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == paused.conversation_id)
            .order_by(ChatMessage.sequence)
        ).all()
        assert [call["id"] for call in stored_before_resume[-1].content["tool_calls"]] == [
            "clarify_reference"
        ]

        resumed = await runtime.run(
            turn("GRCh38", [], True, conversation_id=paused.conversation_id)
        )

        assert resumed.status == "completed"
        resume_history = llm.calls[2]["messages"]
        assert [call.id for call in resume_history[-2].tool_calls] == ["clarify_reference"]
        assert resume_history[-1].tool_call_id == "clarify_reference"


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_load_order", [False, True])
async def test_shared_tool_is_exposed_once_across_loaded_skills(
    db_session_factory,
    reverse_load_order: bool,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        gene_skill, gene_tool = seed_runtime(session, cipher)
        shared_skill = add_skill_sharing_tool(session, gene_tool)
        loaded_ids = [gene_skill.id, shared_skill.id]
        if reverse_load_order:
            loaded_ids.reverse()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_conflict",
                            name="load_skills",
                            arguments={"skill_ids": loaded_ids},
                        )
                    ],
                ),
                CanonicalResponse(content="Shared Tool loaded."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn(
                "lookup",
                [gene_skill.id, shared_skill.id],
                False,
            )
        )

        assert result.content == "Shared Tool loaded."
        assert [tool.name for tool in llm.calls[1]["tools"]] == ["get_gene"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["stopped", "deleted", "unbound"])
async def test_tool_call_is_reauthorized_after_llm_wait(
    db_session_factory,
    revocation: str,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = DeferredToolCallLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("gene", "get_gene", {"symbol": "ABCA4"})
                    ],
                ),
                CanonicalResponse(content="Authorization was revoked."),
            ]
        )
        executor = RecordingExecutor()
        task = asyncio.create_task(
            AgentRuntime(session, cipher, llm, executor).run(
                turn("lookup", [skill.id], False)
            )
        )
        await asyncio.wait_for(llm.tool_call_started.wait(), timeout=2)

        with db_session_factory() as concurrent:
            stored = concurrent.get(Skill, skill.id)
            if revocation == "stopped":
                stored.running = False
            elif revocation == "deleted":
                stored.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                concurrent.query(AgentSkill).filter_by(
                    agent_id=TEST_AGENT_ID,
                    skill_id=skill.id,
                ).delete()
            concurrent.commit()

        llm.release_tool_call.set()
        result = await task

        assert result.content == "Authorization was revoked."
        assert executor.calls == []
        assert llm.calls[2]["messages"][-1].content == {
            "error": "tool_unavailable",
            "tool": "get_gene",
        }


@pytest.mark.asyncio
async def test_shared_tool_remains_authorized_by_another_loaded_skill_after_llm_wait(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        first, tool = seed_runtime(session, cipher)
        second = add_skill_sharing_tool(session, tool)
        llm = DeferredToolCallLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            "load",
                            "load_skills",
                            {"skill_ids": [first.id, second.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("gene", "get_gene", {"symbol": "ABCA4"})
                    ],
                ),
                CanonicalResponse(content="Shared authorization remained valid."),
            ]
        )
        executor = RecordingExecutor()
        task = asyncio.create_task(
            AgentRuntime(session, cipher, llm, executor).run(
                turn("lookup", [first.id, second.id], False)
            )
        )
        await asyncio.wait_for(llm.tool_call_started.wait(), timeout=2)

        with db_session_factory() as concurrent:
            concurrent.query(AgentSkill).filter_by(
                agent_id=TEST_AGENT_ID,
                skill_id=first.id,
            ).delete()
            concurrent.commit()

        llm.release_tool_call.set()
        result = await task

        assert result.content == "Shared authorization remained valid."
        assert [call[0] for call in executor.calls] == ["get_gene"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_state", ["disabled", "deleted"])
async def test_inactive_agent_revokes_shared_tool_during_llm_wait(
    db_session_factory,
    agent_state: str,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        first, tool = seed_runtime(session, cipher)
        second = add_skill_sharing_tool(session, tool)
        llm = DeferredToolCallLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            "load",
                            "load_skills",
                            {"skill_ids": [first.id, second.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("gene", "get_gene", {"symbol": "ABCA4"})
                    ],
                ),
                CanonicalResponse(content="The Agent authorization was revoked."),
            ]
        )
        executor = RecordingExecutor()
        task = asyncio.create_task(
            AgentRuntime(session, cipher, llm, executor).run(
                turn("lookup", [first.id, second.id], False)
            )
        )
        await asyncio.wait_for(llm.tool_call_started.wait(), timeout=2)

        with db_session_factory() as concurrent:
            agent = concurrent.get(Agent, TEST_AGENT_ID)
            if agent_state == "disabled":
                agent.enabled = False
            else:
                agent.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            concurrent.commit()

        llm.release_tool_call.set()
        result = await task

        assert result.status == "completed"
        assert result.content == "The Agent authorization was revoked."
        assert executor.calls == []
        assert llm.calls[2]["messages"][-1].content == {
            "error": "tool_unavailable",
            "tool": "get_gene",
        }
        conversation = session.get(Conversation, result.conversation_id)
        assert conversation.agent_status == "completed"


@pytest.mark.asyncio
async def test_distinct_tools_with_the_same_name_are_rejected(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        gene_skill, _gene_tool = seed_runtime(session, cipher)
        collision_skill, collision_tool = add_compound_skill(session)
        collision_tool.name = "get_gene"
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_conflict",
                            name="load_skills",
                            arguments={"skill_ids": [gene_skill.id, collision_skill.id]},
                        )
                    ],
                )
            ]
        )

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
                turn("lookup", [gene_skill.id, collision_skill.id], False)
            )

        assert error.value.code == "agent.tool_name_conflict"
        assert error.value.params["conflicts"][0]["tool_name"] == "get_gene"
        assert error.value.params["conflicts"][0]["tool_ids"] == sorted(
            [_gene_tool.id, collision_tool.id]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "validator"),
    [
        ({"symbol": 123}, "type"),
        ({"symbol": "ABCA4", "unexpected": True}, "additionalProperties"),
    ],
)
async def test_invalid_business_tool_arguments_are_observed_without_execution(
    db_session_factory, arguments, validator
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("bad", "get_gene", arguments)],
                ),
                CanonicalResponse(content="I could not run the Tool safely."),
            ]
        )
        executor = StrictRecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            turn("lookup", [skill.id], False)
        )

        assert result.status == "completed"
        assert executor.calls == []
        observation = llm.calls[2]["messages"][-1].content
        assert observation["error"] == "invalid_tool_arguments"
        assert observation["tool"] == "get_gene"
        assert observation["validation_errors"][0]["validator"] == validator


@pytest.mark.asyncio
async def test_business_tool_enum_is_validated_before_execution(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, tool = seed_runtime(session, cipher)
        tool.input_schema["properties"]["build"] = {
            "type": "string",
            "enum": ["GRCh37", "GRCh38"],
        }
        tool.input_schema["required"].append("build")
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    tool_calls=[
                        CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                    content="",
                ),
                CanonicalResponse(
                    tool_calls=[
                        CanonicalToolCall("bad", "get_gene", {"symbol": "ABCA4", "build": "hg19"})
                    ],
                    content="",
                ),
                CanonicalResponse(content="Invalid build."),
            ]
        )
        executor = RecordingExecutor()

        await AgentRuntime(session, cipher, llm, executor).run(turn("lookup", [skill.id], False))

        assert executor.calls == []
        assert llm.calls[2]["messages"][-1].content["validation_errors"][0]["validator"] == "enum"


@pytest.mark.asyncio
async def test_malformed_ask_user_is_observed_instead_of_pausing(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            "bad-ask",
                            "ask_user",
                            {"question": "", "reason": 42, "fields": [""]},
                        )
                    ],
                ),
                CanonicalResponse(content="Please provide the missing reference."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn("lookup", [skill.id], True)
        )

        assert result.status == "completed"
        observation = llm.calls[2]["messages"][-1].content
        assert observation["error"] == "invalid_control_arguments"
        assert observation["tool"] == "ask_user"


@pytest.mark.asyncio
async def test_existing_conversation_filters_unavailable_candidates_and_continues(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        first, _tool = seed_runtime(session, cipher)
        second, _second_tool = add_compound_skill(session)
        first_llm = SequencedLlm([CanonicalResponse(content="First answer.")])
        runtime = AgentRuntime(session, cipher, first_llm, RecordingExecutor())
        created = await runtime.run(turn("start", [first.id, second.id], False))
        first.running = False
        session.commit()
        next_llm = SequencedLlm([CanonicalResponse(content="Continued.")])

        continued = await AgentRuntime(session, cipher, next_llm, RecordingExecutor()).run(
            turn("continue", [], False, conversation_id=created.conversation_id)
        )

        assert continued.content == "Continued."
        catalog = json.loads(next_llm.calls[0]["messages"][1].content)
        assert [item["id"] for item in catalog["skills"]] == [second.id]


@pytest.mark.asyncio
async def test_existing_conversation_drops_loaded_skill_when_it_becomes_unavailable(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        first, _tool = seed_runtime(session, cipher)
        second, _second_tool = add_compound_skill(session)
        created = await AgentRuntime(
            session,
            cipher,
            SequencedLlm(
                [
                    CanonicalResponse(
                        content="",
                        tool_calls=[
                            CanonicalToolCall("load", "load_skills", {"skill_ids": [first.id]})
                        ],
                    ),
                    CanonicalResponse(content="First."),
                ]
            ),
            RecordingExecutor(),
        ).run(turn("start", [first.id, second.id], False))
        first.running = False
        session.commit()
        next_llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("load-second", "load_skills", {"skill_ids": [second.id]})
                    ],
                ),
                CanonicalResponse(content="Continued."),
            ]
        )

        result = await AgentRuntime(session, cipher, next_llm, RecordingExecutor()).run(
            turn("continue", [], False, conversation_id=created.conversation_id)
        )

        assert result.content == "Continued."
        assert [tool.name for tool in next_llm.calls[0]["tools"]] == ["load_skills"]
        conversation = session.get(Conversation, created.conversation_id)
        assert conversation.loaded_skill_ids == [second.id]


@pytest.mark.asyncio
async def test_existing_conversation_fails_only_when_no_candidates_remain(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        runtime = AgentRuntime(
            session,
            cipher,
            SequencedLlm([CanonicalResponse(content="First.")]),
            RecordingExecutor(),
        )
        created = await runtime.run(turn("start", [skill.id], False))
        skill.running = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await runtime.run(turn("continue", [], False, conversation_id=created.conversation_id))

        assert error.value.code == "agent.no_eligible_skills"


@pytest.mark.asyncio
async def test_loads_multiple_skills_for_a_compound_task(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        gene_skill, _gene_tool = seed_runtime(session, cipher)
        disease_skill, _disease_tool = add_compound_skill(session)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_both",
                            name="load_skills",
                            arguments={
                                "skill_ids": [
                                    disease_skill.id,
                                    gene_skill.id,
                                    disease_skill.id,
                                ]
                            },
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="gene_1",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        ),
                        CanonicalToolCall(
                            id="disease_1",
                            name="get_disease",
                            arguments={"symbol": "ABCA4"},
                        ),
                    ],
                ),
                CanonicalResponse(content="| Gene | Disease |\n|---|---|\n| ABCA4 | STGD1 |"),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            turn(
                user_content="Combine ABCA4 locus and disease data",
                candidate_skill_ids=[],
                interactive=False,
            )
        )

        assert result.loaded_skill_ids == [disease_skill.id, gene_skill.id]
        assert [tool.name for tool in llm.calls[1]["tools"]] == [
            "get_disease",
            "get_gene",
        ]
        assert [call[0] for call in executor.calls] == ["get_gene", "get_disease"]


@pytest.mark.asyncio
async def test_invalid_load_is_observed_and_can_be_corrected(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        invalid_id = skill.id + 999
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="bad_load",
                            name="load_skills",
                            arguments={"skill_ids": [invalid_id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="good_load",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(content="Recovered."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn("route", [skill.id], False)
        )

        assert result.status == "completed"
        invalid_observation = llm.calls[1]["messages"][-1]
        assert invalid_observation.content == {
            "error": "invalid_skill_ids",
            "requested_skill_ids": [invalid_id],
            "candidate_skill_ids": [skill.id],
        }


@pytest.mark.asyncio
async def test_load_skills_schema_rejects_wrong_argument_type(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("bad-load", "load_skills", {"skill_ids": str(skill.id)})
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("good-load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                ),
                CanonicalResponse(content="Recovered."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn("route", [skill.id], False)
        )

        assert result.content == "Recovered."
        observation = llm.calls[1]["messages"][-1].content
        assert observation["error"] == "invalid_control_arguments"
        assert observation["tool"] == "load_skills"
        assert observation["validation_errors"][0]["validator"] == "type"


@pytest.mark.asyncio
async def test_rejects_stopped_explicit_candidate(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        skill.running = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                turn("route", [skill.id], False)
            )

        assert error.value.code == "agent.skill_unavailable"
        assert error.value.params == {"skill_ids": [skill.id]}


@pytest.mark.asyncio
async def test_tool_failure_becomes_observation_and_model_can_recover(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="gene_1",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        )
                    ],
                ),
                CanonicalResponse(content="The upstream Tool failed with HTTP 403."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, FailingExecutor()).run(
            turn("lookup", [skill.id], False)
        )

        assert result.status == "completed"
        assert result.content == "The upstream Tool failed with HTTP 403."
        assert llm.calls[2]["messages"][-1].content == {
            "error": "upstream_error",
            "message": "Upstream API returned HTTP 403",
            "tool": "get_gene",
        }


@pytest.mark.asyncio
async def test_iteration_exhaustion_is_a_structured_agent_error(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        repeated = CanonicalResponse(
            content="",
            tool_calls=[
                CanonicalToolCall(
                    id="bad_load",
                    name="load_skills",
                    arguments={"skill_ids": [skill.id + 1]},
                )
            ],
        )
        runtime = AgentRuntime(
            session,
            cipher,
            SequencedLlm([repeated, repeated]),
            RecordingExecutor(),
            max_iterations=2,
        )

        with pytest.raises(AgentError) as error:
            await runtime.run(turn("loop", [skill.id], False))

        assert error.value.code == "agent.iteration_limit"
        assert error.value.params == {"max_iterations": 2}
        conversation = session.scalar(select(Conversation))
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == (
            "Agent stopped after reaching the 2-iteration limit."
        )


@pytest.mark.asyncio
async def test_unavailable_agent_configuration_is_structured(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        seed_runtime(session, cipher)
        agent = session.get(Agent, 1)
        agent.enabled = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                turn("hello", [], False)
            )

        assert error.value.code == "agent.unavailable"


@pytest.mark.asyncio
async def test_existing_conversation_records_provider_configuration_failure(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        conversation = Conversation(
            agent_id=1,
            browser_chat_session_id=1,
            candidate_skill_ids=[skill.id],
            candidate_scope_source="explicit",
            loaded_skill_ids=[],
            agent_mode="react",
            agent_status="completed",
        )
        session.add(conversation)
        provider = session.scalar(select(LlmProvider))
        provider.enabled = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                turn("continue", [], False, conversation_id=conversation.id)
            )

        assert error.value.code == "agent.provider_unavailable"
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == "Agent provider is unavailable."


@pytest.mark.asyncio
async def test_loaded_prompt_only_skill_does_not_reenter_routing(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, tool = seed_runtime(session, cipher)
        tool.enabled = False
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(content="Answered from Skill instructions."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn("Explain the Skill", [skill.id], False)
        )

        assert result.status == "completed"
        assert llm.calls[1]["tools"] == []


@pytest.mark.asyncio
async def test_invalid_tool_session_becomes_a_recoverable_observation(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, tool = seed_runtime(session, cipher)
        session.add(GlobalToolAuthConfig(id=1, enabled=True, login_tool_id=tool.id))
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load_1",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="gene_1",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        )
                    ],
                ),
                CanonicalResponse(content="Please sign in again."),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn(
                "lookup",
                [skill.id],
                False,
                tool_session_id="expired-token",
            )
        )

        assert result.status == "authorization_required"
        assert result.pending == {
            "api_source_id": tool.api_source_id,
            "api_source_name": "Gene API",
            "flows": ["swagger"],
        }


@pytest.mark.asyncio
async def test_oauth_configured_tool_without_session_requires_authorization(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, tool = seed_runtime(session, cipher)
        session.add(
            ApiSourceOAuthConfig(
                api_source_id=tool.api_source_id,
                encrypted_config=cipher.encrypt_json({"client_secret": "never-observe"}),
                enabled=True,
            )
        )
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall(id="load", name="load_skills", arguments={"skill_ids": [skill.id]})],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall(id="tool", name="get_gene", arguments={"symbol": "ABCA4"})],
                ),
                CanonicalResponse(content="Please authorize the Tool."),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            turn("lookup", [skill.id], False)
        )

        assert result.status == "authorization_required"
        assert result.pending == {
            "api_source_id": tool.api_source_id,
            "api_source_name": "Gene API",
            "flows": ["pkce"],
        }
        assert executor.calls == []
        assert "never-observe" not in str(llm.calls)


@pytest.mark.asyncio
async def test_browser_chat_pauses_for_oauth_authorization(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, tool = seed_runtime(session, cipher)
        session.add(
            ApiSourceOAuthConfig(
                api_source_id=tool.api_source_id,
                encrypted_config=cipher.encrypt_json({"client_secret": "never-observe"}),
                enabled=True,
            )
        )
        session.commit()
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="load",
                            name="load_skills",
                            arguments={"skill_ids": [skill.id]},
                        )
                    ],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall(
                            id="tool",
                            name="get_gene",
                            arguments={"symbol": "ABCA4"},
                        )
                    ],
                ),
            ]
        )

        result = await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
            turn("lookup", [skill.id], True)
        )

        assert result.status == "authorization_required"
        assert result.pending == {
            "api_source_id": tool.api_source_id,
            "api_source_name": "Gene API",
            "flows": ["pkce"],
        }
        tool_session = ToolUserSession(
            token_hash="b" * 64,
            agent_id=TEST_AGENT_ID,
            browser_chat_session_id=1,
            status="ready",
            idle_expires_at=datetime(2099, 1, 1),
            absolute_expires_at=datetime(2099, 1, 1),
            last_used_at=datetime(2026, 7, 23),
        )
        session.add(tool_session)
        session.flush()
        session.add(
            ToolSessionCredential(
                tool_session_id=tool_session.id,
                api_source_id=tool.api_source_id,
                encrypted_credentials=cipher.encrypt_json(
                    auth_to_json(
                        RequestAuth(
                            headers={"Authorization": "Bearer browser"}
                        )
                    )
                ),
                status="ready",
                expires_at=datetime(2099, 1, 1),
                last_used_at=datetime(2026, 7, 23),
            )
        )
        session.commit()
        executor = RecordingExecutor()
        resumed = await AgentRuntime(
            session,
            cipher,
            SequencedLlm(
                [
                    CanonicalResponse(
                        content="",
                        tool_calls=[
                            CanonicalToolCall(
                                id="retry",
                                name="get_gene",
                                arguments={"symbol": "ABCA4"},
                            )
                        ],
                    ),
                    CanonicalResponse(content="Authorized result."),
                ]
            ),
            executor,
        ).run(
            turn(
                "",
                [],
                True,
                conversation_id=result.conversation_id,
            )
        )

        assert resumed.status == "completed"
        assert resumed.content == "Authorized result."
        assert executor.calls[0][2].headers == {
            "Authorization": "Bearer browser"
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ToolSessionNotFound("missing"), "tool_authorization_required"),
        (ToolSessionExpired("expired"), "tool_reauthorization_required"),
        (ToolSessionReauthorizationRequired("rejected"), "tool_reauthorization_required"),
        (ToolSessionError("unexpected"), "tool_session_error"),
    ],
)
async def test_agent_maps_tool_session_failures_without_leaking_messages(
    db_session_factory, monkeypatch, failure, expected
) -> None:
    async def fail_execute(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("chat4openapi.chat.agent.ToolSessionService.execute", fail_execute)
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        _skill, tool = seed_runtime(session, cipher)
        observation = await AgentRuntime(
            session, cipher, SequencedLlm([]), RecordingExecutor()
        )._execute_tool(
            tool,
            {"symbol": "ABCA4"},
            "opaque-session",
            agent_id=1,
            agent_key_id=1,
            admin_session_id=None,
        )

        assert observation == {"error": expected, "tool": "get_gene"}


@pytest.mark.asyncio
async def test_provider_failure_marks_conversation_failed_with_redacted_summary(
    db_session_factory,
) -> None:
    class ProviderFailureLlm:
        async def complete(self, **_kwargs):
            raise LlmProviderError(502, {"body": "upstream secret token sk-do-not-store"})

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, ProviderFailureLlm(), RecordingExecutor()).run(
                turn("lookup", [skill.id], False)
            )

        assert error.value.code == "agent.provider_failed"
        conversation = session.scalar(select(Conversation))
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == "LLM provider request failed."
        assert "secret" not in str(error.value.params).lower()
        assert "sk-do-not-store" not in str(error.value.params)


@pytest.mark.asyncio
async def test_unexpected_runtime_failure_is_structured_and_redacted(
    db_session_factory,
) -> None:
    class MalformedLlm:
        async def complete(self, **_kwargs):
            return None

    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, MalformedLlm(), RecordingExecutor()).run(
                turn("lookup", [skill.id], False)
            )

        assert error.value.code == "agent.runtime_failed"
        conversation = session.scalar(select(Conversation))
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == "Agent runtime failed."


@pytest.mark.asyncio
async def test_provider_credential_decryption_failure_is_structured_and_redacted(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        provider = session.scalar(select(LlmProvider))
        provider.encrypted_api_key = b"not-a-valid-provider-secret"
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                turn("lookup", [skill.id], False)
            )

        assert error.value.code == "agent.runtime_failed"
        assert error.value.params == {"reason": "Agent runtime failed."}
        conversation = session.scalar(select(Conversation))
        assert conversation.agent_status == "failed"
        assert conversation.latest_failure_summary == "Agent runtime failed."
        assert "not-a-valid" not in str(error.value.params)


@pytest.mark.asyncio
async def test_new_turn_clears_previous_failure_before_llm_and_on_completion(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        conversation = Conversation(
            agent_id=1,
            browser_chat_session_id=1,
            candidate_skill_ids=[skill.id],
            candidate_scope_source="explicit",
            loaded_skill_ids=[],
            agent_mode="react",
            agent_status="failed",
            latest_failure_summary="Old failure.",
        )
        session.add(conversation)
        session.commit()

        class StateInspectingLlm:
            async def complete(inner_self, **_kwargs):
                session.refresh(conversation)
                assert conversation.agent_status == "running"
                assert conversation.latest_failure_summary is None
                return CanonicalResponse(content="Recovered.")

        result = await AgentRuntime(session, cipher, StateInspectingLlm(), RecordingExecutor()).run(
            turn("retry", [], False, conversation_id=conversation.id)
        )

        assert result.content == "Recovered."
        assert conversation.agent_status == "completed"
        assert conversation.latest_failure_summary is None
