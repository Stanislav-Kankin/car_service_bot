import asyncio
import logging
import sys
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import config
from app.database import db
from app.handlers import user_handlers, manager_handlers, group_handlers, chat_handlers
from app.handlers.admin_handlers import router as admin_router

async def main():
    # Проверяем конфигурацию перед запуском
    try:
        config.validate()
    except ValueError as e:
        logging.error(f"Ошибка конфигурации: {e}")
        logging.info(
            "Убедитесь, что файл .env существует и содержит BOT_TOKEN"
            )
        return

    # Настройка логирования
    logging.basicConfig(level=logging.INFO)
    logging.info("Запуск бота...")

    # Инициализация бота и диспетчера
    try:
        redis = Redis.from_url(config.REDIS_URL)
        storage = RedisStorage(redis=redis)
        bot = Bot(token=config.BOT_TOKEN)
        dp = Dispatcher(storage=storage)

        # Регистрация роутеров
        dp.include_router(user_handlers.router)
        dp.include_router(manager_handlers.router)
        dp.include_router(group_handlers.router)
        dp.include_router(chat_handlers.router)
        dp.include_router(admin_router)

        # Создание таблиц в БД (АСИНХРОННО с await!)
        await db.create_tables()  # ← ДОБАВИТЬ AWAIT
        logging.info("Таблицы БД созданы/проверены")

        # Запуск поллинга
        logging.info("Бот запущен и готов к работе!")
        await dp.start_polling(bot)

    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
