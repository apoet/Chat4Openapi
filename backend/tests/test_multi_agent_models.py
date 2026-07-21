from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from chat4openapi.db.session import create_engine_for_url
from chat4openapi.models import Agent, AgentApiKey, AgentSkill, Conversation, Skill


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migration_config(path: Path) -> Config:
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlite_url(path))
    return config


def test_existing_singleton_becomes_default_agent(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-singleton.db"
    config = migration_config(database_path)
    command.upgrade(config, "0007_agent_runtime_hardening")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO llm_providers
                    (id, name, provider_type, base_url, encrypted_api_key,
                     default_model, enabled)
                VALUES
                    (9, 'Preserved', 'openai', 'https://provider.test',
                     X'09', 'provider-model', true)
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE agent_config
                SET name = 'Customized Agent',
                    enabled = false,
                    system_prompt = 'Preserve this prompt',
                    provider_id = 9,
                    model = 'custom-model',
                    mode = 'react',
                    max_iterations = 17,
                    created_at = '2026-01-02 03:04:05',
                    updated_at = '2026-06-07 08:09:10'
                WHERE id = 1
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skills
                    (id, name, system_prompt, running, deleted_at)
                VALUES
                    (20, 'Second', 'Second prompt', true, NULL),
                    (10, 'First', 'First prompt', true, NULL),
                    (30, 'Deleted', 'Deleted prompt', false, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO conversations
                    (id, skill_id, candidate_skill_ids, loaded_skill_ids,
                     agent_status, candidate_scope_source)
                VALUES
                    ('active', 10, '[10]', '[10]', 'running', 'explicit'),
                    ('deleted', NULL, '[]', '[]', 'failed', 'automatic')
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE conversations
                SET deleted_at = CURRENT_TIMESTAMP,
                    latest_failure_summary = 'preserve me'
                WHERE id = 'deleted'
                """
            )
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        agents = connection.execute(
            text(
                """
                SELECT id, name, enabled, is_default, system_prompt, provider_id,
                       model, mode, max_iterations, created_at, updated_at
                FROM agents ORDER BY id
                """
            )
        ).all()
        conversation_agents = connection.execute(
            text("SELECT id, agent_id FROM conversations ORDER BY id")
        ).all()
        bindings = connection.execute(
            text("SELECT skill_id, position FROM agent_skills WHERE agent_id = 1 ORDER BY position")
        ).all()
        preserved_failure = connection.execute(
            text(
                """
                SELECT agent_status, latest_failure_summary, deleted_at IS NOT NULL
                FROM conversations WHERE id = 'deleted'
                """
            )
        ).one()

    engine.dispose()
    assert agents == [
        (
            1,
            "Customized Agent",
            0,
            1,
            "Preserve this prompt",
            9,
            "custom-model",
            "react",
            17,
            "2026-01-02 03:04:05",
            "2026-06-07 08:09:10",
        )
    ]
    assert conversation_agents == [("active", 1), ("deleted", 1)]
    assert bindings == [(10, 0), (20, 1)]
    assert preserved_failure == ("failed", "preserve me", 1)


def test_persisted_conversation_agent_is_immutable(tmp_path: Path) -> None:
    database_path = tmp_path / "immutable-conversation-agent.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine_for_url(sqlite_url(database_path))

    with Session(engine) as session:
        second = Agent(
            name="Second Agent",
            system_prompt="Use the second policy.",
            provider_id=None,
        )
        session.add(second)
        session.flush()
        conversation = Conversation(agent_id=1)
        session.add(conversation)
        session.commit()

        try:
            conversation.agent_id = second.id
        except ValueError as exc:
            assert str(exc) == "conversation agent cannot be changed"
        else:
            raise AssertionError("persisted conversation accepted a different Agent")

    engine.dispose()


def test_0008_downgrade_and_reupgrade_preserves_default_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "multi-agent-round-trip.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE agents
                SET name = 'Reviewed Agent',
                    system_prompt = 'Reviewed prompt',
                    model = 'reviewed-model',
                    mode = 'react',
                    max_iterations = 12
                WHERE id = 1
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO conversations
                    (id, agent_id, candidate_skill_ids, loaded_skill_ids,
                     agent_status, candidate_scope_source)
                VALUES ('history', 1, '[]', '[]', 'failed', 'automatic')
                """
            )
        )
    engine.dispose()

    command.downgrade(config, "0007_agent_runtime_hardening")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        singleton = connection.execute(
            text(
                """
                SELECT name, system_prompt, model, mode, max_iterations
                FROM agent_config WHERE id = 1
                """
            )
        ).one()
    engine.dispose()
    assert singleton == (
        "Reviewed Agent",
        "Reviewed prompt",
        "reviewed-model",
        "react",
        12,
    )

    command.upgrade(config, "head")

    engine = create_engine_for_url(sqlite_url(database_path))
    with engine.connect() as connection:
        agent = connection.execute(
            text(
                """
                SELECT name, system_prompt, model, mode, max_iterations, is_default
                FROM agents WHERE id = 1
                """
            )
        ).one()
        history_agent_id = connection.execute(
            text("SELECT agent_id FROM conversations WHERE id = 'history'")
        ).scalar_one()
    engine.dispose()
    assert agent == (*singleton, 1)
    assert history_agent_id == 1


def test_agent_exposes_ordered_skill_bindings_and_api_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "agent-relationships.db"
    config = migration_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine_for_url(sqlite_url(database_path))

    with Session(engine) as session:
        agent = session.get(Agent, 1)
        assert agent is not None
        session.add_all(
            [
                Skill(id=10, name="First", system_prompt="First prompt"),
                Skill(id=20, name="Second", system_prompt="Second prompt"),
            ]
        )
        agent.skills.extend(
            [
                AgentSkill(skill_id=20, position=1),
                AgentSkill(skill_id=10, position=0),
            ]
        )
        agent.api_keys.append(
            AgentApiKey(
                label="Automation",
                key_prefix="c4o_preview",
                key_hash="a" * 64,
            )
        )
        session.commit()
        session.expire_all()

        agent = session.get(Agent, 1)
        assert agent is not None
        assert [(binding.skill.id, binding.position) for binding in agent.skills] == [
            (10, 0),
            (20, 1),
        ]
        assert [(key.label, key.key_prefix, key.enabled) for key in agent.api_keys] == [
            ("Automation", "c4o_preview", True)
        ]

    engine.dispose()
