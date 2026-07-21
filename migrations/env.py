from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401 - registers ORM models on Base.metadata
from app.config import get_settings
from app.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without opening a database connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=settings.database_url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a short-lived, non-pooled connection."""
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
