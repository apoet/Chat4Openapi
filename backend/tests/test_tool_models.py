from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatapi.db.session import create_engine_for_url
from chatapi.models import ApiSource, GlobalToolAuthConfig, Tool


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migrated_engine(tmp_path: Path):
    database_url = sqlite_url(tmp_path / "tool-runtime.db")
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return config, create_engine_for_url(database_url)


def test_tool_runtime_migration_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    config, engine = migrated_engine(tmp_path)
    expected = {
        "api_sources",
        "tools",
        "global_tool_auth_config",
        "tool_user_sessions",
        "tool_invocations",
    }

    assert expected <= set(inspect(engine).get_table_names())
    tool_foreign_keys = inspect(engine).get_foreign_keys("tools")
    assert any(
        key["referred_table"] == "api_sources"
        and key["constrained_columns"] == ["api_source_id"]
        for key in tool_foreign_keys
    )
    unique_constraints = inspect(engine).get_unique_constraints("tools")
    assert any(
        set(item["column_names"]) == {"api_source_id", "operation_key"}
        for item in unique_constraints
    )
    assert "document_url" in {
        column["name"] for column in inspect(engine).get_columns("api_sources")
    }

    engine.dispose()
    command.downgrade(config, "0001_foundation")
    downgraded = create_engine_for_url(config.get_main_option("sqlalchemy.url"))
    assert expected.isdisjoint(inspect(downgraded).get_table_names())
    downgraded.dispose()

    command.upgrade(config, "head")
    upgraded = create_engine_for_url(config.get_main_option("sqlalchemy.url"))
    assert expected <= set(inspect(upgraded).get_table_names())
    upgraded.dispose()


def test_tool_operation_is_unique_within_source(tmp_path: Path) -> None:
    _, engine = migrated_engine(tmp_path)
    with Session(engine) as session:
        source = ApiSource(name="Example", source_type="openapi", base_url="https://api.test")
        session.add(source)
        session.flush()
        session.add_all(
            [
                Tool(
                    api_source_id=source.id,
                    operation_key="GET /pets",
                    name="list_pets",
                    input_schema={"type": "object"},
                    execution_schema={"method": "GET", "path": "/pets"},
                ),
                Tool(
                    api_source_id=source.id,
                    operation_key="GET /pets",
                    name="list_pets_again",
                    input_schema={"type": "object"},
                    execution_schema={"method": "GET", "path": "/pets"},
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_global_tool_auth_config_is_singleton(tmp_path: Path) -> None:
    _, engine = migrated_engine(tmp_path)
    with Session(engine) as session:
        session.add(GlobalToolAuthConfig(id=2))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
