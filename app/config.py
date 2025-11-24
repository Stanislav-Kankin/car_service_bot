import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # -------------------
    # Бот
    # -------------------
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # -------------------
    # База данных
    # -------------------
    DB_TYPE = os.getenv("DB_TYPE", "sqlite").lower()

    if DB_TYPE == "postgres":
        DB_URL = os.getenv("DB_URL") or os.getenv("POSTGRES_PASSWORD")
        if not DB_URL:
            DB_URL = "postgresql+asyncpg://car_bot_user:password@localhost/car_service_bot"
    else:
        DB_URL = os.getenv("SQLITE_DB_URL", "sqlite:///./car_service_bot.db")

    # -------------------
    # Redis
    # -------------------
    REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"

    # -------------------
    # Чаты / пользователи
    # -------------------
    raw_manager_chat_id = os.getenv("MANAGER_CHAT_ID")
    MANAGER_CHAT_ID = None
    if raw_manager_chat_id:
        try:
            MANAGER_CHAT_ID = int(raw_manager_chat_id)
        except ValueError:
            print(
                f"⚠️ Некорректный MANAGER_CHAT_ID={raw_manager_chat_id!r}, "
                f"глобальный чат менеджера отключён"
            )
            MANAGER_CHAT_ID = None

    # -------------------
    # Администраторы
    # -------------------
    ADMIN_USER_IDS = set()

    # Чтение из .env (можно указать через запятую)
    _raw_ids = os.getenv("ADMIN_USER_IDS", "281146928").split(",")
    for raw in _raw_ids:
        raw = raw.strip()
        if raw.isdigit():
            ADMIN_USER_IDS.add(int(raw))

    # Добавляем второго админа (временно вручную)
    ADMIN_USER_IDS.add(6143087987)

    # -------------------
    # Бонусы / монетизация
    # -------------------
    try:
        BONUS_REGISTER = int(os.getenv("BONUS_REGISTER", "10"))
        BONUS_NEW_REQUEST = int(os.getenv("BONUS_NEW_REQUEST", "5"))
        BONUS_ACCEPT_OFFER = int(os.getenv("BONUS_ACCEPT_OFFER", "3"))
        BONUS_COMPLETE_REQUEST = int(os.getenv("BONUS_COMPLETE_REQUEST", "2"))
        BONUS_RATE_SERVICE = int(os.getenv("BONUS_RATE_SERVICE", "10"))
    except ValueError:
        BONUS_REGISTER = 10
        BONUS_NEW_REQUEST = 5
        BONUS_ACCEPT_OFFER = 3
        BONUS_COMPLETE_REQUEST = 2
        BONUS_RATE_SERVICE = 10

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ Отсутствует BOT_TOKEN в .env файле")

        print(f"ℹ️ DB_TYPE={cls.DB_TYPE}, DB_URL={cls.DB_URL}")
        print(f"ℹ️ MANAGER_CHAT_ID={cls.MANAGER_CHAT_ID}")
        print(f"ℹ️ ADMIN_USER_IDS={cls.ADMIN_USER_IDS}")

        if cls.MANAGER_CHAT_ID is not None and cls.MANAGER_CHAT_ID > 0:
            print(
                "⚠️ MANAGER_CHAT_ID выглядит как положительный ID. "
                "Для групп обычно ID отрицательный."
            )


config = Config()
