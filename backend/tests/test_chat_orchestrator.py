from cryptography.fernet import Fernet
import pytest
from sqlalchemy import select

from chatapi.chat.orchestrator import ChatError, ChatOrchestrator, SkillNotRunning, ToolLoopLimitExceeded
from chatapi.llm.client import CanonicalResponse, CanonicalToolCall
from chatapi.models import (
    ApiSource,
    ChatMessage,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chatapi.security.encryption import SecretCipher
from chatapi.tools.executor import ToolExecutionResult
from chatapi.tools.errors import ToolExecutionError


class SequencedLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool, _source, arguments, auth):
        self.calls.append((tool.name, arguments, auth))
        return ToolExecutionResult(200, {"name": "Milo"}, "application/json")


class FailingExecutor:
    async def execute(self, _tool, _source, _arguments, _auth):
        raise ToolExecutionError("upstream_error", "Upstream API returned HTTP 403")


def seed(session, cipher: SecretCipher, *, running: bool = True) -> Skill:
    provider = LlmProvider(
        name="Primary",
        provider_type="openai",
        base_url="https://llm.test/v1",
        encrypted_api_key=cipher.encrypt_json({"api_key": "provider-secret"}),
        default_model="gpt-test",
    )
    source = ApiSource(name="API", source_type="openapi", base_url="https://api.test")
    session.add_all([provider, source])
    session.flush()
    tool = Tool(
        api_source_id=source.id,
        operation_key="GET /pets/{id}",
        name="get_pet",
        description="Get a pet",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
        execution_schema={"method": "GET", "path": "/pets/{id}", "parameters": []},
        enabled=True,
    )
    skill = Skill(
        name="Pet helper",
        system_prompt="Use pet tools.",
        provider_id=provider.id,
        running=running,
    )
    session.add_all([tool, skill])
    session.flush()
    session.add(SkillTool(skill_id=skill.id, tool_id=tool.id, position=0))
    session.commit()
    return skill


@pytest.mark.asyncio
async def test_runs_bounded_tool_loop_and_persists_conversation(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill = seed(session, cipher)
        llm = SequencedLlm(
            [
                CanonicalResponse(
                    content="",
                    tool_calls=[CanonicalToolCall(id="call_1", name="get_pet", arguments={"id": 7})],
                    stop_reason="tool_calls",
                ),
                CanonicalResponse(content="Milo is pet 7.", stop_reason="stop"),
            ]
        )
        executor = RecordingExecutor()
        result = await ChatOrchestrator(session, cipher, llm, executor).run(
            skill_id=skill.id,
            messages=[{"role": "user", "content": "Find pet 7"}],
        )

        assert result.content == "Milo is pet 7."
        assert executor.calls[0][0:2] == ("get_pet", {"id": 7})
        assert llm.calls[0]["api_key"] == "provider-secret"
        assert [tool.name for tool in llm.calls[0]["tools"]] == ["get_pet"]
        assert "tool_session_id" not in llm.calls[0]["tools"][0].input_schema["properties"]
        second_messages = llm.calls[1]["messages"]
        assert second_messages[-1].tool_call_id == "call_1"
        assert second_messages[-1].content == {"name": "Milo"}
        stored = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == result.conversation_id)
            .order_by(ChatMessage.sequence)
        ).all()
        assert [message.role for message in stored] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_rejects_stopped_skill_and_unbounded_model_loop(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        stopped = seed(session, cipher, running=False)
        with pytest.raises(SkillNotRunning):
            await ChatOrchestrator(session, cipher, SequencedLlm([]), RecordingExecutor()).run(
                skill_id=stopped.id, messages=[{"role": "user", "content": "hello"}]
            )
        stopped.running = True
        session.commit()
        repeated = CanonicalResponse(
            content="",
            tool_calls=[CanonicalToolCall(id="again", name="get_pet", arguments={"id": 7})],
        )
        with pytest.raises(ToolLoopLimitExceeded):
            await ChatOrchestrator(
                session,
                cipher,
                SequencedLlm([repeated, repeated]),
                RecordingExecutor(),
                max_iterations=2,
            ).run(skill_id=stopped.id, messages=[{"role": "user", "content": "loop"}])


@pytest.mark.asyncio
async def test_normalizes_tool_failures_as_chat_errors(db_session_factory) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    with db_session_factory() as session:
        skill = seed(session, cipher)
        llm = SequencedLlm([
            CanonicalResponse(content="", tool_calls=[CanonicalToolCall(
                id="call_1", name="get_pet", arguments={"id": 7},
            )]),
        ])

        with pytest.raises(ChatError, match="get_pet.*upstream_error"):
            await ChatOrchestrator(session, cipher, llm, FailingExecutor()).run(
                skill_id=skill.id, messages=[{"role": "user", "content": "Find pet 7"}],
            )
