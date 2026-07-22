from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from chat4openapi.db.session import create_engine_for_url


def _config(path: Path) -> Config:
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return config


def test_0013_adds_embed_schema_and_preserves_existing_conversation(tmp_path: Path) -> None:
    database = tmp_path / "embed-migration.db"
    config = _config(database)
    command.upgrade(config, "0012_conversation_owners")
    engine = create_engine_for_url(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO browser_chat_sessions
                    (id, token_hash, public_subject_id, expires_at)
                VALUES
                    (1, :token_hash, :subject_id, '2099-01-01 00:00:00')
                """
            ),
            {"token_hash": "b" * 64, "subject_id": "existing-browser-subject"},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO conversations
                    (id, agent_id, browser_chat_session_id, candidate_skill_ids,
                     candidate_scope_source, loaded_skill_ids, agent_status)
                VALUES
                    ('existing-conversation', 1, 1, '[]', 'automatic', '[]', 'running')
                """
            )
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine_for_url(f"sqlite:///{database.as_posix()}")
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    conversation_columns = {item["name"] for item in inspector.get_columns("conversations")}
    tool_session_columns = {
        item["name"] for item in inspector.get_columns("tool_user_sessions")
    }
    setting_columns = {item["name"] for item in inspector.get_columns("app_settings")}
    with engine.connect() as connection:
        owner = connection.execute(
            sa.text(
                """
                SELECT browser_chat_session_id, embed_session_id
                FROM conversations WHERE id = 'existing-conversation'
                """
            )
        ).one()
    engine.dispose()

    assert {"agent_embeds", "embed_sessions", "embed_auth_grants"} <= tables
    assert "base_url" in setting_columns
    assert "embed_session_id" in conversation_columns
    assert "embed_session_id" in tool_session_columns
    assert owner == (1, None)


def test_0013_downgrade_and_reupgrade_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "embed-round-trip.db"
    config = _config(database)
    command.upgrade(config, "head")
    command.downgrade(config, "0012_conversation_owners")

    engine = create_engine_for_url(f"sqlite:///{database.as_posix()}")
    inspector = sa.inspect(engine)
    assert "agent_embeds" not in inspector.get_table_names()
    assert "embed_session_id" not in {
        item["name"] for item in inspector.get_columns("conversations")
    }
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine_for_url(f"sqlite:///{database.as_posix()}")
    assert "agent_embeds" in sa.inspect(engine).get_table_names()
    engine.dispose()
