from datetime import datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from chat4openapi.agui.contracts import AguiRunInput
from chat4openapi.agui.runtime import AguiRuntime
from chat4openapi.chat.agent import AgentRuntime, AgentTurnRequest
from chat4openapi.llm.client import (
    CanonicalMessage,
    CanonicalResponse,
    CanonicalTool,
    CanonicalToolCall,
)
from chat4openapi.models import (
    Agent,
    AgentEmbed,
    AgentSkill,
    ApiSource,
    ApiSourceOAuthConfig,
    Conversation,
    EmbedSession,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.executor import ToolExecutionResult


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

    async def execute(self, tool, _source, arguments, _auth):
        self.calls.append((tool.name, arguments))
        return ToolExecutionResult(200, {"symbol": "ABCA4"}, "application/json")


def _seed(session, cipher: SecretCipher) -> tuple[Skill, EmbedSession]:
    provider = LlmProvider(
        name="Primary",
        provider_type="openai",
        base_url="https://llm.example/v1",
        encrypted_api_key=cipher.encrypt_json({"api_key": "provider-secret"}),
        default_model="gpt-test",
    )
    source = ApiSource(name="Gene API", source_type="openapi", base_url="https://api.example")
    skill = Skill(name="Gene", system_prompt="Use gene Tools.", running=True)
    session.add_all([provider, source, skill])
    session.flush()
    agent = Agent(
        name="Embed Agent",
        enabled=True,
        system_prompt="Help the visitor.",
        provider_id=provider.id,
        mode="react",
    )
    tool = Tool(
        api_source_id=source.id,
        operation_key="GET /genes/{symbol}",
        name="get_gene",
        description="Get a gene",
        input_schema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
        execution_schema={"method": "GET", "path": "/genes/{symbol}", "parameters": []},
        enabled=True,
    )
    session.add_all([agent, tool])
    session.flush()
    session.add_all(
        [
            AgentSkill(agent_id=agent.id, skill_id=skill.id, position=0),
            SkillTool(skill_id=skill.id, tool_id=tool.id, position=0),
        ]
    )
    embed = AgentEmbed(
        agent_id=agent.id,
        name="Site",
        public_id="runtime-embed-id",
        allowed_origins=[],
    )
    session.add(embed)
    session.flush()
    embed_session = EmbedSession(
        embed_id=embed.id,
        agent_id=agent.id,
        public_subject_id="runtime-embed-subject",
        parent_origin="https://host.example",
        token_hash="r" * 64,
        idle_expires_at=datetime(2099, 1, 1),
        absolute_expires_at=datetime(2099, 1, 1),
    )
    session.add(embed_session)
    session.commit()
    return skill, embed_session


def _web_tool() -> CanonicalTool:
    return CanonicalTool(
        name="web__select-row",
        description="Select a host-page row.",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )


def _turn(
    embed_session: EmbedSession,
    *,
    conversation_id: str | None = None,
    incoming_messages: list[CanonicalMessage] | None = None,
) -> AgentTurnRequest:
    return AgentTurnRequest(
        agent_id=embed_session.agent_id,
        user_content="Select row 42",
        candidate_skill_ids=[],
        interactive=False,
        conversation_id=conversation_id,
        embed_session_id=embed_session.id,
        client_tools=[_web_tool()],
        incoming_messages=incoming_messages or [],
    )


@pytest.mark.asyncio
async def test_frontend_tool_is_returned_to_client_and_never_uses_backend_executor(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})],
                ),
                CanonicalResponse(
                    content="Selecting the row.",
                    tool_calls=[CanonicalToolCall("web-1", "web__select-row", {"id": "42"})],
                ),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(_turn(embed_session))

        assert result.status == "client_tool_required"
        assert result.pending == {
            "tool_call_id": "web-1",
            "name": "web__select-row",
            "arguments": {"id": "42"},
        }
        assert executor.calls == []
        conversation = session.get(Conversation, result.conversation_id)
        assert conversation is not None
        assert conversation.embed_session_id == embed_session.id
        assert conversation.agent_key_id is None
        assert conversation.browser_chat_session_id is None


@pytest.mark.asyncio
async def test_backend_tool_still_uses_backend_executor_when_client_tools_are_present(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("gene", "get_gene", {"symbol": "ABCA4"})],
                ),
                CanonicalResponse(content="ABCA4 was found."),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(_turn(embed_session))

        assert result.status == "completed"
        assert executor.calls == [("get_gene", {"symbol": "ABCA4"})]
        assert {tool.name for tool in llm.calls[1]["tools"]} == {
            "get_gene",
            "web__select-row",
        }


@pytest.mark.asyncio
async def test_removed_frontend_tool_becomes_observation_without_backend_fallback(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("gone", "web__removed", {})],
                ),
                CanonicalResponse(content="That page action is no longer available."),
            ]
        )
        executor = RecordingExecutor()

        result = await AgentRuntime(session, cipher, llm, executor).run(_turn(embed_session))

        assert result.status == "completed"
        assert executor.calls == []
        assert llm.calls[2]["messages"][-1].content == {
            "error": "frontend_tool_unavailable",
            "tool": "web__removed",
        }


@pytest.mark.asyncio
async def test_frontend_tool_result_continues_the_same_embed_conversation(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})],
                ),
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall("web-1", "web__select-row", {"id": "42"})],
                ),
                CanonicalResponse(content="Row 42 is selected."),
            ]
        )
        executor = RecordingExecutor()
        runtime = AgentRuntime(session, cipher, llm, executor)
        first = await runtime.run(_turn(embed_session))

        second = await runtime.run(
            _turn(
                embed_session,
                conversation_id=first.conversation_id,
                incoming_messages=[
                    CanonicalMessage(
                        role="tool",
                        content={"selected": "42"},
                        tool_call_id="web-1",
                        name="web__select-row",
                    )
                ],
            )
        )

        assert second.status == "completed"
        assert second.conversation_id == first.conversation_id
        assert second.content == "Row 42 is selected."
        assert executor.calls == []
        conversation = session.scalar(select(Conversation))
        assert conversation is not None
        assert conversation.embed_session_id == embed_session.id


@pytest.mark.asyncio
async def test_agui_adapter_emits_client_tool_and_continues_from_tool_message(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[
                        CanonicalToolCall("load", "load_skills", {"skill_ids": [skill.id]})
                    ],
                ),
                CanonicalResponse(
                    content="Selecting.",
                    tool_calls=[
                        CanonicalToolCall("web-1", "web__select-row", {"id": "42"})
                    ],
                ),
                CanonicalResponse(content="Selected row 42."),
            ]
        )
        executor = RecordingExecutor()
        runtime = AguiRuntime(AgentRuntime(session, cipher, llm, executor))
        first_payload = AguiRunInput.model_validate(
            {
                "threadId": "thread-1",
                "runId": "run-1",
                "messages": [{"id": "user-1", "role": "user", "content": "Select 42"}],
                "tools": [
                    {
                        "name": "web__select-row",
                        "description": "Select a row.",
                        "parameters": _web_tool().input_schema,
                    }
                ],
            }
        )

        first_events = [event async for event in runtime.run(first_payload, embed_session)]

        assert [
            event["type"]
            for event in first_events
            if event["type"].startswith("TOOL_CALL_")
        ] == ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]
        conversation_event = next(
            event
            for event in first_events
            if event.get("name") == "chat4openapi:conversation"
        )
        conversation_id = conversation_event["value"]["conversationId"]
        second_payload = AguiRunInput.model_validate(
            {
                "threadId": "thread-1",
                "runId": "run-2",
                "state": {"conversationId": conversation_id},
                "messages": [
                    {
                        "id": "tool-1",
                        "role": "tool",
                        "toolCallId": "web-1",
                        "content": {"selected": "42"},
                    }
                ],
                "tools": first_payload.model_dump(mode="json")["tools"],
            }
        )

        second_events = [event async for event in runtime.run(second_payload, embed_session)]

        assert any(
            event.get("delta") == "Selected row 42." for event in second_events
        )
        assert executor.calls == []


@pytest.mark.asyncio
async def test_embed_protected_backend_tool_emits_authorization_event(
    db_session_factory,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill, embed_session = _seed(session, cipher)
        source = session.scalar(select(ApiSource))
        assert source is not None
        session.add(
            ApiSourceOAuthConfig(
                api_source_id=source.id,
                encrypted_config=cipher.encrypt_json({"client_secret": "never-expose"}),
                enabled=True,
            )
        )
        session.commit()
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
                        CanonicalToolCall("gene", "get_gene", {"symbol": "ABCA4"})
                    ],
                ),
            ]
        )
        runtime = AguiRuntime(AgentRuntime(session, cipher, llm, RecordingExecutor()))
        payload = AguiRunInput.model_validate(
            {
                "threadId": "thread-auth",
                "runId": "run-auth",
                "messages": [{"id": "user-auth", "role": "user", "content": "Find ABCA4"}],
            }
        )

        events = [event async for event in runtime.run(payload, embed_session)]

        required = next(
            event for event in events if event.get("name") == "authorization_required"
        )
        assert required["value"] == {
            "api_source_id": source.id,
            "api_source_name": "Gene API",
            "flows": ["pkce"],
        }
        assert "never-expose" not in str(events)
        assert len(llm.calls) == 2
