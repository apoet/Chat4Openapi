from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.db.session import create_engine_for_url
from chatapi.models import (
    AgentConfig,
    ApiSource,
    Conversation,
    LlmProvider,
    Skill,
    Tool,
    ToolParameterOverride,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migration_config(path: Path) -> Config:
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlite_url(path))
    return config


def test_migration_preserves_existing_installation_as_agent_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing.db"
    config = migration_config(database_path)
    command.upgrade(config, "0004_api_source_refresh")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO llm_providers
                    (id, name, provider_type, base_url, encrypted_api_key,
                     default_model, enabled, deleted_at)
                VALUES
                    (0, 'Deleted', 'openai', 'https://deleted.test',
                     X'00', 'deleted-model', 1, '2026-01-01 00:00:00'),
                    (1, 'Disabled', 'openai', 'https://disabled.test',
                     X'01', 'disabled-model', 0, NULL),
                    (2, 'Primary', 'openai', 'https://primary.test',
                     X'02', 'primary-model', 1, NULL),
                    (3, 'Secondary', 'openai', 'https://secondary.test',
                     X'03', 'secondary-model', 1, NULL)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skills (id, name, system_prompt, provider_id, model)
                VALUES (1, 'Existing Skill', 'Use the existing tool.', 3, 'legacy-model')
                """
            )
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with Session(engine) as session:
        provider = session.get(LlmProvider, 2)
        agent = session.get(AgentConfig, 1)
        skill = session.get(Skill, 1)

        assert provider is not None
        assert agent is not None
        assert agent.provider_id == provider.id
        assert agent.mode == "human_in_loop"
        assert agent.max_iterations == 8
        assert skill is not None
        assert not hasattr(skill, "provider_id")
        assert not hasattr(skill, "model")

        conversation = Conversation()
        session.add(conversation)
        session.flush()
        assert conversation.candidate_skill_ids == []
        assert conversation.loaded_skill_ids == []
        assert conversation.agent_status == "running"
        assert conversation.pending_clarification is None
    engine.dispose()


def test_tool_parameter_override_is_unique_and_cascades_with_tool(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "overrides.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine_for_url(sqlite_url(database_path))

    with Session(engine) as session:
        source = ApiSource(
            name="Example API",
            source_type="openapi",
            base_url="https://api.test",
        )
        session.add(source)
        session.flush()
        tool = Tool(
            api_source_id=source.id,
            operation_key="GET /items",
            name="list_items",
            input_schema={"type": "object"},
            execution_schema={"method": "GET", "path": "/items", "parameters": []},
        )
        session.add(tool)
        session.flush()
        override = ToolParameterOverride(
            tool_id=tool.id,
            argument_name="limit",
            description="Maximum items to return",
            example=10,
        )
        session.add(override)
        session.commit()
        tool_id = tool.id
        override_id = override.id

    with Session(engine) as session:
        session.add(ToolParameterOverride(tool_id=tool_id, argument_name="limit"))
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        session.execute(delete(Tool).where(Tool.id == tool_id))
        session.commit()
        assert session.get(ToolParameterOverride, override_id) is None

    engine.dispose()
