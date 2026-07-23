import json

import pytest
from pydantic import ValidationError

from chat4openapi.auto_agentify.catalog import OperationCatalogItem
from chat4openapi.auto_agentify.planner import (
    AutoAgentifyPlanner,
    PlanGenerationError,
)
from chat4openapi.llm.client import CanonicalResponse
from chat4openapi.schemas.auto_agentify import AgentPlan, GenerationPlan, SkillPlan


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


class FakeLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list] = []

    async def complete(self, **kwargs) -> CanonicalResponse:
        self.calls.append(kwargs["messages"])
        return CanonicalResponse(content=self.responses.pop(0))


def test_generation_plan_enforces_limits_and_references() -> None:
    with pytest.raises(ValidationError):
        GenerationPlan(
            skills=[_skill(index, f"GET /projects/{index}") for index in range(21)],
            agents=[_agent()],
        )

    plan = GenerationPlan(skills=[_skill(operation_key="GET /missing")], agents=[_agent()])
    with pytest.raises(ValueError, match="unknown operation"):
        plan.validate_references({"GET /projects"})


@pytest.mark.asyncio
async def test_planner_corrects_one_invalid_response() -> None:
    client = FakeLlmClient(['{"skills":[],"agents":[]}', _valid_json()])
    planner = AutoAgentifyPlanner(client=client)

    plan = await planner.plan(
        provider_type="openai",
        base_url="https://llm.example.test/v1",
        api_key="secret",
        model="model",
        catalog=_catalog(),
    )

    assert len(client.calls) == 2
    assert plan.skills[0].operation_keys == ["GET /projects"]
    assert "validation errors" in client.calls[1][-1].content


@pytest.mark.asyncio
async def test_planner_rejects_second_invalid_response() -> None:
    client = FakeLlmClient(["not json", "still not json"])
    planner = AutoAgentifyPlanner(client=client)

    with pytest.raises(PlanGenerationError, match="invalid"):
        await planner.plan(
            provider_type="openai",
            base_url="https://llm.example.test/v1",
            api_key="secret",
            model="model",
            catalog=_catalog(),
        )

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_large_catalog_uses_batch_summaries_before_synthesis() -> None:
    summary = json.dumps({"capabilities": [{"name": "Projects", "operation_keys": ["GET /projects"]}]})
    client = FakeLlmClient([summary, summary, _valid_json()])
    planner = AutoAgentifyPlanner(client=client)

    await planner.plan(
        provider_type="anthropic",
        base_url="https://llm.example.test",
        api_key="secret",
        model="model",
        catalog=_catalog(201),
    )

    assert len(client.calls) == 3
    assert "capability summaries" in client.calls[-1][-1].content
