from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ebook_converter_bot.db import Analytics, Chat, Preference, UserOptionDefault  # noqa: F401
from ebook_converter_bot.db.base import Base
from ebook_converter_bot.db.session import db_connection_string

config = context.config
config.set_main_option("sqlalchemy.url", db_connection_string)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_connection_string,
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
