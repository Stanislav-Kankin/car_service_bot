import asyncio
import logging
from sqlalchemy import text
from app.database.db import engine, AsyncSessionLocal
from app.config import config

async def add_manager_comment_column():
    """Добавляет столбец manager_comment в таблицу requests"""
    async with AsyncSessionLocal() as session:
        try:
            # Проверяем, существует ли уже столбец
            if config.DB_TYPE == "sqlite":
                check_query = text("""
                    PRAGMA table_info(requests)
                """)
            else:  # PostgreSQL
                check_query = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'requests' AND column_name = 'manager_comment'
                """)
            
            result = await session.execute(check_query)
            columns = result.fetchall()
            
            column_exists = False
            if config.DB_TYPE == "sqlite":
                column_exists = any('manager_comment' in str(col) for col in columns)
            else:
                column_exists = len(columns) > 0
            
            if not column_exists:
                # Добавляем столбец
                if config.DB_TYPE == "sqlite":
                    alter_query = text("""
                        ALTER TABLE requests ADD COLUMN manager_comment TEXT
                    """)
                else:  # PostgreSQL
                    alter_query = text("""
                        ALTER TABLE requests ADD COLUMN manager_comment TEXT
                    """)
                
                await session.execute(alter_query)
                await session.commit()
                logging.info("✅ Столбец manager_comment успешно добавлен в таблицу requests")
            else:
                logging.info("✅ Столбец manager_comment уже существует")
                
        except Exception as e:
            logging.error(f"❌ Ошибка при добавлении столбца manager_comment: {e}")
            await session.rollback()

async def main():
    logging.basicConfig(level=logging.INFO)
    logging.info("🔄 Запуск миграции...")
    await add_manager_comment_column()
    logging.info("✅ Миграция завершена")

if __name__ == "__main__":
    asyncio.run(main())