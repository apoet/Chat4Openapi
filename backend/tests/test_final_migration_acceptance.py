from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from chat4openapi.config import Settings, migrate_legacy_default_files


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migration_config(path: Path) -> Config:
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlite_url(path))
    return config


def test_fresh_database_reaches_the_only_alembic_head(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    config = migration_config(database)

    assert ScriptDirectory.from_config(config).get_heads() == [
        "0020_agent_description"
    ]
    command.upgrade(config, "head")

    engine = sa.create_engine(sqlite_url(database))
    inspector = sa.inspect(engine)
    assert {
        "agents",
        "auto_agentify_job_events",
        "auto_agentify_jobs",
        "agent_api_keys",
        "agent_skills",
        "api_sources",
        "browser_chat_sessions",
        "conversations",
        "skills",
        "tool_session_credentials",
        "tools",
    } <= set(inspector.get_table_names())
    assert "encrypted_request_config" in {
        column["name"]
        for column in inspector.get_columns("api_source_tool_auth_configs")
    }
    assert "description" in {
        column["name"] for column in inspector.get_columns("agents")
    }
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
            "0020_agent_description"
        )
    engine.dispose()


def test_0007_representative_installation_reaches_head_without_data_loss(
    tmp_path: Path,
) -> None:
    database = tmp_path / "existing-0007.db"
    config = migration_config(database)
    command.upgrade(config, "0007_agent_runtime_hardening")
    engine = sa.create_engine(sqlite_url(database))

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO admin_users
                    (id, username, password_hash, locale, enabled)
                VALUES (1, 'operator', 'preserved-password-hash', 'zh-CN', true)
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO admin_sessions
                    (id, admin_id, token_hash, csrf_hash, idle_expires_at,
                     absolute_expires_at)
                VALUES
                    (7, 1, 'preserved-session-hash', 'preserved-csrf-hash',
                     '2099-01-01 00:00:00', '2099-01-02 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO llm_providers
                    (id, name, provider_type, base_url, encrypted_api_key,
                     default_model, enabled)
                VALUES
                    (3, 'Preserved provider', 'openai', 'https://llm.example/v1',
                     :secret, 'preserved-model', true)
                """
            ),
            {"secret": b"encrypted-provider-secret"},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO api_sources
                    (id, name, source_type, base_url, spec_snapshot, spec_hash,
                     allow_private_networks, enabled, document_url)
                VALUES
                    (5, 'Preserved API', 'openapi', 'https://api.example',
                     :snapshot, 'preserved-hash', false, true,
                     'https://api.example/openapi.json')
                """
            ),
            {"snapshot": '{"openapi":"3.0.0"}'},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO tools
                    (id, api_source_id, operation_key, name, description,
                     input_schema, execution_schema, enabled)
                VALUES
                    (11, 5, 'GET /orders', 'listOrders', 'Preserved Tool',
                     :input_schema, :execution_schema, true)
                """
            ),
            {
                "input_schema": json.dumps(
                    {"type": "object", "properties": {"limit": {"type": "integer"}}}
                ),
                "execution_schema": json.dumps(
                    {"method": "GET", "path": "/orders", "parameters": []}
                ),
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO tool_parameter_overrides
                    (id, tool_id, argument_name, description, example)
                VALUES (13, 11, 'limit', 'Preserved guidance', '25')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO skills
                    (id, name, description, system_prompt, running)
                VALUES
                    (17, 'Preserved Skill', 'Preserved description',
                     'Use {{tool:listOrders}}.', true)
                """
            )
        )
        connection.execute(
            sa.text("INSERT INTO skill_tools (skill_id, tool_id, position) VALUES (17, 11, 0)")
        )
        connection.execute(
            sa.text(
                """
                UPDATE agent_config
                SET name = 'Preserved Agent', provider_id = 3,
                    system_prompt = 'Preserved agent prompt', model = 'agent-model',
                    mode = 'react', max_iterations = 12
                WHERE id = 1
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO conversations
                    (id, skill_id, title, candidate_skill_ids, loaded_skill_ids,
                     agent_mode, agent_status, pending_clarification,
                     candidate_scope_source, latest_failure_summary)
                VALUES
                    ('preserved-conversation', 17, 'Preserved history', '[17]', '[17]',
                     'react', 'running', NULL, 'explicit', NULL)
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO chat_messages
                    (conversation_id, sequence, role, content, request_id)
                VALUES
                    ('preserved-conversation', 0, 'user', :content, 'request-1')
                """
            ),
            {"content": json.dumps({"text": "Preserve this message"})},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO tool_user_sessions
                    (token_hash, encrypted_login_data, encrypted_auth_data,
                     idle_expires_at, absolute_expires_at, last_used_at)
                VALUES
                    (:token_hash, :login_secret, :auth_secret,
                     '2099-01-01 00:00:00', '2099-01-02 00:00:00', CURRENT_TIMESTAMP)
                """
            ),
            {
                "token_hash": "a" * 64,
                "login_secret": b"legacy-encrypted-login",
                "auth_secret": b"legacy-encrypted-auth",
            },
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = sa.create_engine(sqlite_url(database))
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT username, password_hash, locale, role "
                "FROM admin_users WHERE id = 1"
            )
        ).one() == ("operator", "preserved-password-hash", "zh-CN", "admin")
        assert connection.execute(
            sa.text("SELECT token_hash, csrf_hash FROM admin_sessions WHERE id = 7")
        ).one() == ("preserved-session-hash", "preserved-csrf-hash")
        assert connection.scalar(
            sa.text("SELECT encrypted_api_key FROM llm_providers WHERE id = 3")
        ) == b"encrypted-provider-secret"
        assert connection.execute(
            sa.text(
                """
                SELECT name, base_url, spec_snapshot, spec_hash, document_url
                FROM api_sources WHERE id = 5
                """
            )
        ).one() == (
            "Preserved API",
            "https://api.example",
            '{"openapi":"3.0.0"}',
            "preserved-hash",
            "https://api.example/openapi.json",
        )
        tool = connection.execute(
            sa.text(
                """
                SELECT name, description, input_schema, execution_schema, enabled
                FROM tools WHERE id = 11
                """
            )
        ).one()
        assert tool.name == "listOrders"
        assert tool.description == "Preserved Tool"
        assert json.loads(tool.input_schema)["properties"]["limit"]["type"] == "integer"
        assert json.loads(tool.execution_schema)["path"] == "/orders"
        assert tool.enabled == 1
        assert connection.execute(
            sa.text(
                """
                SELECT s.name, s.system_prompt, st.tool_id, st.position
                FROM skills AS s JOIN skill_tools AS st ON st.skill_id = s.id
                WHERE s.id = 17
                """
            )
        ).one() == ("Preserved Skill", "Use {{tool:listOrders}}.", 11, 0)
        assert connection.execute(
            sa.text("SELECT skill_id, position FROM agent_skills WHERE agent_id = 1")
        ).one() == (17, 0)
        assert connection.execute(
            sa.text(
                """
                SELECT name, provider_id, system_prompt, model, mode, max_iterations
                FROM agents WHERE id = 1
                """
            )
        ).one() == (
            "Preserved Agent",
            3,
            "Preserved agent prompt",
            "agent-model",
            "react",
            12,
        )
        conversation = connection.execute(
            sa.text(
                """
                SELECT agent_id, candidate_skill_ids, loaded_skill_ids, agent_status,
                       deleted_at IS NOT NULL, latest_failure_summary,
                       agent_key_id, browser_chat_session_id
                FROM conversations WHERE id = 'preserved-conversation'
                """
            )
        ).one()
        assert conversation == (
            1,
            "[17]",
            "[17]",
            "revoked",
            1,
            "Conversation predates owner isolation and cannot be resumed.",
            None,
            None,
        )
        assert connection.scalar(
            sa.text(
                "SELECT content FROM chat_messages WHERE conversation_id = 'preserved-conversation'"
            )
        ) == '{"text": "Preserve this message"}'
        assert connection.scalar(sa.text("SELECT count(*) FROM tool_user_sessions")) == 0
    engine.dispose()


def test_head_to_0007_to_head_preserves_default_configuration_and_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "roundtrip.db"
    config = migration_config(database)
    command.upgrade(config, "head")
    engine = sa.create_engine(sqlite_url(database))
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE agents
                SET name = 'Roundtrip Agent', system_prompt = 'Roundtrip prompt',
                    model = 'roundtrip-model', mode = 'react', max_iterations = 14
                WHERE id = 1
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO browser_chat_sessions
                    (id, token_hash, public_subject_id, expires_at)
                VALUES
                    (1, 'roundtrip-browser-token',
                     '00000000-0000-0000-0000-000000000001', '2099-01-01 00:00:00')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO conversations
                    (id, agent_id, browser_chat_session_id, candidate_skill_ids,
                     loaded_skill_ids, agent_status, candidate_scope_source, title)
                VALUES
                    ('roundtrip-history', 1, 1, '[]', '[]', 'completed',
                     'automatic', 'Roundtrip history')
                """
            )
        )
    engine.dispose()

    command.downgrade(config, "0007_agent_runtime_hardening")
    engine = sa.create_engine(sqlite_url(database))
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                """
                SELECT name, system_prompt, model, mode, max_iterations
                FROM agent_config WHERE id = 1
                """
            )
        ).one() == (
            "Roundtrip Agent",
            "Roundtrip prompt",
            "roundtrip-model",
            "react",
            14,
        )
        assert connection.scalar(
            sa.text("SELECT title FROM conversations WHERE id = 'roundtrip-history'")
        ) == "Roundtrip history"
    engine.dispose()

    command.upgrade(config, "head")
    engine = sa.create_engine(sqlite_url(database))
    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                """
                SELECT name, system_prompt, model, mode, max_iterations, is_default
                FROM agents WHERE id = 1
                """
            )
        ).one() == (
            "Roundtrip Agent",
            "Roundtrip prompt",
            "roundtrip-model",
            "react",
            14,
            1,
        )
        assert connection.execute(
            sa.text(
                """
                SELECT title, agent_id, agent_status, deleted_at IS NOT NULL
                FROM conversations WHERE id = 'roundtrip-history'
                """
            )
        ).one() == ("Roundtrip history", 1, "revoked", 1)
    engine.dispose()


def test_legacy_default_database_and_key_migrate_atomically_without_overwrite(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    legacy_stem = "chat" + "api"
    old_database = data / f"{legacy_stem}.db"
    old_key = data / f".{legacy_stem}.key"
    new_database = data / "chat4openapi.db"
    new_key = data / ".chat4openapi.key"
    old_database.write_bytes(b"legacy-database")
    old_key.write_bytes(b"legacy-key")

    migrate_legacy_default_files(Settings(_env_file=None))

    assert new_database.read_bytes() == b"legacy-database"
    assert new_key.read_bytes() == b"legacy-key"
    assert not old_database.exists()
    assert not old_key.exists()

    old_database.write_bytes(b"must-not-overwrite-database")
    old_key.write_bytes(b"must-not-overwrite-key")
    migrate_legacy_default_files(Settings(_env_file=None))

    assert new_database.read_bytes() == b"legacy-database"
    assert new_key.read_bytes() == b"legacy-key"
    assert old_database.read_bytes() == b"must-not-overwrite-database"
    assert old_key.read_bytes() == b"must-not-overwrite-key"
