import logging
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Request, User, Car
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import get_manager_request_kb
from app.config import config


async def notify_manager_about_new_request(bot: Bot, request_id: int):
    if not config.MANAGER_CHAT_ID:
        logging.warning("MANAGER_CHAT_ID не установлен - уведомление не отправлено")
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

            # Формируем сообщение для менеджера
            message_text = (
                "🆕 <b>НОВАЯ ЗАЯВКА</b>\n\n"
                f"📋 <b>№{request.id}</b>\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n"
                f"📞 <b>Телефон:</b> {user.phone_number or 'Не указан'}\n"
                f"🚗 <b>Автомобиль:</b> {car.brand} {car.model}\n"
                f"🗓️ <b>Год:</b> {car.year or 'Не указан'}\n"
                f"🚙 <b>Номер:</b> {car.license_plate or 'Не указан'}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n"
                f"📝 <b>Описание:</b> {request.description}\n"
                f"🗓️ <b>Желаемая дата:</b> {request.preferred_date}\n"
                f"⏰ <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            )

            # ОТПРАВЛЯЕМ В ГРУППУ С КНОПКАМИ
            try:
                if request.photo_file_id:
                    try:
                        # Пытаемся отправить как фото
                        await bot.send_photo(
                            chat_id=config.MANAGER_CHAT_ID,
                            photo=request.photo_file_id,
                            caption=message_text,
                            parse_mode="HTML",
                            reply_markup=get_manager_request_kb(request.id)
                        )
                    except Exception as photo_error:
                        # Если не фото, пробуем как видео
                        try:
                            await bot.send_video(
                                chat_id=config.MANAGER_CHAT_ID,
                                video=request.photo_file_id,
                                caption=message_text,
                                parse_mode="HTML",
                                reply_markup=get_manager_request_kb(request.id)
                            )
                        except Exception as video_error:
                            # Если и видео не получилось, отправляем только текст
                            logging.warning(f"Не удалось отправить медиа в группу: {photo_error}, {video_error}")
                            await bot.send_message(
                                chat_id=config.MANAGER_CHAT_ID,
                                text=message_text + f"\n\n📎 <b>Медиафайл:</b> Не удалось отобразить",
                                parse_mode="HTML",
                                reply_markup=get_manager_request_kb(request.id)
                            )
                else:
                    await bot.send_message(
                        chat_id=config.MANAGER_CHAT_ID,
                        text=message_text,
                        parse_mode="HTML",
                        reply_markup=get_manager_request_kb(request.id)
                    )
                
                logging.info(f"✅ Уведомление о заявке #{request_id} отправлено в группу")
                
            except Exception as group_error:
                logging.error(f"❌ Ошибка отправки в группу: {group_error}")
                
                # Пробуем отправить в личные сообщения как запасной вариант
                try:
                    if config.ADMIN_USER_ID:
                        await bot.send_message(
                            chat_id=config.ADMIN_USER_ID,
                            text=f"❌ Не удалось отправить в группу. Заявка #{request_id}\n\n{message_text}",
                            parse_mode="HTML",
                            reply_markup=get_manager_request_kb(request.id)
                        )
                        logging.info(f"✅ Уведомление о заявке #{request_id} отправлено в личные сообщения")
                except Exception as pm_error:
                    logging.error(f"❌ Ошибка отправки в личные сообщения: {pm_error}")

        except Exception as e:
            logging.error(f"❌ Общая ошибка при отправке уведомления: {e}")