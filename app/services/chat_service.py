import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, Car


def _format_status(status: Optional[str]) -> str:
    status = status or "new"
    mapping = {
        "new": "🆕 Новая",
        "accepted": "✅ Принята клиентом",
        "in_progress": "⏳ В работе",
        "completed": "✅ Завершена",
        "rejected": "❌ Отклонена",
        "to_pay": "💰 К оплате",
    }
    return mapping.get(status, status)


def _build_chat_keyboard(request: Request) -> InlineKeyboardMarkup:
    """
    Формирует inline-клавиатуру под сообщение в группе менеджеров
    в зависимости от текущего статуса заявки.
    """
    kb = InlineKeyboardBuilder()
    rid = request.id

    status = request.status or "new"

    if status == "new":
        # Только комментарий, отправка условий клиенту и обновление
        kb.button(
            text="💬 Комментарий",
            callback_data=f"manager_comment:{rid}",
        )
        kb.button(
            text="📩 Отправить условия клиенту",
            callback_data=f"manager_send_offer:{rid}",
        )
        kb.button(
            text="🔄 Обновить",
            callback_data=f"manager_view_request:{rid}",
        )
        kb.adjust(1, 1, 1)

    elif status == "accepted":
        # Клиент подтвердил условия – менеджер может взять в работу
        kb.button(
            text="⏳ В работу",
            callback_data=f"chat_in_progress:{rid}",
        )
        kb.button(
            text="💬 Комментарий",
            callback_data=f"manager_comment:{rid}",
        )
        kb.button(
            text="🔄 Обновить",
            callback_data=f"manager_view_request:{rid}",
        )
        kb.adjust(1, 1, 1)

    elif status == "in_progress":
        kb.button(
            text="✅ Завершить",
            callback_data=f"chat_complete:{rid}",
        )
        kb.button(
            text="💬 Комментарий",
            callback_data=f"manager_comment:{rid}",
        )
        kb.button(
            text="🔄 Обновить",
            callback_data=f"manager_view_request:{rid}",
        )
        kb.adjust(1, 1, 1)

    else:
        # Для отклонённых/завершённых – только обновление
        kb.button(
            text="🔄 Обновить",
            callback_data=f"manager_view_request:{rid}",
        )
        kb.adjust(1)

    return kb.as_markup()


def _format_request_text(request: Request, user: User, car: Optional[Car]) -> str:
    car_block = "🚗 Автомобиль: не указан"

    if car:
        car_block = (
            "🚗 Автомобиль:\n"
            f"   • Марка: {car.brand}\n"
            f"   • Модель: {car.model}\n"
            f"   • Год: {car.year}\n"
            f"   • Госномер: {car.license_plate}"
        )

    created_at = request.created_at.strftime("%d.%m.%Y %H:%M") if request.created_at else "неизвестно"

    text = (
        f"📋 Заявка #{request.id}\n\n"
        f"👤 Клиент: {user.full_name or 'Не указано'}\n"
        f"📞 Телефон: {user.phone_number or 'Не указан'}\n"
        f"🆔 ID пользователя: {user.telegram_id}\n\n"
        f"{car_block}\n\n"
        f"🛠️ Услуга: {request.service_type}\n\n"
        f"📝 Описание:\n{request.description}\n\n"
        f"📊 Статус: {_format_status(request.status)}\n"
        f"⏰ Создана: {created_at}\n\n"
        "ℹ️ Чтобы оставить комментарий, ответьте на это сообщение (Reply)\n"
        "или используйте кнопку ниже."
    )

    if request.manager_comment:
        text += f"\n\n💬 Комментарий менеджера:\n{request.manager_comment}"

    return text


async def create_request_chat(bot: Bot, request_id: int) -> None:
    """Создать/отправить сообщение о заявке в группу менеджеров."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id, isouter=True)
                .where(Request.id == request_id)
            )
            row = result.first()

            if not row:
                logging.error(f"❌ create_request_chat: заявка #{request_id} не найдена")
                return

            request, user, car = row

            if not config.MANAGER_CHAT_ID:
                logging.error("❌ MANAGER_CHAT_ID не задан в конфиге/ENV")
                return

            try:
                chat_id = int(config.MANAGER_CHAT_ID)
            except ValueError:
                logging.error(f"❌ Некорректный MANAGER_CHAT_ID: {config.MANAGER_CHAT_ID}")
                return

            text = _format_request_text(request, user, car)
            keyboard = _build_chat_keyboard(request)

            message = None

            # Берём первое фото, если в строке несколько file_id через запятую
            file_id = None
            if request.photo_file_id:
                file_id = request.photo_file_id.split(",")[0].strip() or None

            if file_id:
                # Пытаемся отправить как фото, если не получится — просто текст
                try:
                    message = await bot.send_photo(
                        chat_id=chat_id,
                        photo=file_id,
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logging.error(f"❌ Ошибка отправки фото в чат менеджеров для заявки #{request_id}: {e}")

            if message is None:
                # Без фото / фото не отправилось
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )

            # Сохраняем ID сообщения чата, чтобы потом обновлять клавиатуру
            request.chat_message_id = message.message_id
            await session.commit()
            logging.info(f"✅ Чат для заявки #{request_id} создан и сообщение отправлено (msg_id={message.message_id})")

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка создания чата для заявки #{request_id}: {e}")


async def update_chat_keyboard(bot: Bot, request_id: int) -> None:
    """Обновить inline-клавиатуру под сообщением заявки в группе менеджеров."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                logging.error(f"❌ update_chat_keyboard: заявка #{request_id} не найдена")
                return

            if not request.chat_message_id:
                logging.warning(
                    f"⚠️ update_chat_keyboard: у заявки #{request_id} нет chat_message_id, нечего обновлять"
                )
                return

            if not config.MANAGER_CHAT_ID:
                logging.error("❌ MANAGER_CHAT_ID не задан в конфиге/ENV")
                return

            try:
                chat_id = int(config.MANAGER_CHAT_ID)
            except ValueError:
                logging.error(f"❌ Некорректный MANAGER_CHAT_ID: {config.MANAGER_CHAT_ID}")
                return

            keyboard = _build_chat_keyboard(request)

            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=request.chat_message_id,
                    reply_markup=keyboard,
                )
                logging.info(f"🔧 update_chat_keyboard #{request_id}, status={request.status}")
            except Exception as e:
                # Игнорируем ситуацию "message is not modified"
                if "message is not modified" in str(e):
                    logging.info(
                        f"ℹ️ Клавиатура для заявки #{request_id} уже актуальна, Telegram вернул 'message is not modified'"
                    )
                else:
                    logging.error(
                        f"❌ Не удалось обновить клавиатуру чата для заявки #{request_id}: {e}"
                    )

        except Exception as e:
            logging.error(f"❌ Ошибка в update_chat_keyboard для заявки #{request_id}: {e}")
