import asyncio
import logging
from sqlalchemy import text
from app.database.db import engines

async def migrate_database():
    """Добавляет новые поля в таблицу requests"""
    async with engine.begin() as conn:
        try:
            # Проверяем существование полей
            result = await conn.execute(text("PRAGMA table_info(requests)"))
            existing_columns = [row[1] for row in result]
            
            columns_to_add = [
                'accepted_at',
                'in_progress_at', 
                'completed_at',
                'rejected_at'
            ]
            
            for column in columns_to_add:
                if column not in existing_columns:
                    await conn.execute(text(f"ALTER TABLE requests ADD COLUMN {column} DATETIME"))
                    logging.info(f"✅ Добавлен столбец {column}")
            
            logging.info("✅ Миграция базы данных завершена успешно")
            
        except Exception as e:
            logging.error(f"❌ Ошибка миграции БД: {e}")
            raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate_database())