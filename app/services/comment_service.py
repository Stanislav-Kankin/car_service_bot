import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Request, User
from app.database.comment_models import Comment
from app.database.db import AsyncSessionLocal


async def add_comment(request_id: int, user_id: int, message: str, is_manager: bool = False):
    """Добавляет комментарий к заявке"""
    async with AsyncSessionLocal() as session:
        try:
            comment = Comment(
                request_id=request_id,
                user_id=user_id,
                message=message,
                is_manager=is_manager
            )
            session.add(comment)
            await session.commit()
            logging.info(f"✅ Комментарий добавлен к заявке #{request_id}")
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка добавления комментария: {e}")
            return False


async def get_comments(request_id: int):
    """Получает все комментарии заявки"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Comment, User)
                .join(User, Comment.user_id == User.id)
                .where(Comment.request_id == request_id)
                .order_by(Comment.created_at.asc())
            )
            return result.all()
        except Exception as e:
            logging.error(f"❌ Ошибка получения комментариев: {e}")
            return []