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
    # postgres или sqlite
    DB_TYPE = os.getenv("DB_TYPE", "sqlite").lower()

    if DB_TYPE == "postgres":
        # URL для Postgres:
        #   можно задать через DB_URL
        #   либо (как у тебя) через POSTGRES_PASSWORD, где уже лежит полный URL
        DB_URL = os.getenv("DB_URL") or os.getenv("POSTGRES_PASSWORD")
        if not DB_URL:
            # фоллбек, чтобы не упасть совсем
            DB_URL = "postgresql+asyncpg://car_bot_user:password@localhost/car_service_bot"
    else:
        # SQLite для разработки (aiosqlite добавляется в db.py)
        DB_URL = os.getenv("SQLITE_DB_URL", "sqlite:///./car_service_bot.db")

    # -------------------
    # Redis
    # -------------------
    REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"

    # -------------------
    # Чаты / пользователи
    # -------------------
    # Жёстко приводим к int с дефолтами, чтобы точно не было None
    # Если .env не подхватится — всё равно будет твой тестовый ID
    try:
        MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "-5052775827"))
    except ValueError:
        print(f"⚠️ Некорректный MANAGER_CHAT_ID={os.getenv('MANAGER_CHAT_ID')!r}, использую -5052775827")
        MANAGER_CHAT_ID = -5052775827

    try:
        ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "281146928"))
    except ValueError:
        print(f"⚠️ Некорректный ADMIN_USER_ID={os.getenv('ADMIN_USER_ID')!r}, использую 281146928")
        ADMIN_USER_ID = 281146928

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ Отсутствует BOT_TOKEN в .env файле")

        print(f"ℹ️ DB_TYPE={cls.DB_TYPE}, DB_URL={cls.DB_URL}")
        print(f"ℹ️ MANAGER_CHAT_ID={cls.MANAGER_CHAT_ID}, ADMIN_USER_ID={cls.ADMIN_USER_ID}")

        # Лёгкая проверка на формат ID группы
        if cls.MANAGER_CHAT_ID > 0:
            print("⚠️ MANAGER_CHAT_ID выглядит как положительный ID. Для групп обычно ID отрицательный.")


config = Config()
