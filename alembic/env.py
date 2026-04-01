from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config.settings import make_sync_sqlalchemy_url
from app.db.base import Base
from app.models import *  # noqa: F401,F403

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_migration_url() -> str:
    sync_url = os.getenv("DATABASE_URL_SYNC")
    if sync_url:
        return sync_url

    runtime_url = os.getenv("DATABASE_URL")
    if runtime_url:
        return make_sync_sqlalchemy_url(runtime_url)

    return make_sync_sqlalchemy_url(config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    url = get_migration_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    alembic_config = config.get_section(config.config_ini_section, {})
    alembic_config["sqlalchemy.url"] = get_migration_url()
    connectable = engine_from_config(
        alembic_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
