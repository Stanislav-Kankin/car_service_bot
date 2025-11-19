from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
import logging

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.handlers.manager_handlers import is_manager

router = Router()


# Обработчик callback'ов из групп
@router.callback_query(F.data.startswith("manager_"))
async def handle_group_callbacks(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback'ов из групп"""
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
            
        elif callback.data.startswith("manager_call:"):
            request_id = int(callback.data.split(":")[1])
            await process_manager_call(callback, request_id)
            
        else:
            await callback.answer("⚠️ Действие не распознано")
            
    except Exception as e:
        logging.error(f"❌ Ошибка обработки callback из группы: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


async def process_manager_accept(callback: CallbackQuery, state: FSMContext):
    """Обработка принятия заявки из группы"""
    try:
        request_id = int(callback.data.split(":")[1])
        logging.info(f"🔔 Обработка принятия заявки #{request_id}")
        
        # Используем функцию из chat_handlers
        from app.handlers.chat_handlers import accept_request
        await accept_request(callback, request_id)
        
    except Exception as e:
        logging.error(f"❌ Ошибка в process_manager_accept: {e}")
        await callback.answer("❌ Ошибка при обработке")


async def process_manager_reject(callback: CallbackQuery, state: FSMContext):
    """Обработка отклонения заявки из группы"""
    try:
        request_id = int(callback.data.split(":")[1])
        logging.info(f"🔔 Обработка отклонения заявки #{request_id}")
        
        # Используем функцию из chat_handlers
        from app.handlers.chat_handlers import reject_request
        await reject_request(callback, request_id)
        
    except Exception as e:
        logging.error(f"❌ Ошибка в process_manager_reject: {e}")
        await callback.answer("❌ Ошибка при обработке")


async def process_manager_call(callback: CallbackQuery, request_id: int):
    """Обработка кнопки звонка из группы"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем данные заявки и пользователя
            request_result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            if not user.phone_number:
                await callback.answer("❌ У клиента не указан номер телефона")
                return
            
            # Показываем номер телефона
            call_message = (
                f"📞 <b>Контакт клиента</b>\n\n"
                f"📋 <b>Заявка:</b> #{request.id}\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n"
                f"📱 <b>Телефон:</b> {user.phone_number}\n\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}"
            )
            
            await callback.message.answer(
                call_message,
                parse_mode="HTML"
            )
            await callback.answer()
            
        except Exception as e:
            logging.error(f"Ошибка при получении контакта: {e}")
            await callback.answer("❌ Ошибка при получении контакта")
