"""Alembic environment. sqlalchemy.url comes from app.config.settings(), not alembic.ini —
one source of truth for DATABASE_URL, matching how the app itself connects (app/db.py).

★ `--autogenerate` renders custom TypeDecorator columns (GUID, in models/base.py) as
`app.models.base.GUID(...)` but does not add the `import app.models.base` line itself —
add it by hand to each new migration file that touches a GUID column, or `alembic upgrade`
fails with `NameError: name 'app' is not defined`."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings().database_url
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
