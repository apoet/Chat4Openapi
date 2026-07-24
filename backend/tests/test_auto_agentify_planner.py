import json

import pytest
from pydantic import ValidationError

from chat4openapi.auto_agentify.catalog import OperationCatalogItem
from chat4openapi.auto_agentify.planner import (
    AutoAgentifyPlanner,
)
from chat4openapi.auto_agentify.progress import ProgressEvent
from chat4openapi.llm.client import CanonicalResponse, LlmProviderError
from chat4openapi.schemas.auto_agentify import (
    AgentPlan,
    CapabilityPreferences,
    GenerationPlan,
    SkillPlan,
)


def _skill(index: int = 0, operation_key: str = "GET /projects") -> SkillPlan:
    return SkillPlan(
        name=f"Project Insights {index}",
        description="Read project information.",
        system_prompt="Use project tools to answer project questions.",
        operation_keys=[operation_key],
        value="Makes project state understandable.",
    )


def _agent(index: int = 0, skill_name: str = "Project Insights 0") -> AgentPlan:
    return AgentPlan(
        name=f"Project Analyst {index}",
        responsibility="Analyze project status.",
        system_prompt="Analyze project information accurately.",
        skill_names=[skill_name],
        mode="react",
        max_iterations=8,
        value="Turns project data into decisions.",
        use_cases=["Summarize project status"],
    )


def _catalog(count: int = 1) -> list[OperationCatalogItem]:
    return [
        OperationCatalogItem(
            operation_key=f"GET /projects{'' if index == 0 else f'/{index}'}",
            name=f"getProject{index}",
            method="GET",
            path=f"/projects{'' if index == 0 else f'/{index}'}",
            tags=("Projects",),
            summary="Get projects",
            description="Returns project data.",
            input_fields=(),
        )
        for index in range(count)
    ]


def _valid_json() -> str:
    return GenerationPlan(skills=[_skill()], agents=[_agent()]).model_dump_json()


def _valid_json_zh() -> str:
    skill = SkillPlan(
        name="项目洞察",
        description="读取并分析项目业务信息。",
        system_prompt="Use project tools to answer project questions.",
        operation_keys=["GET /projects"],
        value="帮助用户快速理解项目状态。",
    )
    agent = AgentPlan(
        name="项目分析 Agent",
        responsibility="分析项目状态并总结关键风险。",
        system_prompt="Analyze project information accurately.",
        skill_names=[skill.name],
        mode="react",
        max_iterations=8,
        value="将项目数据转化为可执行决策。",
        use_cases=["汇总项目状态"],
    )
    return GenerationPlan(skills=[skill], agents=[agent]).model_dump_json()


def _capabilities_json(operation_key: str = "GET /projects") -> str:
    return json.dumps(
        {
            "capabilities": [
                {
                    "name": "Project lifecycle",
                    "description": "Coordinate projects from creation through closure.",
                    "value": "Reduces manual delivery coordination.",
                    "workflow": ["Create", "Assign", "Track", "Close"],
                    "operation_keys": [operation_key],
                    "candidate_skills": ["Project Insights"],
                    "high_impact": False,
                }
            ]
        }
    )


def _capabilities_json_zh(operation_key: str = "GET /projects") -> str:
    return json.dumps(
        {
            "capabilities": [
                {
                    "name": "项目全生命周期",
                    "description": "协调项目从创建到关闭的完整业务流程。",
                    "value": "减少人工协调项目交付所需的时间。",
                    "workflow": ["创建项目", "分配任务", "跟踪进展", "关闭项目"],
                    "operation_keys": [operation_key],
                    "candidate_skills": ["项目洞察"],
                    "high_impact": False,
                }
            ]
        },
        ensure_ascii=False,
    )


class FakeLlmClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list] = []
        self.requests: list[dict] = []

    async def complete(self, **kwargs) -> CanonicalResponse:
        self.requests.append(kwargs)
        self.calls.append(kwargs["messages"])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return CanonicalResponse(content=response)


class CollectingReporter:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)


def test_generation_plan_enforces_limits_and_references() -> None:
    with pytest.raises(ValidationError):
        GenerationPlan(
            skills=[_skill(index, f"GET /projects/{index}") for index in range(21)],
            agents=[_agent()],
        )

    plan = GenerationPlan(skills=[_skill(operation_key="GET /missing")], agents=[_agent()])
    with pytest.raises(ValueError, match="unknown operation"):
        plan.validate_references({"GET /projects"})


def test_capability_preferences_reject_unknown_system_labels_and_normalize_custom() -> None:
    with pytest.raises(ValidationError, match="unknown system capability"):
        CapabilityPreferences(
            allowed_system_capabilities=["not_a_builtin"],
        )

    preferences = CapabilityPreferences(
        allowed_system_capabilities=["file_management", "file_management"],
        custom_capability_labels=[" Clinical trial ", "Clinical trial"],
    )
    assert preferences.allowed_system_capabilities == ["file_management"]
    assert preferences.custom_capability_labels == ["Clinical trial"]


@pytest.mark.asyncio
async def test_planner_corrects_one_invalid_response() -> None:
    client = FakeLlmClient(
        [_capabilities_json(), '{"skills":[],"agents":[]}', _valid_json()]
    )
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
    )

    assert len(client.calls) == 3
    assert plan.skills[0].operation_keys == ["GET /projects"]
    assert "validation errors" in client.calls[2][-1].content


@pytest.mark.asyncio
async def test_planner_corrects_one_invalid_capability_batch() -> None:
    client = FakeLlmClient(
        ["not json", _capabilities_json(), _valid_json()]
    )
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
    )

    assert plan.skills
    assert len(client.calls) == 3
    assert "Allowed operation_keys" in client.calls[1][-1].content
    assert any(
        event.kind == "capability_batch_correction_started"
        for event in reporter.events
    )


@pytest.mark.asyncio
async def test_planner_falls_back_when_capability_correction_is_invalid() -> None:
    client = FakeLlmClient(["not json", "still not json", _valid_json()])
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
        source_name="EDC",
    )

    assert plan.skills
    assert any(
        event.kind == "capability_batch_fallback"
        for event in reporter.events
    )
    discovered = next(
        event for event in reporter.events if event.kind == "capability_discovered"
    )
    assert discovered.capability["name"] == "Projects"


@pytest.mark.asyncio
async def test_planner_filters_unselected_system_capabilities() -> None:
    capability = json.loads(_capabilities_json())
    capability["capabilities"][0].update(
        {
            "name": "AI Writing",
            "description": "Generate text with an AI model.",
            "candidate_skills": ["AI Writing"],
        }
    )
    client = FakeLlmClient([json.dumps(capability), _valid_json()])
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
    )

    assert any(event.kind == "capability_filtered" for event in reporter.events)
    assert not any(
        event.kind == "capability_discovered" for event in reporter.events
    )


@pytest.mark.asyncio
async def test_planner_keeps_selected_system_capabilities() -> None:
    capability = json.loads(_capabilities_json())
    capability["capabilities"][0].update(
        {
            "name": "AI Writing",
            "description": "Generate text with an AI model.",
            "candidate_skills": ["AI Writing"],
        }
    )
    client = FakeLlmClient([json.dumps(capability), _valid_json()])
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
        allowed_system_capabilities=["ai_platform"],
    )

    assert any(
        event.kind == "capability_discovered" for event in reporter.events
    )
    assert not any(event.kind == "capability_filtered" for event in reporter.events)


@pytest.mark.asyncio
async def test_planner_blocks_sensitive_information_and_security_unless_selected() -> None:
    capability = json.loads(_capabilities_json())
    capability["capabilities"][0].update(
        {
            "name": "Sensitive data security",
            "description": "Mask personal information and respond to security incidents.",
            "candidate_skills": ["Sensitive data protection"],
        }
    )
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(
        client=FakeLlmClient([json.dumps(capability), _valid_json()])
    )

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
    )

    filtered = next(
        event for event in reporter.events if event.kind == "capability_filtered"
    )
    assert filtered.params["capability"] == (
        "sensitive information and security / 敏感信息与安全"
    )
    assert not any(
        event.kind == "capability_discovered" for event in reporter.events
    )


@pytest.mark.asyncio
async def test_planner_allows_sensitive_information_and_security_when_selected() -> None:
    capability = json.loads(_capabilities_json())
    capability["capabilities"][0].update(
        {
            "name": "敏感信息与安全",
            "description": "识别敏感数据并执行安全事件处置。",
            "candidate_skills": ["敏感数据保护"],
        }
    )
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(
        client=FakeLlmClient([json.dumps(capability), _valid_json_zh()])
    )

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
        allowed_system_capabilities=["sensitive_data_security"],
        result_language="zh-CN",
    )

    assert any(
        event.kind == "capability_discovered" for event in reporter.events
    )
    assert not any(event.kind == "capability_filtered" for event in reporter.events)


@pytest.mark.asyncio
async def test_planner_corrects_final_plan_with_forbidden_capability() -> None:
    forbidden_plan = GenerationPlan(
        skills=[
            SkillPlan(
                name="AI Writing",
                description="Generate text with an AI model.",
                system_prompt="Generate text.",
                operation_keys=["GET /projects"],
                value="Automates AI writing.",
            )
        ],
        agents=[
            _agent(skill_name="AI Writing"),
        ],
    ).model_dump_json()
    client = FakeLlmClient(
        [_capabilities_json(), forbidden_plan, _valid_json()]
    )
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
    )

    assert plan.skills[0].name == "Project Insights 0"
    assert "forbidden capability" in client.calls[2][-1].content


@pytest.mark.asyncio
async def test_planner_blocks_security_skill_and_agent_unless_selected() -> None:
    security_plan = GenerationPlan(
        skills=[
            SkillPlan(
                name="Sensitive information protection",
                description="Mask personal data and investigate security incidents.",
                system_prompt="Protect sensitive information.",
                operation_keys=["GET /projects"],
                value="Reduces data security risk.",
            )
        ],
        agents=[
            AgentPlan(
                name="Security response Agent",
                responsibility="Coordinate sensitive-data incident response.",
                system_prompt="Handle security events.",
                skill_names=["Sensitive information protection"],
                mode="human_in_loop",
                max_iterations=8,
                value="Improves security response.",
                use_cases=["Investigate a security incident"],
            )
        ],
    ).model_dump_json()
    client = FakeLlmClient([_capabilities_json(), security_plan, _valid_json()])
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
    )

    assert plan.skills[0].name == "Project Insights 0"
    assert "sensitive_data_security" in client.calls[2][-1].content


@pytest.mark.asyncio
async def test_planner_keeps_security_skill_and_agent_when_selected() -> None:
    security_plan = GenerationPlan(
        skills=[
            SkillPlan(
                name="敏感信息保护",
                description="识别敏感数据并进行数据脱敏。",
                system_prompt="保护敏感信息。",
                operation_keys=["GET /projects"],
                value="降低信息安全风险。",
            )
        ],
        agents=[
            AgentPlan(
                name="安全响应 Agent",
                responsibility="协调安全事件处置。",
                system_prompt="处理安全事件。",
                skill_names=["敏感信息保护"],
                mode="human_in_loop",
                max_iterations=8,
                value="提升安全响应效率。",
                use_cases=["处置安全事件"],
            )
        ],
    ).model_dump_json()
    planner = AutoAgentifyPlanner(
        client=FakeLlmClient([_capabilities_json_zh(), security_plan])
    )

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        allowed_system_capabilities=["sensitive_data_security"],
        result_language="zh-CN",
    )

    assert plan.skills[0].name == "敏感信息保护"
    assert plan.agents[0].name == "安全响应 Agent"


@pytest.mark.asyncio
async def test_planner_falls_back_after_second_invalid_plan_response() -> None:
    client = FakeLlmClient(
        [_capabilities_json(), "not json", "still not json"]
    )
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
        source_name="EDC",
    )

    assert len(plan.skills) == 1
    assert len(plan.agents) == 1
    assert len(client.calls) == 3
    assert any(event.kind == "plan_fallback" for event in reporter.events)


@pytest.mark.asyncio
async def test_large_catalog_uses_batch_summaries_before_synthesis() -> None:
    client = FakeLlmClient(
        [
            _capabilities_json("GET /projects"),
            _capabilities_json("GET /projects/99"),
            _valid_json(),
        ]
    )
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="anthropic",
        base_url="https://llm.example.test",
        api_key="secret",
        model="model",
        catalog=_catalog(151),
    )

    assert len(client.calls) == 3
    assert "capability summaries" in client.calls[-1][-1].content


@pytest.mark.asyncio
async def test_planner_emits_structured_business_capability_and_selection_events() -> None:
    client = FakeLlmClient([_capabilities_json(), _valid_json()])
    reporter = CollectingReporter()
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
    )

    capability = next(
        event for event in reporter.events if event.kind == "capability_discovered"
    )
    assert capability.capability is not None
    assert capability.capability["name"] == "Project lifecycle"
    assert capability.capability["workflow"] == ["Create", "Assign", "Track", "Close"]
    assert any(event.kind == "skill_selected" for event in reporter.events)
    assert any(event.kind == "agent_synthesized" for event in reporter.events)
    assert "secret" not in json.dumps(
        [event.capability for event in reporter.events], ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_planner_prompts_prioritize_core_domain_value_and_bounded_output() -> None:
    client = FakeLlmClient([_capabilities_json(), _valid_json()])
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        source_name="EDC",
        allowed_system_capabilities=["file_management"],
        custom_capability_labels=["clinical trial data capture"],
    )

    capability_prompt = client.calls[0][-1].content
    plan_prompt = client.calls[1][-1].content
    system_prompt = client.calls[0][0].content
    assert "requested result language" in system_prompt
    assert "generic administration" in capability_prompt
    assert "2 to 6" in capability_prompt
    assert 'Source name: "EDC"' in capability_prompt
    assert "file management / 文件管理" in capability_prompt
    assert "system configuration / 系统配置" in capability_prompt
    assert "clinical trial data capture" in capability_prompt
    assert "English (en-US)" in capability_prompt
    assert "system_prompt fields may use whichever language" in plan_prompt
    assert "6 to 12 Skills" in plan_prompt
    assert "2 to 5 Agents" in plan_prompt
    assert client.requests[0]["max_tokens"] == 4_000
    assert client.requests[1]["max_tokens"] == 12_000


@pytest.mark.asyncio
async def test_planner_enforces_user_language_and_normalizes_result_category() -> None:
    chinese_capability = json.loads(_capabilities_json())
    chinese_capability["capabilities"][0].update(
        {
            "name": "项目文件管理",
            "category": "file management / 文件管理",
            "description": "统一管理项目文件并协调相关业务操作。",
            "value": "减少人工整理文件所需的时间。",
            "workflow": ["确认文件范围", "执行文件操作", "汇总处理结果"],
            "candidate_skills": ["项目文件管理"],
        }
    )
    reporter = CollectingReporter()
    client = FakeLlmClient(
        [
            _capabilities_json(),
            json.dumps(chinese_capability, ensure_ascii=False),
            _valid_json(),
            _valid_json_zh(),
        ]
    )
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
        reporter=reporter,
        allowed_system_capabilities=["file_management"],
        result_language="zh-CN",
    )

    discovered = next(
        event for event in reporter.events if event.kind == "capability_discovered"
    )
    assert discovered.capability["category"] == "file_management"
    assert plan.skills[0].name == "项目洞察"
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_planner_retries_one_transient_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("chat4openapi.auto_agentify.planner.asyncio.sleep", no_wait)
    client = FakeLlmClient(
        [
            LlmProviderError(502, {"message": "temporary timeout"}),
            _capabilities_json(),
            _valid_json(),
        ]
    )
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
    )

    assert plan.skills
    assert len(client.calls) == 3
