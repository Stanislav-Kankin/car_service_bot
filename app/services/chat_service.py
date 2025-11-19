import logging
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select
from app.database.models import Request, User, Car
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

            # Формируем сообщение
            message_text = (
                "💬 <b>ЗАЯВКА #{}</b>\n\n"
                "👤 <b>Клиент:</b> {}\n"
                "📞 <b>Телефон:</b> {}\n"
                "🚗 <b>Автомобиль:</b> {} {}\n"
                "🛠️ <b>Услуга:</b> {}\n"
                "📝 <b>Описание:</b> {}\n"
                "📊 <b>Статус:</b> {}"
            ).format(
                request.id,
                user.full_name,
                user.phone_number or 'Не указан',
                car.brand, car.model,
                request.service_type,
                request.description,
                "🆕 Новая" if request.status == 'new' else 
                "✅ Принята" if request.status == 'accepted' else
                "⏳ В работе" if request.status == 'in_progress' else
                "✅ Завершена" if request.status == 'completed' else
                "❌ Отклонена"
            )

            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()
            
            if request.status == 'new':
                builder.row(
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"chat_accept:{request.id}"),
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request.id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request.id}")
                )
            elif request.status == 'accepted':
                builder.row(
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request.id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request.id}")
                )
            elif request.status == 'in_progress':
                builder.row(
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"chat_complete:{request.id}"),
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