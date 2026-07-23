from datetime import UTC, datetime
import json
import logging
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api.admin_auto_agentify import get_auto_agentify_planner
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.auto_agentify.planner import PlanGenerationError
from chat4openapi.models import (
    Agent,
    AgentSkill,
    ApiSource,
    LlmProvider,
    Skill,
    SkillTool,
    Tool,
)
from chat4openapi.schemas.auto_agentify import AgentPlan, GenerationPlan, SkillPlan
from chat4openapi.security.encryption import SecretCipher

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}
OPENAPI = (Path(__file__).parent / "fixtures" / "openapi3.yaml").read_bytes()


async def login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def seed_provider(
    factory: sessionmaker[Session],
    cipher: SecretCipher,
    *,
    enabled: bool = True,
) -> int:
    with factory() as session:
        provider = LlmProvider(
            name="Analysis Provider",
            provider_type="openai",
            base_url="https://llm.example.test/v1",
            encrypted_api_key=cipher.encrypt_json({"api_key": "provider-secret"}),
            default_model="gpt-test",
            enabled=enabled,
        )
        session.add(provider)
        session.commit()
        return provider.id


class SuccessfulPlanner:
    calls: list[dict]

    def __init__(self) -> None:
        self.calls = []

    async def plan(self, **kwargs) -> GenerationPlan:
        self.calls.append(kwargs)
        return GenerationPlan(
            skills=[
                SkillPlan(
                    name="Pet Operations",
                    description="Creates pets through the API.",
                    system_prompt="Use the pet creation Tool when the user requests it.",
                    operation_keys=["POST /pets"],
                    value="Automates pet onboarding.",
                )
            ],
            agents=[
                AgentPlan(
                    name="Pet Operator",
                    responsibility="Coordinates pet onboarding.",
                    system_prompt="Use Pet Operations to complete onboarding requests.",
                    skill_names=["Pet Operations"],
                    mode="human_in_loop",
                    max_iterations=8,
                    value="Turns the API into an onboarding workflow.",
                    use_cases=["Create a pet record"],
                )
            ],
        )


class FailingPlanner:
    async def plan(self, **_kwargs) -> GenerationPlan:
        raise PlanGenerationError("model returned invalid generation plan")


@pytest.mark.asyncio
async def test_file_generation_creates_immediately_usable_configuration(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    planner = SuccessfulPlanner()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: planner

    response = await client.post(
        "/api/admin/auto-agentify/file",
        data={
            "provider_id": str(provider_id),
            "name": "Pets",
            "base_url": "https://api.example.test/v1",
            "allow_private_networks": "false",
        },
        files={"document": ("openapi.yaml", OPENAPI, "application/yaml")},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"]["name"] == "Pets"
    assert body["imported_tool_count"] == 1
    assert body["enabled_tool_count"] == 1
    assert body["skills"][0]["value"] == "Automates pet onboarding."
    assert body["agents"][0]["value"] == "Turns the API into an onboarding workflow."
    assert body["agents"][0]["use_cases"] == ["Create a pet record"]
    assert planner.calls[0]["api_key"] == "provider-secret"

    with db_session_factory() as session:
        tool = session.scalar(select(Tool))
        skill = session.scalar(select(Skill))
        agent = session.scalar(select(Agent))
        assert tool is not None and tool.enabled is True
        assert skill is not None and skill.running is True
        assert agent is not None and agent.enabled is True
        assert agent.provider_id == provider_id
        assert agent.model is None
        assert session.scalar(select(func.count()).select_from(SkillTool)) == 1
        assert session.scalar(select(func.count()).select_from(AgentSkill)) == 1


@pytest.mark.asyncio
async def test_planning_failure_leaves_no_generated_rows(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: FailingPlanner()

    response = await client.post(
        "/api/admin/auto-agentify/file",
        data={"provider_id": str(provider_id), "name": "Pets"},
        files={"document": ("openapi.yaml", OPENAPI, "application/yaml")},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "auto_agentify.plan_invalid"
    with db_session_factory() as session:
        for model in (ApiSource, Tool, Skill, Agent):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_generation_rejects_unavailable_provider_and_requires_csrf(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher, enabled=False)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: SuccessfulPlanner()
    request = {
        "provider_id": str(provider_id),
        "name": "Pets",
    }
    files = {"document": ("openapi.yaml", OPENAPI, "application/yaml")}

    unavailable = await client.post(
        "/api/admin/auto-agentify/file",
        data=request,
        files=files,
        headers={"X-CSRF-Token": token},
    )
    missing_csrf = await client.post(
        "/api/admin/auto-agentify/file",
        data=request,
        files=files,
    )

    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "auto_agentify.provider_unavailable"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "auth.csrf_invalid"


@pytest.mark.asyncio
async def test_generation_allocates_a_new_name_when_soft_deleted_skill_owns_name(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    with db_session_factory() as session:
        session.add(
            Skill(
                name="Pet Operations",
                description="Old configuration",
                system_prompt="Do not use.",
                running=False,
                deleted_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.commit()
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: SuccessfulPlanner()

    response = await client.post(
        "/api/admin/auto-agentify/file",
        data={"provider_id": str(provider_id), "name": "Pets"},
        files={"document": ("openapi.yaml", OPENAPI, "application/yaml")},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 201
    assert response.json()["skills"][0]["name"] == "Pet Operations (Pets)"


@pytest.mark.asyncio
async def test_generation_logs_only_bounded_operational_metadata(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: SuccessfulPlanner()
    service_logger = logging.getLogger("chat4openapi.auto_agentify.service")
    service_logger.disabled = False
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    caplog.set_level(logging.INFO, logger="chat4openapi.auto_agentify.service")

    try:
        response = await client.post(
            "/api/admin/auto-agentify/file",
            data={"provider_id": str(provider_id), "name": "Pets"},
            files={"document": ("openapi.yaml", OPENAPI, "application/yaml")},
            headers={"X-CSRF-Token": token},
        )
    finally:
        logging.disable(previous_disable)

    assert response.status_code == 201
    assert "auto_agentify.completed" in caplog.text
    assert f"provider_id={provider_id}" in caplog.text
    assert "operations=1 skills=1 agents=1" in caplog.text
    assert "provider-secret" not in caplog.text
    assert "openapi: 3.0.3" not in caplog.text


@pytest.mark.asyncio
async def test_url_generation_records_url_and_enables_only_referenced_tools(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    spec = yaml.safe_load(OPENAPI)
    spec["paths"]["/pets"]["get"] = {
        "operationId": "listPets",
        "summary": "List pets",
        "responses": {"200": {"description": "Pet list"}},
    }
    document = json.dumps(spec).encode()

    async def fetch_document(url: str, allow_private_networks: bool) -> bytes:
        assert url == "https://api.example.test/openapi.json"
        assert allow_private_networks is False
        return document

    monkeypatch.setattr(
        "chat4openapi.api.admin_auto_agentify._fetch_openapi_document",
        fetch_document,
    )
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: SuccessfulPlanner()

    response = await client.post(
        "/api/admin/auto-agentify/url",
        json={
            "provider_id": provider_id,
            "name": "Pets",
            "url": "https://api.example.test/openapi.json",
            "base_url": None,
            "allow_private_networks": False,
        },
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 201
    assert response.json()["source"]["document_url"] == (
        "https://api.example.test/openapi.json"
    )
    assert response.json()["imported_tool_count"] == 2
    assert response.json()["enabled_tool_count"] == 1
    with db_session_factory() as session:
        states = {
            tool.operation_key: tool.enabled
            for tool in session.scalars(select(Tool).order_by(Tool.operation_key))
        }
        assert states == {"GET /pets": False, "POST /pets": True}


@pytest.mark.asyncio
async def test_persistence_failure_rolls_back_source_tools_skills_and_agents(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = seed_provider(db_session_factory, cipher)
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: SuccessfulPlanner()

    def fail_binding(**_kwargs):
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(
        "chat4openapi.auto_agentify.service.SkillTool",
        fail_binding,
    )
    with pytest.raises(RuntimeError, match="forced persistence failure"):
        await client.post(
            "/api/admin/auto-agentify/file",
            data={"provider_id": str(provider_id), "name": "Pets"},
            files={"document": ("openapi.yaml", OPENAPI, "application/yaml")},
            headers={"X-CSRF-Token": token},
        )

    with db_session_factory() as session:
        for model in (ApiSource, Tool, Skill, Agent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
