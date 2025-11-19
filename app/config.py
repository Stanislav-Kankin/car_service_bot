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

    # Настройки менеджера (ДОБАВЛЯЕМ)
    MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")  # ID чата/группы менеджера
    ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")  # ID пользователя администратора

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ Отсутствует BOT_TOKEN в .env файле")
        
        if not cls.MANAGER_CHAT_ID:
            print("⚠️  MANAGER_CHAT_ID не установлен - уведомления менеджеру не будут отправляться")
        else:
            # Проверяем, что это ID группы (отрицательный)
            if int(cls.MANAGER_CHAT_ID) > 0:
                print("⚠️  MANAGER_CHAT_ID должен быть отрицательным числом для групп")


config = Config()
