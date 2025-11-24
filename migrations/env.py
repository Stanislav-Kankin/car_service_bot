from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 🔗 Импортируем конфиг приложения и Base
from app.config import config as app_config
from app.database.base import Base

# ВАЖНО: импортируем модели, чтобы Alembic видел все таблицы
from app.database import models  # noqa: F401
from app.database import bonus_models  # noqa: F401
from app.database import comment_models  # noqa: F401


# Это стандартный alembic Config (НЕ путать с app.config)
alembic_config = context.config

# Подключаем logging из alembic.ini
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# metadata всех моделей
target_metadata = Base.metadata


def _get_sync_url() -> str:
    """
    Берём URL из app.config.Config.DB_URL,
    и приводим его к синхронному виду.

    - postgres: убираем "+asyncpg"
    - sqlite: оставляем "sqlite://"
    """
    url = app_config.DB_URL

    # Типичные варианты:
    # postgresql+asyncpg://...  -> postgresql://...
    # sqlite:///...             -> sqlite:///...
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "")
    if "+aiosqlite" in url:
        url = url.replace("+aiosqlite", "")

    return url


def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме (без реального подключения)."""
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Запуск миграций в online-режиме (с подключением к БД)."""
    # Подменяем sqlalchemy.url в alembic_config на наш
    url = _get_sync_url()
    alembic_config.set_main_option("sqlalchemy.url", url)

    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
