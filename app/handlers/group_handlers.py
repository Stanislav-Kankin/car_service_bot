from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
import logging

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.handlers.manager_handlers import is_manager
from app.config import config

router = Router()


# Обработчик callback'ов из МЕНЕДЖЕРСКОЙ ГРУППЫ
@router.callback_query(F.chat.id == config.MANAGER_CHAT_ID, F.data.startswith("manager_"))
async def handle_group_callbacks(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback'ов из группы менеджеров"""
    try:
        logging.info(f"🔔 Callback из группы: {callback.data} от пользователя {callback.from_user.id}")
        
        # Проверяем права пользователя
        if not await is_manager(callback.from_user.id):
            await callback.answer("❌ У вас нет прав для управления заявками", show_alert=True)
            return
        
        # Обрабатываем разные типы callback'ов
        if callback.data.startswith("manager_accept:"):
            await process_manager_accept(callback, state)
            
        elif callback.data.startswith("manager_reject:"):
            await process_manager_reject(callback, state)
            
        elif callback.data.startswith("manager_comment:"):
            await process_manager_comment(callback, state)
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки callback из группы: {e}")
        await callback.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=True)


async def process_manager_accept(callback: CallbackQuery, state: FSMContext):
    """Обработка принятия заявки менеджером"""
    try:
        _, request_id_str = callback.data.split(":")
        request_id = int(request_id_str)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = result.scalar_one_or_none()
            
            if not request:
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            
            request.status = "accepted"
            await session.commit()
        
        await callback.answer("Заявка принята")
        
    except Exception as e:
        logging.error(f"❌ Ошибка при принятии заявки: {e}")
        await callback.answer("Не удалось принять заявку", show_alert=True)


async def process_manager_reject(callback: CallbackQuery, state: FSMContext):
    """Обработка отклонения заявки менеджером"""
    try:
        _, request_id_str = callback.data.split(":")
        request_id = int(request_id_str)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = result.scalar_one_or_none()
            
            if not request:
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            
            request.status = "rejected"
            await session.commit()
        
        await callback.answer("Заявка отклонена")
        
    except Exception as e:
        logging.error(f"❌ Ошибка при отклонении заявки: {e}")
        await callback.answer("Не удалось отклонить заявку", show_alert=True)


async def process_manager_comment(callback: CallbackQuery, state: FSMContext):
    """Обработка комментария менеджера к заявке"""
    try:
        _, request_id_str = callback.data.split(":")
        request_id = int(request_id_str)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            
            request, user = row
            
            # Здесь можно реализовать логику запроса комментария от менеджера
            await callback.answer("Функция комментариев пока не реализована", show_alert=True)
        
    except Exception as e:
        logging.error(f"❌ Ошибка при обработке комментария: {e}")
        await callback.answer("Не удалось обработать комментарий", show_alert=True)
