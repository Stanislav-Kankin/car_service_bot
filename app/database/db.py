from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import config
from app.database.base import Base  # ← Импортируем Base из base.py
from app.database.models import User, Car, Request  # ← Теперь это безопасно
import logging

# Асинхронный движок
if config.DB_TYPE == "postgres":
    DB_URL = config.DB_URL.replace("postgresql://", "postgresql+asyncpg://")
else:
    DB_URL = config.DB_URL.replace("sqlite://", "sqlite+aiosqlite://")

engine = create_async_engine(DB_URL, echo=True)

# Асинхронная сессия
AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession,
    expire_on_commit=False
)


async def create_tables():
    """Асинхронное создание таблиц"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logging.info("✅ Таблицы БД успешно созданы/проверены")
        # Логируем созданные таблицы
        logging.info(f"📊 Созданные таблицы: {list(Base.metadata.tables.keys())}")
    except Exception as e:
        logging.error(f"❌ Ошибка при создании таблиц БД: {e}")
        raise


async def get_async_session():
    """Dependency для получения асинхронной сессии"""
    async with AsyncSessionLocal() as session:
        yield session