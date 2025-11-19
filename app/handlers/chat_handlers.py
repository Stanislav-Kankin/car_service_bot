from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select
import logging

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.services.chat_service import add_message_to_chat
from app.config import config

router = Router()


class ChatForm(StatesGroup):
    waiting_for_price = State()
    waiting_for_question = State()
    waiting_for_reject_reason = State()
    waiting_for_comment = State()


@router.callback_query(F.data.startswith("chat_"))
async def handle_chat_actions(callback: CallbackQuery, state: FSMContext):
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
        elif action == "chat_price":
            await ask_price(callback, state, request_id)
        elif action == "chat_question":
            await ask_question(callback, state, request_id)
        elif action == "chat_reject":
            await reject_request(callback, state, request_id)
        elif action == "chat_in_progress":
            await set_in_progress(callback, request_id)
        elif action == "chat_complete":
            await complete_request(callback, request_id)
        elif action == "chat_comment":
            await add_comment(callback, state, request_id)

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
            
            # Обновляем статус
            request.status = 'accepted'
            await session.commit()

            # Добавляем сообщение в чат
            await add_message_to_chat(
                callback.bot, 
                request_id, 
                "Менеджер", 
                "✅ Заявка принята в работу", 
                True
            )

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
            
            # Обновляем клавиатуру в чате
            await update_chat_keyboard(callback, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка принятия заявки: {e}")
            await callback.answer("❌ Ошибка")


async def ask_price(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Запросить стоимость"""
    await state.update_data(request_id=request_id)
    await state.set_state(ChatForm.waiting_for_price)
    
    await callback.message.answer(
        f"💰 <b>Укажите стоимость для заявки #{request_id}</b>\n\n"
        "Введите сумму и описание:\n\n"
        "<i>Пример: 5000 руб - замена масла и фильтров</i>",
        parse_mode="HTML"
    )
    await callback.answer("💬 Введите стоимость")


@router.message(ChatForm.waiting_for_price)
async def process_chat_price(message: Message, state: FSMContext):
    """Обработать ввод стоимости"""
    try:
        price = message.text.strip()
        user_data = await state.get_data()
        request_id = user_data['request_id']

        # Добавляем сообщение в чат
        await add_message_to_chat(
            message.bot, 
            request_id, 
            "Менеджер", 
            f"💰 <b>Ориентировочная стоимость:</b>\n{price}", 
            True
        )

        await message.answer("✅ Стоимость добавлена в чат")
        
        # Обновляем клавиатуру в чате
        await update_request_status(message.bot, request_id, 'accepted')
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки стоимости: {e}")
        await message.answer("❌ Ошибка при добавлении стоимости")
    finally:
        await state.clear()


async def ask_question(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Задать вопрос клиенту"""
    await state.update_data(request_id=request_id)
    await state.set_state(ChatForm.waiting_for_question)
    
    await callback.message.answer(
        f"❓ <b>Задайте вопрос по заявке #{request_id}</b>\n\n"
        "Введите ваш вопрос:",
        parse_mode="HTML"
    )
    await callback.answer("💬 Введите вопрос")


@router.message(ChatForm.waiting_for_question)
async def process_chat_question(message: Message, state: FSMContext):
    """Обработать ввод вопроса"""
    try:
        question = message.text.strip()
        user_data = await state.get_data()
        request_id = user_data['request_id']

        # Добавляем сообщение в чат
        await add_message_to_chat(
            message.bot, 
            request_id, 
            "Менеджер", 
            f"❓ <b>Вопрос от менеджера:</b>\n{question}", 
            True
        )

        # Отправляем вопрос пользователю
        async with AsyncSessionLocal() as session:
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if result:
                request, user = result
                user_message = (
                    "❓ <b>Уточнение по вашей заявке</b>\n\n"
                    f"📋 <b>Номер заявки:</b> #{request.id}\n"
                    f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                    f"💬 <b>Менеджер уточняет:</b>\n{question}\n\n"
                    f"📝 <b>Пожалуйста, ответьте на этот вопрос.</b>"
                )
                
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=user_message,
                    parse_mode="HTML"
                )

        await message.answer("✅ Вопрос отправлен клиенту")
        
    except Exception as e:
        logging.error(f"❌ Ошибка обработки вопроса: {e}")
        await message.answer("❌ Ошибка при отправке вопроса")
    finally:
        await state.clear()


async def reject_request(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Отклонить заявку"""
    await state.update_data(request_id=request_id)
    await state.set_state(ChatForm.waiting_for_reject_reason)
    
    await callback.message.answer(
        f"❌ <b>Отклонение заявки #{request_id}</b>\n\n"
        "Укажите причину отклонения:\n\n"
        "<i>Пример: Нет запчастей, не обслуживаем эту марку</i>",
        parse_mode="HTML"
    )
    await callback.answer("💬 Укажите причину")


@router.message(ChatForm.waiting_for_reject_reason)
async def process_chat_reject(message: Message, state: FSMContext):
    """Обработать причину отклонения"""
    try:
        reason = message.text.strip()
        user_data = await state.get_data()
        request_id = user_data['request_id']

        async with AsyncSessionLocal() as session:
            # Обновляем статус
            request_result = await session.execute(
                select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await message.answer("❌ Заявка не найдена")
                await state.clear()
                return
            
            request, user = result
            
            request.status = 'rejected'
            await session.commit()

            # Добавляем сообщение в чат
            await add_message_to_chat(
                message.bot, 
                request_id, 
                "Менеджер", 
                f"❌ <b>Заявка отклонена:</b>\n{reason}", 
                True
            )

            # Уведомляем пользователя
            user_message = (
                "❌ <b>Ваша заявка отклонена</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"📝 <b>Причина:</b> {reason}\n\n"
                f"ℹ️ <b>Вы можете создать новую заявку с учетом замечаний.</b>"
            )
            
            await message.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )

        await message.answer("✅ Заявка отклонена")
        
        # Обновляем клавиатуру в чате
        await update_chat_keyboard(message, request_id)
        
    except Exception as e:
        logging.error(f"❌ Ошибка отклонения заявки: {e}")
        await message.answer("❌ Ошибка при отклонении заявки")
    finally:
        await state.clear()


async def set_in_progress(callback: CallbackQuery, request_id: int):
    """Взять заявку в работу"""
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
            
            # Обновляем статус
            request.status = 'in_progress'
            await session.commit()

            # Добавляем сообщение в чат
            await add_message_to_chat(
                callback.bot, 
                request_id, 
                "Менеджер", 
                "⏳ Заявка взята в работу", 
                True
            )

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
            
            # Обновляем клавиатуру в чате
            await update_chat_keyboard(callback, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка взятия в работу: {e}")
            await callback.answer("❌ Ошибка")


async def complete_request(callback: CallbackQuery, request_id: int):
    """Завершить заявку"""
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
            
            # Обновляем статус
            request.status = 'completed'
            await session.commit()

            # Добавляем сообщение в чат
            await add_message_to_chat(
                callback.bot, 
                request_id, 
                "Менеджер", 
                "✅ Заявка завершена", 
                True
            )

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
            
            # Обновляем клавиатуру в чате
            await update_chat_keyboard(callback, request_id)

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка завершения заявки: {e}")
            await callback.answer("❌ Ошибка")


async def add_comment(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Добавить комментарий"""
    await state.update_data(request_id=request_id)
    await state.set_state(ChatForm.waiting_for_comment)
    
    await callback.message.answer(
        f"💬 <b>Добавление комментария к заявке #{request_id}</b>\n\n"
        "Введите комментарий:",
        parse_mode="HTML"
    )
    await callback.answer("💬 Введите комментарий")


@router.message(ChatForm.waiting_for_comment)
async def process_chat_comment(message: Message, state: FSMContext):
    """Обработать ввод комментария"""
    try:
        comment = message.text.strip()
        user_data = await state.get_data()
        request_id = user_data['request_id']

        # Добавляем сообщение в чат
        await add_message_to_chat(
            message.bot, 
            request_id, 
            "Менеджер", 
            f"💬 <b>Комментарий менеджера:</b>\n{comment}", 
            True
        )

        await message.answer("✅ Комментарий добавлен в чат")
        
    except Exception as e:
        logging.error(f"❌ Ошибка добавления комментария: {e}")
        await message.answer("❌ Ошибка при добавлении комментария")
    finally:
        await state.clear()


async def update_chat_keyboard(update, request_id: int):
    """Обновляет клавиатуру в чате заявки"""
    try:
        if isinstance(update, CallbackQuery):
            bot = update.bot
            message = update.message
        else:
            bot = update.bot
            message = update

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
                    InlineKeyboardButton(text="💰 Стоимость", callback_data=f"chat_price:{request_id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❓ Вопрос", callback_data=f"chat_question:{request_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request_id}")
                )
            elif request.status == 'accepted':
                builder.row(
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request_id}"),
                    InlineKeyboardButton(text="💰 Стоимость", callback_data=f"chat_price:{request_id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❓ Вопрос", callback_data=f"chat_question:{request_id}"),
                    InlineKeyboardButton(text="💬 Комментарий", callback_data=f"chat_comment:{request_id}")
                )
            elif request.status == 'in_progress':
                builder.row(
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"chat_complete:{request_id}"),
                    InlineKeyboardButton(text="💰 Стоимость", callback_data=f"chat_price:{request_id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❓ Вопрос", callback_data=f"chat_question:{request_id}"),
                    InlineKeyboardButton(text="💬 Комментарий", callback_data=f"chat_comment:{request_id}")
                )
            else:  # completed or rejected
                builder.row(
                    InlineKeyboardButton(text="💬 Комментарий", callback_data=f"chat_comment:{request_id}"),
                    InlineKeyboardButton(text="📊 Статус", callback_data=f"chat_status:{request_id}")
                )

            # Обновляем сообщение в группе
            await bot.edit_message_reply_markup(
                chat_id=config.MANAGER_CHAT_ID,
                message_id=request.chat_message_id,
                reply_markup=builder.as_markup()
            )

    except Exception as e:
        logging.error(f"❌ Ошибка обновления клавиатуры: {e}")


async def update_request_status(bot: Bot, request_id: int, status: str):
    """Обновляет статус заявки и клавиатуру"""
    async with AsyncSessionLocal() as session:
        try:
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()
            
            if request:
                request.status = status
                await session.commit()
                await update_chat_keyboard(bot, request_id)
                
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка обновления статуса: {e}")