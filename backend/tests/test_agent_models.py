from pathlib import Path
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chat4openapi.db.session import create_engine_for_url
from chat4openapi.chat.agent import DEFAULT_AGENT_PROMPT
from chat4openapi.models import (
    Agent,
    ApiSource,
    BrowserChatSession,
    Conversation,
    LlmProvider,
    Skill,
    Tool,
    ToolParameterOverride,
)
from chat4openapi.skills.defaults import (
    VARCARDS2_GENE_LEGACY_SYSTEM_PROMPT,
    VARCARDS2_GENE_SYSTEM_PROMPT,
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
        agent = session.get(Agent, 1)
        skill = session.get(Skill, 1)

        assert provider is not None
        assert agent is not None
        assert agent.provider_id == provider.id
        assert agent.mode == "human_in_loop"
        assert agent.max_iterations == 8
        assert agent.system_prompt == DEFAULT_AGENT_PROMPT
        assert agent.created_at is not None
        assert agent.updated_at is not None
        assert skill is not None
        assert not hasattr(skill, "provider_id")
        assert not hasattr(skill, "model")

        browser_session = BrowserChatSession(
            token_hash="agent-model-test-token",
            public_subject_id="agent-model-test-subject",
            expires_at=datetime(2099, 1, 1),
        )
        session.add(browser_session)
        session.flush()
        conversation = Conversation(
            agent_id=agent.id, browser_chat_session_id=browser_session.id
        )
        session.add(conversation)
        session.flush()
        assert conversation.candidate_skill_ids == []
        assert conversation.loaded_skill_ids == []
        assert conversation.agent_status == "running"
        assert conversation.pending_clarification is None
        assert conversation.candidate_scope_source == "automatic"
        assert conversation.latest_failure_summary is None
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


def test_markdown_prompt_migration_updates_the_varcards_legacy_default(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "varcards-default.db"
    config = migration_config(database_path)
    command.upgrade(config, "0005_agent_runtime")
    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO skills (name, description, system_prompt, running)
                VALUES ('Varcards2-Gene', 'Gene lookup', :prompt, true)
                """
            ),
            {"prompt": VARCARDS2_GENE_LEGACY_SYSTEM_PROMPT},
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        prompt = connection.execute(
            text("SELECT system_prompt FROM skills WHERE name = 'Varcards2-Gene'")
        ).scalar_one()
    engine.dispose()
    assert prompt == VARCARDS2_GENE_SYSTEM_PROMPT


def test_markdown_prompt_migration_preserves_a_customized_varcards_prompt(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "varcards-custom.db"
    config = migration_config(database_path)
    command.upgrade(config, "0005_agent_runtime")
    custom_prompt = "Use my organization's reviewed gene response format."
    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO skills (name, description, system_prompt, running)
                VALUES ('Varcards2-Gene', 'Gene lookup', :prompt, true)
                """
            ),
            {"prompt": custom_prompt},
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        prompt = connection.execute(
            text("SELECT system_prompt FROM skills WHERE name = 'Varcards2-Gene'")
        ).scalar_one()
    engine.dispose()
    assert prompt == custom_prompt


@pytest.mark.parametrize(
    "legacy_prompt",
    [
        "",
        (
            "You are Chat4Openapi Agent, the built-in assistant. Use the available Skills "
            "and Tools to help the user, and return clear Markdown responses."
        ),
    ],
)
def test_0007_upgrades_only_known_legacy_agent_prompts(tmp_path: Path, legacy_prompt: str) -> None:
    database_path = tmp_path / f"legacy-{len(legacy_prompt)}.db"
    config = migration_config(database_path)
    command.upgrade(config, "0006_varcards_markdown_prompt")
    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE agent_config SET system_prompt = :prompt WHERE id = 1"),
            {"prompt": legacy_prompt},
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        prompt = connection.execute(
            text("SELECT system_prompt FROM agents WHERE id = 1")
        ).scalar_one()
    engine.dispose()
    assert prompt == DEFAULT_AGENT_PROMPT


def test_0007_preserves_custom_agent_prompt(tmp_path: Path) -> None:
    database_path = tmp_path / "custom-agent.db"
    config = migration_config(database_path)
    command.upgrade(config, "0006_varcards_markdown_prompt")
    custom_prompt = "Use our reviewed internal operating policy."
    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE agent_config SET system_prompt = :prompt WHERE id = 1"),
            {"prompt": custom_prompt},
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        prompt = connection.execute(
            text("SELECT system_prompt FROM agents WHERE id = 1")
        ).scalar_one()
    engine.dispose()
    assert prompt == custom_prompt
