from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def test_m6_migration_revokes_ownerless_legacy_sessions_and_adds_bound_credentials(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m6.db"
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "0008_multi_agent")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO tool_user_sessions
                    (token_hash, encrypted_login_data, encrypted_auth_data,
                     idle_expires_at, absolute_expires_at, last_used_at)
                VALUES
                    (:token_hash, :login, :auth, CURRENT_TIMESTAMP,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"token_hash": "a" * 64, "login": b"legacy", "auth": b"legacy"},
        )

    command.upgrade(config, "0009_tool_sessions")

    inspector = sa.inspect(engine)
    session_columns = {column["name"] for column in inspector.get_columns("tool_user_sessions")}
    credential_columns = {
        column["name"] for column in inspector.get_columns("tool_session_credentials")
    }
    assert {"agent_id", "agent_key_id", "admin_session_id", "status"} <= session_columns
    assert {
        "tool_session_id",
        "api_source_id",
        "encrypted_credentials",
        "status",
        "expires_at",
        "last_used_at",
    } <= credential_columns
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM tool_user_sessions")) == 0

    command.downgrade(config, "0008_multi_agent")
    downgraded = sa.inspect(engine)
    assert "tool_session_credentials" not in downgraded.get_table_names()
    assert "agent_id" not in {
        column["name"] for column in downgraded.get_columns("tool_user_sessions")
    }
    command.upgrade(config, "0009_tool_sessions")
    assert "tool_session_credentials" in sa.inspect(engine).get_table_names()
    engine.dispose()
