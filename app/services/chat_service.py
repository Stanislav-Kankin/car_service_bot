import logging
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select

from app.database.models import Request, User, Car
from app.database.db import AsyncSessionLocal
from app.config import config


async def create_request_chat(bot: Bot, request_id: int):
    """Создает сообщение в менеджерской группе для обсуждения заявки"""

    # Страховка по chat_id, чтобы не было chat_id=None
    chat_id = config.MANAGER_CHAT_ID
    if not chat_id:
        logging.error(
            "❌ MANAGER_CHAT_ID не настроен (None/0). "
            "Заявка не может быть отправлена в менеджерскую группу."
        )
        return

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

            # Формируем текст сообщения
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
                user.phone_number or "Не указан",
                car.brand,
                car.model,
                request.service_type,
                request.description,
                "🆕 Новая"
                if request.status == "new"
                else "✅ Принята"
                if request.status == "accepted"
                else "⏳ В работе"
                if request.status == "in_progress"
                else "✅ Завершена"
                if request.status == "completed"
                else "❌ Отклонена",
            )

            # Создаем инлайн-клавиатуру для менеджера
            builder = InlineKeyboardBuilder()

            if request.status == "new":
                builder.row(
                    InlineKeyboardButton(
                        text="✅ Принять",
                        callback_data=f"chat_accept:{request.id}",
                    ),
                    InlineKeyboardButton(
                        text="⏳ В работу",
                        callback_data=f"chat_in_progress:{request.id}",
                    ),
                )
                builder.row(
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"chat_reject:{request.id}",
                    )
                )
            elif request.status == "accepted":
                builder.row(
                    InlineKeyboardButton(
                        text="⏳ В работу",
                        callback_data=f"chat_in_progress:{request.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"chat_reject:{request.id}",
                    ),
                )
            elif request.status == "in_progress":
                builder.row(
                    InlineKeyboardButton(
                        text="✅ Завершить",
                        callback_data=f"chat_complete:{request.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"chat_reject:{request.id}",
                    ),
                )
            elif request.status == "completed":
                builder.row(
                    InlineKeyboardButton(
                        text="📁 В архив",
                        callback_data=f"chat_archive:{request.id}",
                    )
                )
            else:
                builder.row(
                    InlineKeyboardButton(
                        text="📁 В архив",
                        callback_data=f"chat_archive:{request.id}",
                    )
                )

            # Отправка в группу: с фото / видео / просто текст
            message = None
            if request.photo_file_id:
                # Пытаемся как фото
                try:
                    message = await bot.send_photo(
                        chat_id=chat_id,
                        photo=request.photo_file_id,
                        caption=message_text,
                        parse_mode="HTML",
                        reply_markup=builder.as_markup(),
                    )
                except Exception as e_photo:
                    logging.warning(
                        f"⚠️ Не удалось отправить как фото, пробую как видео: {e_photo}"
                    )
                    # Пытаемся как видео
                    try:
                        message = await bot.send_video(
                            chat_id=chat_id,
                            video=request.photo_file_id,
                            caption=message_text,
                            parse_mode="HTML",
                            reply_markup=builder.as_markup(),
                        )
                    except Exception as e_video:
                        logging.warning(
                            f"⚠️ Не удалось отправить как видео, пробую как текст: {e_video}"
                        )
                        message = await bot.send_message(
                            chat_id=chat_id,
                            text=message_text,
                            parse_mode="HTML",
                            reply_markup=builder.as_markup(),
                        )
            else:
                # Без медиа — просто текст
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup(),
                )

            # Если по какой-то причине message так и не создалось — не падаем с AttributeError
            if not message:
                logging.error(
                    f"❌ Не удалось отправить сообщение в группу для заявки #{request_id}"
                )
                return

            # Сохраняем ID сообщения в заявке
            request.chat_message_id = message.message_id
            await session.commit()

            logging.info(f"✅ Чат для заявки #{request_id} создан и сообщение отправлено")

        except Exception as e:
            logging.error(f"❌ Ошибка создания чата: {e}")
