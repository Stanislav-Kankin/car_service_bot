import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # Умное определение БД
    DB_TYPE = os.getenv("DB_TYPE", "sqlite")  # postgres или sqlite

    if DB_TYPE == "postgres":
        # PostgreSQL для продакшена
        DB_URL = os.getenv(
            "DB_URL"
            ) or "postgresql+asyncpg://car_bot_user:password@localhost/car_service_bot"
    else:
        # SQLite для разработки
        DB_URL = "sqlite:///./car_service_bot.db"

    REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ Отсутствует BOT_TOKEN в .env файле")

        print(f"🔧 Используется БД: {cls.DB_TYPE}")
        print(f"🔧 DB_URL: {
            cls.DB_URL.replace(
                '//', '//***:***@') if 'postgres' in cls.DB_URL else cls.DB_URL
            }")


config = Config()
