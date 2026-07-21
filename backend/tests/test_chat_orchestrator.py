import pytest

import chatapi.chat.orchestrator as orchestrator_module
from chatapi.chat.agent import AgentTurnRequest, AgentTurnResult
from chatapi.chat.orchestrator import ChatOrchestrator
from chatapi.llm.client import CanonicalMessage


class RecordingRuntime:
    def __init__(self, result: AgentTurnResult) -> None:
        self.result = result
        self.requests: list[AgentTurnRequest] = []

    async def run(self, request: AgentTurnRequest) -> AgentTurnResult:
        self.requests.append(request)
        return self.result


@pytest.mark.asyncio
async def test_compatibility_orchestrator_delegates_to_agent_runtime(monkeypatch) -> None:
    expected = AgentTurnResult(
        conversation_id="conversation-1",
        status="completed",
        content="| Pet | Result |\n|---|---|\n| Milo | Found |",
        loaded_skill_ids=[7],
        pending=None,
        input_tokens=11,
        output_tokens=5,
    )
    runtime = RecordingRuntime(expected)
    constructor_calls = []

    def runtime_factory(session, cipher, llm, tool_runner, *, max_iterations=None):
        constructor_calls.append((session, cipher, llm, tool_runner, max_iterations))
        return runtime

    monkeypatch.setattr(orchestrator_module, "AgentRuntime", runtime_factory, raising=False)
    dependencies = [object(), object(), object(), object()]
    orchestrator = ChatOrchestrator(*dependencies, max_iterations=4)

    result = await orchestrator.run(
        skill_id=7,
        messages=[
            {"role": "system", "content": "Compatibility client context"},
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
            {"role": "user", "content": "Find Milo"},
        ],
        tool_session_id="tool-session-1",
        conversation_id="conversation-1",
    )

    assert result is expected
    assert constructor_calls == [(*dependencies, 4)]
    assert runtime.requests == [
        AgentTurnRequest(
            conversation_id="conversation-1",
            user_content="Find Milo",
            candidate_skill_ids=[7],
            interactive=False,
            tool_session_id="tool-session-1",
            incoming_messages=[
                CanonicalMessage(role="system", content="Compatibility client context"),
                CanonicalMessage(role="user", content="older question"),
                CanonicalMessage(role="assistant", content="older answer"),
                CanonicalMessage(role="user", content="Find Milo"),
            ],
            candidate_scope_source="explicit",
        )
    ]


@pytest.mark.asyncio
async def test_compatibility_orchestrator_requires_a_user_message(monkeypatch) -> None:
    runtime = RecordingRuntime(
        AgentTurnResult("unused", "completed", "", [], None, 0, 0)
    )
    monkeypatch.setattr(
        orchestrator_module,
        "AgentRuntime",
        lambda *_args, **_kwargs: runtime,
        raising=False,
    )

    with pytest.raises(ValueError, match="user message"):
        await ChatOrchestrator(object(), object(), object(), object()).run(
            skill_id=1,
            messages=[{"role": "system", "content": "context only"}],
        )

    assert runtime.requests == []
