from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config

from chat4openapi.config import Settings, migrate_legacy_default_files, migrate_legacy_file


def test_legacy_default_files_move_without_overwriting(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    current = tmp_path / "chat4openapi.db"
    legacy.write_bytes(b"sqlite")

    migrate_legacy_file(legacy, current)

    assert current.read_bytes() == b"sqlite"
    assert not legacy.exists()


def test_existing_new_file_is_never_overwritten(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    current = tmp_path / "chat4openapi.db"
    legacy.write_bytes(b"old")
    current.write_bytes(b"new")

    migrate_legacy_file(legacy, current)

    assert current.read_bytes() == b"new"
    assert legacy.read_bytes() == b"old"


def test_destination_created_during_migration_is_never_overwritten(
    tmp_path: Path, monkeypatch,
) -> None:
    legacy = tmp_path / "legacy.db"
    current = tmp_path / "chat4openapi.db"
    legacy.write_bytes(b"old")
    original_mkdir = Path.mkdir

    def mkdir_then_create_destination(path: Path, *args, **kwargs) -> None:
        original_mkdir(path, *args, **kwargs)
        if path == current.parent:
            current.write_bytes(b"new")

    monkeypatch.setattr(Path, "mkdir", mkdir_then_create_destination)

    migrate_legacy_file(legacy, current)

    assert current.read_bytes() == b"new"
    assert legacy.read_bytes() == b"old"


def test_legacy_default_database_and_key_are_migrated(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    legacy_database = data / ("chat" + "api.db")
    legacy_key = data / (".chat" + "api.key")
    legacy_database.write_bytes(b"database")
    legacy_key.write_bytes(b"secret")

    migrate_legacy_default_files(Settings(_env_file=None))

    assert (data / "chat4openapi.db").read_bytes() == b"database"
    assert (data / ".chat4openapi.key").read_bytes() == b"secret"
    assert not legacy_database.exists()
    assert not legacy_key.exists()


def test_custom_paths_do_not_move_legacy_default_files(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    legacy_database = data / ("chat" + "api.db")
    legacy_key = data / (".chat" + "api.key")
    legacy_database.write_bytes(b"database")
    legacy_key.write_bytes(b"secret")
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'custom.db').as_posix()}",
        encryption_key_file=tmp_path / "custom.key",
        _env_file=None,
    )

    migrate_legacy_default_files(settings)

    assert legacy_database.read_bytes() == b"database"
    assert legacy_key.read_bytes() == b"secret"


def test_settings_use_only_the_new_environment_prefix(monkeypatch) -> None:
    monkeypatch.setenv("CHAT" + "API_DEFAULT_LOCALE", "zh-CN")

    assert Settings(_env_file=None).default_locale == "en-US"

    monkeypatch.setenv("CHAT4OPENAPI_DEFAULT_LOCALE", "zh-CN")
    assert Settings(_env_file=None).default_locale == "zh-CN"


def test_alembic_default_config_migrates_the_existing_database(
    tmp_path: Path, monkeypatch,
) -> None:
    config_path = Path(__file__).parents[1] / "alembic.ini"
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    legacy_database = data / ("chat" + "api.db")
    connection = sqlite3.connect(legacy_database)
    try:
        connection.execute("CREATE TABLE preserved_data (value TEXT NOT NULL)")
        connection.execute("INSERT INTO preserved_data VALUES ('kept')")
        connection.commit()
    finally:
        connection.close()

    command.upgrade(Config(config_path.as_posix()), "head")

    current_database = data / "chat4openapi.db"
    assert current_database.exists()
    assert not legacy_database.exists()
    with sqlite3.connect(current_database) as connection:
        value = connection.execute("SELECT value FROM preserved_data").fetchone()
    assert value == ("kept",)
