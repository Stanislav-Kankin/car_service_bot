import logging
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select
from app.database.models import Request, User, Car
from app.database.comment_models import Comment
from app.database.db import AsyncSessionLocal
from app.config import config


async def create_request_chat(bot: Bot, request_id: int):
    """Создает чат для обсуждения заявки"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем данные заявки
            request_result = await session.execute(
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
                .where(Request.id == request_id)
            )
            result = request_result.first()

            if not result:
                logging.error(f"Заявка #{request_id} не найдена")
                return

            request, user, car = result

            # Формируем сообщение с кнопками управления
            message_text = (
                "💬 <b>ЧАТ ПО ЗАЯВКЕ #{}</b>\n\n"
                "👤 <b>Клиент:</b> {}\n"
                "📞 <b>Телефон:</b> {}\n"
                "🚗 <b>Автомобиль:</b> {} {}\n"
                "🛠️ <b>Услуга:</b> {}\n"
                "📝 <b>Описание:</b> {}\n"
                "📊 <b>Статус:</b> {}\n\n"
                "💭 <i>Отправляйте сообщения в этот чат для общения с клиентом</i>"
            ).format(
                request.id,
                user.full_name,
                user.phone_number or 'Не указан',
                car.brand, car.model,
                request.service_type,
                request.description,
                "🆕 Новая" if request.status == 'new' else "✅ Принята"
            )

            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="✅ Принять заявку", callback_data=f"chat_accept:{request.id}"),
                InlineKeyboardButton(text="💰 Указать стоимость", callback_data=f"chat_price:{request.id}")
            )
            builder.row(
                InlineKeyboardButton(text="❓ Задать вопрос", callback_data=f"chat_question:{request.id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request.id}")
            )
            builder.row(
                InlineKeyboardButton(text="⏳ Взять в работу", callback_data=f"chat_in_progress:{request.id}"),
                InlineKeyboardButton(text="✅ Завершить", callback_data=f"chat_complete:{request.id}")
            )

            # Отправляем в группу
            if request.photo_file_id:
                try:
                    message = await bot.send_photo(
                        chat_id=config.MANAGER_CHAT_ID,
                        photo=request.photo_file_id,
                        caption=message_text,
                        parse_mode="HTML",
                        reply_markup=builder.as_markup()
                    )
                except:
                    message = await bot.send_video(
                        chat_id=config.MANAGER_CHAT_ID,
                        video=request.photo_file_id,
                        caption=message_text,
                        parse_mode="HTML",
                        reply_markup=builder.as_markup()
                    )
            else:
                message = await bot.send_message(
                    chat_id=config.MANAGER_CHAT_ID,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )

            # Сохраняем ID сообщения чата
            request.chat_message_id = message.message_id
            await session.commit()

            logging.info(f"✅ Чат для заявки #{request_id} создан")

        except Exception as e:
            logging.error(f"❌ Ошибка создания чата: {e}")


async def add_message_to_chat(bot: Bot, request_id: int, user_name: str, message: str, is_manager: bool = False):
    """Добавляет сообщение в чат заявки"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем заявку
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()

            if not request or not request.chat_message_id:
                logging.error(f"Чат для заявки #{request_id} не найден")
                return

            # Формируем сообщение
            sender = "👨‍💼 Менеджер" if is_manager else "👤 Клиент"
            message_text = f"{sender} <b>{user_name}:</b>\n{message}"

            # Отправляем в чат
            await bot.send_message(
                chat_id=config.MANAGER_CHAT_ID,
                text=message_text,
                parse_mode="HTML",
                reply_to_message_id=request.chat_message_id
            )

            # Сохраняем в комментарии
            from app.services.comment_service import add_comment
            
            # Получаем ID пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == (config.ADMIN_USER_ID if is_manager else request.user_id))
            )
            user = user_result.scalar_one_or_none()

            if user:
                await add_comment(request_id, user.id, message, is_manager)

            logging.info(f"✅ Сообщение добавлено в чат заявки #{request_id}")

        except Exception as e:
            logging.error(f"❌ Ошибка добавления сообщения в чат: {e}")