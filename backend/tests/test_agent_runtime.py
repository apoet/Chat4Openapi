import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from chatapi.chat.agent import AgentError, AgentRuntime, AgentTurnRequest
from chatapi.llm.client import CanonicalResponse, CanonicalToolCall
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
from chatapi.tools.executor import ToolExecutionResult
from chatapi.tools.errors import ToolExecutionError


class SequencedLlm:
    def __init__(self, responses: list[CanonicalResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
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


class FailingExecutor:
    async def execute(self, _tool, _source, _arguments, _auth):
        raise ToolExecutionError("upstream_error", "Upstream API returned HTTP 403")


def seed_runtime(session, cipher: SecretCipher) -> tuple[Skill, Tool]:
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
        AgentConfig(
            id=1,
            name="ChatAPI Agent",
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
        name="Gene lookup",
        description="Look up gene loci.",
        system_prompt="Return gene loci as Markdown tables.",
        running=True,
    )
    session.add_all([tool, skill])
    session.flush()
    session.add(SkillTool(skill_id=skill.id, tool_id=tool.id, position=0))
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
    session.add(SkillTool(skill_id=skill.id, tool_id=tool.id, position=0))
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
    session.add(SkillTool(skill_id=skill.id, tool_id=tool.id, position=0))
    session.commit()
    return skill


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
                    content="| Field | Result |\n|---|---|\n| Gene | ABCA4 |",
                    stop_reason="stop",
                ),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(
            AgentTurnRequest(
                user_content="查询 ABCA4 位点",
                candidate_skill_ids=[skill.id],
                interactive=False,
            )
        )

        assert result.status == "completed"
        assert result.loaded_skill_ids == [skill.id]
        assert "| Gene | ABCA4 |" in result.content
        assert [tool.name for tool in llm.calls[0]["tools"]] == ["load_skills"]
        catalog = json.loads(llm.calls[0]["messages"][1].content)
        assert catalog == {
            "skills": [
                {
                    "id": skill.id,
                    "name": "Gene lookup",
                    "description": "Look up gene loci.",
                }
            ]
        }
        assert "Return gene loci" not in "\n".join(
            str(message.content) for message in llm.calls[0]["messages"]
        )
        assert [tool.name for tool in llm.calls[1]["tools"]] == ["get_gene"]
        assert any(
            message.role == "system" and "Return gene loci" in message.content
            for message in llm.calls[1]["messages"]
        )
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
            AgentTurnRequest(
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
            AgentTurnRequest(
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

        paused = await runtime.run(AgentTurnRequest("lookup", [skill.id], True))

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
            AgentTurnRequest("GRCh38", [], True, conversation_id=paused.conversation_id)
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

        paused = await runtime.run(AgentTurnRequest("lookup", [skill.id], True))

        assert paused.status == "needs_input"
        assert paused.pending is not None
        assert paused.pending["tool_call_id"] == "clarify_reference"
        stored_before_resume = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == paused.conversation_id)
            .order_by(ChatMessage.sequence)
        ).all()
        assert [
            call["id"] for call in stored_before_resume[-1].content["tool_calls"]
        ] == ["clarify_reference"]

        resumed = await runtime.run(
            AgentTurnRequest("GRCh38", [], True, conversation_id=paused.conversation_id)
        )

        assert resumed.status == "completed"
        resume_history = llm.calls[2]["messages"]
        assert [call.id for call in resume_history[-2].tool_calls] == [
            "clarify_reference"
        ]
        assert resume_history[-1].tool_call_id == "clarify_reference"


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_load_order", [False, True])
async def test_rejects_cross_skill_business_tool_name_conflicts_independent_of_order(
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
                )
            ]
        )

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, llm, RecordingExecutor()).run(
                AgentTurnRequest(
                    "lookup",
                    [gene_skill.id, shared_skill.id],
                    False,
                )
            )

        assert error.value.code == "agent.tool_name_conflict"
        assert error.value.params == {
            "conflicts": [
                {
                    "tool_name": "get_gene",
                    "skill_ids": sorted([gene_skill.id, shared_skill.id]),
                }
            ]
        }


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
            AgentTurnRequest(
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
            AgentTurnRequest("route", [skill.id], False)
        )

        assert result.status == "completed"
        invalid_observation = llm.calls[1]["messages"][-1]
        assert invalid_observation.content == {
            "error": "invalid_skill_ids",
            "requested_skill_ids": [invalid_id],
            "candidate_skill_ids": [skill.id],
        }


@pytest.mark.asyncio
async def test_rejects_stopped_explicit_candidate(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, _tool = seed_runtime(session, cipher)
        skill.running = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                AgentTurnRequest("route", [skill.id], False)
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
            AgentTurnRequest("lookup", [skill.id], False)
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
            await runtime.run(AgentTurnRequest("loop", [skill.id], False))

        assert error.value.code == "agent.iteration_limit"
        assert error.value.params == {"max_iterations": 2}
        conversation = session.scalar(select(Conversation))
        assert conversation.agent_status == "failed"


@pytest.mark.asyncio
async def test_unavailable_agent_configuration_is_structured(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        seed_runtime(session, cipher)
        agent = session.get(AgentConfig, 1)
        agent.enabled = False
        session.commit()

        with pytest.raises(AgentError) as error:
            await AgentRuntime(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                AgentTurnRequest("hello", [], False)
            )

        assert error.value.code == "agent.unavailable"


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
            AgentTurnRequest("Explain the Skill", [skill.id], False)
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
        session.add(
            GlobalToolAuthConfig(id=1, enabled=True, login_tool_id=tool.id)
        )
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
            AgentTurnRequest(
                "lookup",
                [skill.id],
                False,
                tool_session_id="expired-token",
            )
        )

        assert result.status == "completed"
        assert llm.calls[2]["messages"][-1].content == {
            "error": "tool_session_error",
            "message": "Tool Session was not found",
            "tool": "get_gene",
        }
