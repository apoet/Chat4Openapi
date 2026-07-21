from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from chatapi.db.session import create_engine_for_url


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
    conversation_columns = {
        column["name"] for column in inspector.get_columns("conversations")
    }
    skill_columns = {column["name"] for column in inspector.get_columns("skills")}
    engine.dispose()

    assert {"agent_config", "tool_parameter_overrides"} <= table_names
    assert {
        "candidate_skill_ids",
        "loaded_skill_ids",
        "agent_mode",
        "agent_status",
        "pending_clarification",
    } <= conversation_columns
    assert {"provider_id", "model"}.isdisjoint(skill_columns)
