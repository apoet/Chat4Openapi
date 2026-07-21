from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from chat4openapi.config import Settings, migrate_legacy_default_files
from chat4openapi.db.base import Base
from chat4openapi import models  # noqa: F401

config = context.config
migrate_legacy_default_files(
    Settings(database_url=config.get_main_option("sqlalchemy.url"), _env_file=None)
)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
