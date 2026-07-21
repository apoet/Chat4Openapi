from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from chat4openapi.db.session import create_engine_for_url


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_sqlite_engine_enables_required_pragmas(tmp_path: Path) -> None:
    engine = create_engine_for_url(sqlite_url(tmp_path / "pragmas.db"))

    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    engine.dispose()
    assert foreign_keys == 1
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000


def test_initial_migration_creates_foundation_tables(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "migrated.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine_for_url(database_url)
    table_names = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"admin_users", "admin_sessions", "app_settings"} <= table_names


def test_agent_runtime_migration_creates_persistence_schema(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "agent-runtime.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine_for_url(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    conversation_column_details = inspector.get_columns("conversations")
    conversation_columns = {column["name"] for column in conversation_column_details}
    conversation_agent_column = next(
        column for column in conversation_column_details if column["name"] == "agent_id"
    )
    skill_columns = {column["name"] for column in inspector.get_columns("skills")}
    agent_skill_columns = {column["name"] for column in inspector.get_columns("agent_skills")}
    agent_key_columns = {column["name"] for column in inspector.get_columns("agent_api_keys")}
    with engine.connect() as connection:
        default_agents = connection.execute(
            text("SELECT id, is_default FROM agents ORDER BY id")
        ).all()
    engine.dispose()

    assert {
        "agents",
        "agent_skills",
        "agent_api_keys",
        "tool_parameter_overrides",
    } <= table_names
    assert "agent_config" not in table_names
    assert {
        "candidate_skill_ids",
        "loaded_skill_ids",
        "agent_mode",
        "agent_status",
        "pending_clarification",
        "candidate_scope_source",
        "latest_failure_summary",
        "agent_id",
    } <= conversation_columns
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    agent_checks = {constraint["name"] for constraint in inspector.get_check_constraints("agents")}
    assert {"is_default", "created_at", "updated_at", "deleted_at"} <= agent_columns
    assert {"agent_id", "skill_id", "position"} == agent_skill_columns
    assert {
        "agent_id",
        "label",
        "key_prefix",
        "key_hash",
        "enabled",
        "expires_at",
        "last_used_at",
        "created_at",
        "updated_at",
        "revoked_at",
        "deleted_at",
    } <= agent_key_columns
    assert {"ck_agent_mode", "ck_agent_max_iterations"} <= agent_checks
    assert {"provider_id", "model"}.isdisjoint(skill_columns)
    assert conversation_agent_column["nullable"] is False
    assert default_agents == [(1, 1)]


def test_database_constraints_reject_invalid_agent_runtime_settings(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "agent-checks.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE agents SET mode = 'invalid' WHERE id = 1"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE agents SET max_iterations = 1 WHERE id = 1"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO agents
                    (name, enabled, is_default, system_prompt, mode, max_iterations)
                VALUES
                    ('Another Default', true, true, 'Prompt', 'react', 8)
                """
            )
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO agents
                    (name, enabled, is_default, system_prompt, mode,
                     max_iterations, deleted_at)
                VALUES
                    ('Deleted Default', false, true, 'Prompt', 'react', 8,
                     CURRENT_TIMESTAMP)
                """
            )
        )

    engine.dispose()


def test_0007_downgrade_and_reupgrade_round_trip(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "agent-hardening-round-trip.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "0006_varcards_markdown_prompt")
    engine = create_engine_for_url(database_url)
    inspector = inspect(engine)
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    agent_columns = {column["name"] for column in inspector.get_columns("agent_config")}
    engine.dispose()
    assert "candidate_scope_source" not in conversation_columns
    assert "latest_failure_summary" not in conversation_columns
    assert {"created_at", "updated_at"}.isdisjoint(agent_columns)

    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    inspector = inspect(engine)
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    engine.dispose()
    assert {"candidate_scope_source", "latest_failure_summary"} <= conversation_columns
    assert {"created_at", "updated_at"} <= agent_columns


def test_0007_allows_distinct_tool_rows_to_share_a_name(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "tool-name-scope.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO api_sources (id, name, source_type, base_url, enabled)
                VALUES
                    (1, 'First', 'openapi', 'https://first.test', true),
                    (2, 'Second', 'openapi', 'https://second.test', true)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tools
                    (api_source_id, operation_key, name, input_schema,
                     execution_schema, enabled)
                VALUES
                    (1, 'GET /first', 'shared_name', '{}', '{}', true),
                    (2, 'GET /second', 'shared_name', '{}', '{}', true)
                """
            )
        )
    engine.dispose()


def test_0007_downgrade_deterministically_names_colliding_tools(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "tool-name-downgrade.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO api_sources (id, name, source_type, base_url, enabled)
                VALUES
                    (1, 'First', 'openapi', 'https://first.test', true),
                    (2, 'Second', 'openapi', 'https://second.test', true)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tools
                    (id, api_source_id, operation_key, name, input_schema,
                     execution_schema, enabled)
                VALUES
                    (10, 1, 'GET /first', 'shared_name', '{}', '{}', true),
                    (20, 2, 'GET /second', 'shared_name', '{}', '{}', true)
                """
            )
        )
    engine.dispose()

    command.downgrade(config, "0006_varcards_markdown_prompt")

    engine = create_engine_for_url(database_url)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, name FROM tools ORDER BY id")).all()
    assert rows == [(10, "shared_name"), (20, "shared_name__legacy_20")]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tools
                    (api_source_id, operation_key, name, input_schema,
                     execution_schema, enabled)
                VALUES (1, 'GET /third', 'shared_name', '{}', '{}', true)
                """
            )
        )
    engine.dispose()
