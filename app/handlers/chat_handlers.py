from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select
import logging

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.config import config

from datetime import datetime

router = Router()


@router.callback_query(F.data.startswith("chat_"))
async def handle_chat_actions(callback: CallbackQuery):
    """Обработчик действий в чате"""
    try:
        logging.info(f"🔔 Chat action: {callback.data}")
        
        # Проверяем права
        if not await is_manager(callback.from_user.id):
            await callback.answer("❌ У вас нет прав для управления заявками", show_alert=True)
            return
        
        action_parts = callback.data.split(":")
        action = action_parts[0]
        request_id = int(action_parts[1])

        if action == "chat_accept":
            await accept_request(callback, request_id)
        elif action == "chat_reject":
            await reject_request(callback, request_id)
        elif action == "chat_in_progress":
            await set_in_progress(callback, request_id)
        elif action == "chat_complete":
            await complete_request(callback, request_id)

    except Exception as e:
        logging.error(f"❌ Ошибка обработки chat action: {e}")
        await callback.answer("❌ Произошла ошибка")


async def is_manager(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь менеджером"""
    return str(telegram_id) == config.ADMIN_USER_ID


async def accept_request(callback: CallbackQuery, request_id: int):
    """Принять заявку"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем заявку и пользователя
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            # Обновляем статус и время принятия
            request.status = 'accepted'
            request.accepted_at = datetime.now()  # ← ВАЖНО: добавляем время
            
            await session.commit()
            logging.info(f"✅ Заявка #{request_id} принята в {request.accepted_at}")

            # Уведомляем пользователя
            user_message = (
                "✅ <b>Ваша заявка принята!</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"📞 <b>Менеджер свяжется с вами для уточнения деталей.</b>"
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )

            await callback.answer("✅ Заявка принята")
            await update_chat_keyboard(callback.bot, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка принятия заявки: {e}")
            await callback.answer("❌ Ошибка")


async def reject_request(callback: CallbackQuery, request_id: int):
    """Отклонить заявку"""
    async with AsyncSessionLocal() as session:
        try:
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            # Обновляем статус и время отклонения
            request.status = 'rejected'
            request.rejected_at = datetime.now()  # ← ВАЖНО: добавляем время
            
            await session.commit()
            logging.info(f"❌ Заявка #{request_id} отклонена в {request.rejected_at}")

            # Уведомляем пользователя
            user_message = (
                "❌ <b>Ваша заявка отклонена</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"ℹ️ <b>Вы можете создать новую заявку.</b>"
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )

            await callback.answer("❌ Заявка отклонена")
            await update_chat_keyboard(callback.bot, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка отклонения заявки: {e}")
            await callback.answer("❌ Ошибка")


async def set_in_progress(callback: CallbackQuery, request_id: int):
    """Взять заявку в работу"""
    async with AsyncSessionLocal() as session:
        try:
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            # Обновляем статус и время взятия в работу
            request.status = 'in_progress'
            request.in_progress_at = datetime.now()  # ← ВАЖНО: добавляем время
            
            await session.commit()
            logging.info(f"⏳ Заявка #{request_id} взята в работу в {request.in_progress_at}")

            # Уведомляем пользователя
            user_message = (
                "⏳ <b>Ваша заявка переведена в работу!</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"🔧 <b>Мастер приступил к работе над вашей заявкой.</b>"
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )

            await callback.answer("✅ Заявка в работе")
            await update_chat_keyboard(callback.bot, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка взятия в работу: {e}")
            await callback.answer("❌ Ошибка")


async def complete_request(callback: CallbackQuery, request_id: int):
    """Завершить заявку"""
    async with AsyncSessionLocal() as session:
        try:
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            # Обновляем статус и время завершения
            request.status = 'completed'
            request.completed_at = datetime.now()  # ← ВАЖНО: добавляем время
            
            await session.commit()
            logging.info(f"🏁 Заявка #{request_id} завершена в {request.completed_at}")

            # Уведомляем пользователя
            user_message = (
                "✅ <b>Ваша заявка завершена!</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"🏁 <b>Работа по вашей заявке успешно завершена.</b>\n"
                f"Благодарим за обращение!"
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )

            await callback.answer("✅ Заявка завершена")
            await update_chat_keyboard(callback.bot, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка завершения заявки: {e}")
            await callback.answer("❌ Ошибка")


async def update_chat_keyboard(bot: Bot, request_id: int):
    """Обновляет клавиатуру в чате заявки"""
    try:
        async with AsyncSessionLocal() as session:
            # Получаем текущий статус заявки
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()
            
            if not request or not request.chat_message_id:
                return

            # Создаем клавиатуру в зависимости от статуса
            builder = InlineKeyboardBuilder()
            
            if request.status == 'new':
                builder.row(
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"chat_accept:{request_id}"),
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request_id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request_id}")
                )
            elif request.status == 'accepted':
                builder.row(
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request_id}")
                )
            elif request.status == 'in_progress':
                builder.row(
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"chat_complete:{request_id}"),
                )
            # Для завершенных и отклоненных заявок убираем кнопки

            # Обновляем сообщение в группе
            await bot.edit_message_reply_markup(
                chat_id=config.MANAGER_CHAT_ID,
                message_id=request.chat_message_id,
                reply_markup=builder.as_markup()
            )

    except Exception as e:
        logging.error(f"❌ Ошибка обновления клавиатуры: {e}")