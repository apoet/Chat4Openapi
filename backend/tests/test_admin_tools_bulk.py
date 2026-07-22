from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api import admin_skills, admin_tools
from chat4openapi.api.admin_auth import AdminContext
from chat4openapi.api.errors import ApiError
from chat4openapi.models import (
    ApiSource,
    GlobalToolAuthConfig,
    Skill,
    SkillTool,
    Tool,
)
from chat4openapi.schemas.tools import ApiSourceEnabledRequest, ToolAuthConfigRequest

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def context(session: Session) -> AdminContext:
    return AdminContext(admin=None, admin_session=None, db=session)  # type: ignore[arg-type]


def make_tool(source_id: int, name: str, enabled: bool) -> Tool:
    return Tool(
        api_source_id=source_id,
        operation_key=f"GET /{name}",
        name=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
        execution_schema={"method": "GET", "path": f"/{name}", "parameters": []},
        enabled=enabled,
    )


def seed_tools(factory: sessionmaker[Session]) -> dict[str, int]:
    with factory() as session:
        active_source = ApiSource(
            name="Active API",
            source_type="openapi",
            base_url="https://active.test",
            spec_snapshot="{}",
        )
        disabled_source = ApiSource(
            name="Disabled API",
            source_type="openapi",
            base_url="https://disabled.test",
            spec_snapshot="{}",
            enabled=False,
        )
        deleted_source = ApiSource(
            name="Deleted API",
            source_type="openapi",
            base_url="https://deleted.test",
            spec_snapshot="{}",
            enabled=False,
            deleted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add_all([active_source, disabled_source, deleted_source])
        session.flush()
        enabled = make_tool(active_source.id, "enabled", True)
        disabled = make_tool(active_source.id, "disabled", False)
        later = make_tool(active_source.id, "later", True)
        login_tool = make_tool(active_source.id, "login", True)
        disabled_source_tool = make_tool(disabled_source.id, "disabled-source", False)
        deleted_source_tool = make_tool(deleted_source.id, "deleted-source", False)
        session.add_all(
            [
                enabled,
                disabled,
                later,
                login_tool,
                disabled_source_tool,
                deleted_source_tool,
            ]
        )
        session.flush()
        session.add(
            GlobalToolAuthConfig(
                id=1,
                enabled=True,
                login_tool_id=login_tool.id,
                token_json_path="$.token",
            )
        )
        session.commit()
        return {
            "source": active_source.id,
            "enabled": enabled.id,
            "disabled": disabled.id,
            "later": later.id,
            "login": login_tool.id,
            "disabled_source": disabled_source.id,
            "disabled_source_tool": disabled_source_tool.id,
            "deleted_source": deleted_source.id,
            "deleted_source_tool": deleted_source_tool.id,
        }


@pytest.mark.asyncio
async def test_bulk_tools_requires_admin_and_csrf(client: httpx.AsyncClient) -> None:
    unauthenticated = await client.post(
        "/api/admin/tools/batch",
        json={"action": "disable", "tool_ids": [1]},
    )
    csrf = await login(client)
    missing_csrf = await client.post(
        "/api/admin/tools/batch",
        json={"action": "disable", "tool_ids": [1]},
    )
    authorized = await client.post(
        "/api/admin/tools/batch",
        json={"action": "disable", "tool_ids": [1]},
        headers={"X-CSRF-Token": csrf},
    )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert authorized.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"action": "archive", "tool_ids": [1]},
        {"action": "enable", "tool_ids": []},
        {"action": "enable", "tool_ids": [0]},
        {"action": "enable", "tool_ids": [-1]},
        {"action": "enable", "tool_ids": [True]},
        {"action": "enable", "tool_ids": ["1"]},
        {"action": "enable", "tool_ids": [1.0]},
    ],
)
async def test_bulk_tools_rejects_invalid_input(
    client: httpx.AsyncClient,
    payload: dict,
) -> None:
    csrf = await login(client)

    response = await client.post(
        "/api/admin/tools/batch",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"


@pytest.mark.asyncio
async def test_bulk_tools_rejects_the_201st_unique_id(client: httpx.AsyncClient) -> None:
    csrf = await login(client)

    response = await client.post(
        "/api/admin/tools/batch",
        json={"action": "enable", "tool_ids": list(range(1, 202))},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "tools.batch_limit_exceeded", "params": {"limit": 200}}
    }


@pytest.mark.asyncio
async def test_bulk_disable_deduplicates_stably_and_is_partial_and_idempotent(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    ids = seed_tools(db_session_factory)
    missing_first = 900_001
    missing_second = 900_002
    payload = {
        "action": "disable",
        "tool_ids": [
            ids["enabled"],
            missing_first,
            ids["disabled"],
            ids["enabled"],
            missing_second,
        ],
    }

    response = await client.post(
        "/api/admin/tools/batch",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    repeated = await client.post(
        "/api/admin/tools/batch",
        json={"action": "disable", "tool_ids": [ids["enabled"], ids["disabled"]]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_count": 4,
        "succeeded": [
            {"tool_id": ids["enabled"], "action": "disable", "status": "disabled"},
            {"tool_id": ids["disabled"], "action": "disable", "status": "disabled"},
        ],
        "failed": [
            {
                "tool_id": missing_first,
                "action": "disable",
                "code": "tools.not_found",
                "params": {},
            },
            {
                "tool_id": missing_second,
                "action": "disable",
                "code": "tools.not_found",
                "params": {},
            },
        ],
    }
    assert [item["status"] for item in repeated.json()["succeeded"]] == [
        "disabled",
        "disabled",
    ]


@pytest.mark.asyncio
async def test_bulk_enable_and_single_enable_share_source_constraints(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    ids = seed_tools(db_session_factory)

    response = await client.post(
        "/api/admin/tools/batch",
        json={
            "action": "enable",
            "tool_ids": [
                ids["disabled_source_tool"],
                ids["deleted_source_tool"],
                ids["disabled"],
            ],
        },
        headers={"X-CSRF-Token": csrf},
    )
    single = await client.patch(
        f"/api/admin/tools/{ids['disabled_source_tool']}/enabled",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )

    assert [item["tool_id"] for item in response.json()["succeeded"]] == [ids["disabled"]]
    assert response.json()["failed"] == [
        {
            "tool_id": ids["disabled_source_tool"],
            "action": "enable",
            "code": "tools.source_unavailable",
            "params": {"source_id": ids["disabled_source"]},
        },
        {
            "tool_id": ids["deleted_source_tool"],
            "action": "enable",
            "code": "tools.source_unavailable",
            "params": {"source_id": ids["deleted_source"]},
        },
    ]
    assert single.status_code == 409
    assert single.json()["error"] == {
        "code": "tools.source_unavailable",
        "params": {"source_id": ids["disabled_source"]},
    }


@pytest.mark.asyncio
async def test_bulk_login_conflict_rolls_back_only_that_item_and_continues(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    ids = seed_tools(db_session_factory)

    response = await client.post(
        "/api/admin/tools/batch",
        json={
            "action": "disable",
            "tool_ids": [ids["enabled"], ids["login"], ids["later"]],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert [item["tool_id"] for item in response.json()["succeeded"]] == [
        ids["enabled"],
        ids["later"],
    ]
    assert response.json()["failed"] == [
        {
            "tool_id": ids["login"],
            "action": "disable",
            "code": "tools.login_tool_conflict",
            "params": {},
        }
    ]
    with db_session_factory() as session:
        assert session.get(Tool, ids["enabled"]).enabled is False
        assert session.get(Tool, ids["login"]).enabled is True
        assert session.get(Tool, ids["later"]).enabled is False


@pytest.mark.asyncio
async def test_bulk_disable_and_delete_stop_bound_skills_and_soft_delete(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    csrf = await login(client)
    ids = seed_tools(db_session_factory)
    with db_session_factory() as session:
        disable_skill = Skill(name="Disable skill", system_prompt="Disable", running=True)
        delete_skill = Skill(name="Delete skill", system_prompt="Delete", running=True)
        session.add_all([disable_skill, delete_skill])
        session.flush()
        session.add_all(
            [
                SkillTool(skill_id=disable_skill.id, tool_id=ids["enabled"], position=0),
                SkillTool(skill_id=delete_skill.id, tool_id=ids["later"], position=0),
            ]
        )
        session.commit()
        disable_skill_id = disable_skill.id
        delete_skill_id = delete_skill.id

    disabled = await client.post(
        "/api/admin/tools/batch",
        json={"action": "disable", "tool_ids": [ids["enabled"]]},
        headers={"X-CSRF-Token": csrf},
    )
    deleted = await client.post(
        "/api/admin/tools/batch",
        json={"action": "delete", "tool_ids": [ids["later"], ids["later"]]},
        headers={"X-CSRF-Token": csrf},
    )
    already_deleted = await client.post(
        "/api/admin/tools/batch",
        json={"action": "enable", "tool_ids": [ids["later"]]},
        headers={"X-CSRF-Token": csrf},
    )

    assert disabled.json()["succeeded"][0]["status"] == "disabled"
    assert deleted.json()["request_count"] == 1
    assert deleted.json()["succeeded"] == [
        {"tool_id": ids["later"], "action": "delete", "status": "deleted"}
    ]
    assert already_deleted.json()["failed"] == [
        {
            "tool_id": ids["later"],
            "action": "enable",
            "code": "tools.not_found",
            "params": {},
        }
    ]
    with db_session_factory() as session:
        assert session.get(Skill, disable_skill_id).running is False
        assert session.get(Skill, delete_skill_id).running is False
        deleted_tool = session.get(Tool, ids["later"])
        assert deleted_tool.enabled is False
        assert deleted_tool.deleted_at is not None


@pytest.mark.asyncio
async def test_unexpected_item_failure_is_sanitized_and_does_not_poison_later_items(
    client: httpx.AsyncClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = await login(client)
    ids = seed_tools(db_session_factory)
    original = getattr(admin_tools, "apply_tool_action", None)

    def fail_after_flush(db: Session, tool_id: int, action: str):
        if tool_id == ids["disabled"]:
            db.get(Tool, tool_id).enabled = True
            db.flush()
            raise RuntimeError("secret database detail")
        assert original is not None
        return original(db, tool_id, action)

    monkeypatch.setattr(admin_tools, "apply_tool_action", fail_after_flush, raising=False)
    response = await client.post(
        "/api/admin/tools/batch",
        json={
            "action": "disable",
            "tool_ids": [ids["enabled"], ids["disabled"], ids["later"]],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert [item["tool_id"] for item in response.json()["succeeded"]] == [
        ids["enabled"],
        ids["later"],
    ]
    assert response.json()["failed"] == [
        {
            "tool_id": ids["disabled"],
            "action": "disable",
            "code": "tools.batch_item_failed",
            "params": {},
        }
    ]
    assert "secret database detail" not in response.text
    with db_session_factory() as session:
        assert session.get(Tool, ids["enabled"]).enabled is False
        assert session.get(Tool, ids["disabled"]).enabled is False
        assert session.get(Tool, ids["later"]).enabled is False


def test_bulk_commit_failure_rolls_back_the_whole_batch(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_tools(db_session_factory)
    assert hasattr(admin_tools, "batch_tools")

    with db_session_factory() as session:
        def fail_commit() -> None:
            session.flush()
            raise RuntimeError("commit failed")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit failed"):
            admin_tools.batch_tools(
                SimpleNamespace(
                    action="disable",
                    tool_ids=[ids["enabled"], ids["later"]],
                ),
                context(session),
            )

    with db_session_factory() as session:
        assert session.get(Tool, ids["enabled"]).enabled is True
        assert session.get(Tool, ids["later"]).enabled is True


def test_source_disable_serializes_before_a_competing_bulk_enable(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_tools(db_session_factory)
    assert hasattr(admin_tools, "batch_tools")
    with db_session_factory() as session:
        session.get(GlobalToolAuthConfig, 1).enabled = False
        session.commit()
    source_locked = Event()
    release_source = Event()
    batch_started = Event()
    original_source_tool_ids = admin_tools._source_tool_ids

    def pause_source(context_value: AdminContext, source_id: int) -> list[int]:
        result = original_source_tool_ids(context_value, source_id)
        source_locked.set()
        assert release_source.wait(5)
        return result

    monkeypatch.setattr(admin_tools, "_source_tool_ids", pause_source)

    def disable_source() -> None:
        with db_session_factory() as session:
            admin_tools.set_source_enabled(
                ids["source"],
                ApiSourceEnabledRequest(enabled=False),
                context(session),
            )

    def enable_tool() -> dict:
        with db_session_factory() as session:
            batch_started.set()
            result = admin_tools.batch_tools(
                SimpleNamespace(action="enable", tool_ids=[ids["disabled"]]),
                context(session),
            )
            return result.model_dump()

    with ThreadPoolExecutor(max_workers=2) as executor:
        source_result = executor.submit(disable_source)
        assert source_locked.wait(5)
        batch_result = executor.submit(enable_tool)
        assert batch_started.wait(5)
        release_source.set()
        source_result.result(timeout=5)
        result = batch_result.result(timeout=5)

    assert result["succeeded"] == []
    assert result["failed"][0]["code"] == "tools.source_unavailable"
    with db_session_factory() as session:
        assert session.get(ApiSource, ids["source"]).enabled is False
        assert session.get(Tool, ids["disabled"]).enabled is False


@pytest.mark.parametrize("action", ["disable", "delete"])
def test_set_tool_auth_revalidates_after_queued_batch_mutation(
    db_session_factory: sessionmaker[Session],
    action: str,
) -> None:
    ids = seed_tools(db_session_factory)
    target_id = ids["enabled"]
    auth_ready = Event()
    batch_committed = Event()

    def configure_auth() -> str | None:
        with db_session_factory() as session:
            tool = session.get(Tool, target_id)
            session.get(ApiSource, tool.api_source_id)
            session.get(GlobalToolAuthConfig, 1)
            session.commit()
            auth_ready.set()
            assert batch_committed.wait(5)
            try:
                admin_tools.set_tool_auth(
                    ToolAuthConfigRequest(
                        enabled=True,
                        login_tool_id=target_id,
                        token_json_path="$.token",
                    ),
                    context(session),
                )
            except ApiError as exc:
                return exc.code
            return None

    def mutate_tool() -> None:
        with db_session_factory() as session:
            admin_tools.batch_tools(
                SimpleNamespace(action=action, tool_ids=[target_id]),
                context(session),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        auth_result = executor.submit(configure_auth)
        assert auth_ready.wait(5)
        batch_result = executor.submit(mutate_tool)
        batch_result.result(timeout=5)
        batch_committed.set()
        auth_error = auth_result.result(timeout=5)

    assert auth_error in {"tools.login_tool_disabled", "tools.not_found"}
    with db_session_factory() as session:
        config = session.get(GlobalToolAuthConfig, 1)
        target = session.get(Tool, target_id)
        assert not (config.enabled and config.login_tool_id == target_id)
        assert target.enabled is False
        if action == "delete":
            assert target.deleted_at is not None


@pytest.mark.parametrize("action", ["disable", "delete"])
def test_start_skill_revalidates_after_queued_batch_mutation(
    db_session_factory: sessionmaker[Session],
    action: str,
) -> None:
    ids = seed_tools(db_session_factory)
    target_id = ids["enabled"]
    with db_session_factory() as session:
        skill = Skill(name=f"Queued {action}", system_prompt="Queued", running=False)
        session.add(skill)
        session.flush()
        session.add(SkillTool(skill_id=skill.id, tool_id=target_id, position=0))
        session.commit()
        skill_id = skill.id
    skill_ready = Event()
    batch_committed = Event()

    def start_bound_skill() -> str | None:
        with db_session_factory() as session:
            cached_skill = session.get(Skill, skill_id)
            cached_tool = session.get(Tool, target_id)
            cached_source = session.get(ApiSource, ids["source"])
            assert cached_skill is not None
            assert cached_tool is not None
            assert cached_source is not None
            session.commit()
            skill_ready.set()
            assert batch_committed.wait(5)
            try:
                admin_skills.start_skill(skill_id, context(session))
            except ApiError as exc:
                return exc.code
            return None

    def mutate_tool() -> None:
        with db_session_factory() as session:
            admin_tools.batch_tools(
                SimpleNamespace(action=action, tool_ids=[target_id]),
                context(session),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        skill_result = executor.submit(start_bound_skill)
        assert skill_ready.wait(5)
        batch_result = executor.submit(mutate_tool)
        batch_result.result(timeout=5)
        batch_committed.set()
        skill_error = skill_result.result(timeout=5)

    assert skill_error == "skills.tool_unavailable"
    with db_session_factory() as session:
        skill = session.get(Skill, skill_id)
        target = session.get(Tool, target_id)
        assert skill.running is False
        assert target.enabled is False
        if action == "delete":
            assert target.deleted_at is not None
