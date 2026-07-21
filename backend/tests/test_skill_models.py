from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.db.session import create_engine_for_url
from chatapi.models import LlmProvider, Skill, SkillTool, Tool


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migrated_engine(tmp_path: Path):
    url = sqlite_url(tmp_path / "skills.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return config, create_engine_for_url(url)


def test_skills_migration_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    config, engine = migrated_engine(tmp_path)
    expected = {"llm_providers", "skills", "skill_tools", "conversations", "chat_messages"}
    inspector = inspect(engine)

    assert expected <= set(inspector.get_table_names())
    provider_columns = {column["name"] for column in inspector.get_columns("llm_providers")}
    assert "encrypted_api_key" in provider_columns
    assert "api_key" not in provider_columns
    skill_foreign_keys = inspector.get_foreign_keys("skills")
    assert any(key["referred_table"] == "llm_providers" for key in skill_foreign_keys)
    message_foreign_keys = inspector.get_foreign_keys("chat_messages")
    assert any(
        key["referred_table"] == "conversations"
        and key["options"].get("ondelete") == "CASCADE"
        for key in message_foreign_keys
    )

    engine.dispose()
    command.downgrade(config, "0002_tool_runtime")
    downgraded = create_engine_for_url(config.get_main_option("sqlalchemy.url"))
    assert expected.isdisjoint(inspect(downgraded).get_table_names())
    downgraded.dispose()
    command.upgrade(config, "head")
    upgraded = create_engine_for_url(config.get_main_option("sqlalchemy.url"))
    assert expected <= set(inspect(upgraded).get_table_names())
    upgraded.dispose()


def test_skill_tool_and_position_are_unique_within_skill(
    tmp_path: Path,
) -> None:
    _, engine = migrated_engine(tmp_path)
    with Session(engine) as session:
        provider = LlmProvider(
            name="Primary",
            provider_type="openai",
            base_url="https://llm.test/v1",
            encrypted_api_key=b"encrypted",
            default_model="test-model",
        )
        session.add(provider)
        session.flush()
        skill = Skill(name="Pet helper", system_prompt="Help", provider_id=provider.id)
        source_id = _create_source(session)
        first = _create_tool(session, source_id, "first", "GET /first")
        second = _create_tool(session, source_id, "second", "GET /second")
        session.add(skill)
        session.flush()
        session.add_all(
            [
                SkillTool(skill_id=skill.id, tool_id=first.id, position=0),
                SkillTool(skill_id=skill.id, tool_id=second.id, position=0),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def _create_source(session: Session) -> int:
    from chatapi.models import ApiSource

    source = ApiSource(name="API", source_type="openapi", base_url="https://api.test")
    session.add(source)
    session.flush()
    return source.id


def _create_tool(session: Session, source_id: int, name: str, operation: str) -> Tool:
    tool = Tool(
        api_source_id=source_id,
        operation_key=operation,
        name=name,
        input_schema={"type": "object"},
        execution_schema={"method": "GET", "path": "/", "parameters": []},
        enabled=True,
    )
    session.add(tool)
    session.flush()
    return tool
