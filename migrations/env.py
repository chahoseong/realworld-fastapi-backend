from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from app.articles.models import Article, ArticleTag, Tag  # noqa: F401
from app.config import get_settings
from app.database import Base
from app.users.models import User  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    database_url = config.attributes.get("database_url")
    if database_url is not None:
        return str(database_url)
    return str(get_settings().database_url)


def configure_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        configure_context(connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    migration_engine = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )
    with migration_engine.connect() as connection:
        configure_context(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
