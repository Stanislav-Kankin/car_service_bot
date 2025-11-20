import logging
from datetime import datetime
from typing import Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.services.chat_service import update_chat_keyboard


router = Router()


def _is_manager(telegram_id: int) -> bool:
    """Пока считаем менеджером только ADMIN_USER_ID из .env"""
    try:
        return int(config.ADMIN_USER_ID) == int(telegram_id)
    except Exception:
        return False


async def _load_request_with_user(session, request_id: int) -> Optional[tuple[Request, User]]:
    result = await session.execute(
        select(Request, User).join(User, Request.user_id == User.id).where(Request.id == request_id)
    )
    row = result.first()
    if not row:
        return None
    return row[0], row[1]


@router.callback_query(F.data.startswith("chat_"))
async def handle_chat_actions(callback: CallbackQuery):
    """Общий вход для всех callback из сообщения в группе менеджеров (chat_...)."""
    data = callback.data
    logging.info(f"🔔 Chat action: {data}")

    # Проверяем права
    if not _is_manager(callback.from_user.id):
        logging.info(
            f"[is_manager] NO ACCESS telegram_id={callback.from_user.id}, ADMIN_USER_ID={config.ADMIN_USER_ID}"
        )
        await callback.answer("❌ Недостаточно прав для изменения заявки", show_alert=True)
        return

    # data вида 'chat_in_progress:17'
    try:
        action, rid_str = data.split(":", 1)
        action = action.replace("chat_", "")
        request_id = int(rid_str)
    except Exception:
        await callback.answer("❌ Неверные данные callback", show_alert=True)
        return

    if action == "in_progress":
        await set_in_progress(callback, request_id)
    elif action == "complete":
        await complete_request(callback, request_id)
    elif action == "reject":
        await reject_request(callback, request_id)
    elif action == "accept":
        # На всякий случай заглушка — принять должен клиент, не чат
        await callback.answer(
            "ℹ️ Подтверждение условий выполняется только со стороны клиента в боте.",
            show_alert=True,
        )
    else:
        logging.warning(f"⚠️ Неизвестное действие chat_*: {action}")
        await callback.answer("❌ Неизвестное действие", show_alert=True)


async def set_in_progress(callback: CallbackQuery, request_id: int):
    """Взять заявку в работу (статус in_progress)."""
    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data
            current_status = request.status or "new"
            logging.info(f"✅ set_in_progress #{request_id}, current_status={current_status}")

            # запрещаем для отклоненных/завершенных
            if current_status in ("rejected", "completed"):
                await callback.answer(
                    "❌ Нельзя взять в работу завершённую или отклонённую заявку",
                    show_alert=True,
                )
                return

            # В работу можно только после того, как клиент подтвердил условия
            if current_status != "accepted":
                await callback.answer(
                    "❌ Заявку можно взять в работу только после подтверждения клиентом",
                    show_alert=True,
                )
                return

            request.status = "in_progress"
            request.in_progress_at = datetime.now()
            await session.commit()
            logging.info(f"⏳ Заявка #{request_id} взята в работу в {request.in_progress_at}")

            # Сообщение клиенту о начале работ + кнопка связаться с менеджером
            try:
                manager_name = (
                    callback.from_user.full_name
                    or callback.from_user.username
                    or "Менеджер"
                )
                manager_mention = (
                    f" (@{callback.from_user.username})"
                    if callback.from_user.username
                    else ""
                )

                from aiogram.utils.keyboard import InlineKeyboardBuilder

                user_message = (
                    "🔧 <b>Ваша заявка принята в работу!</b>\n\n"
                    f"📋 <b>Номер заявки:</b> #{request.id}\n"
                    f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                    f"👨‍🔧 <b>Ваш менеджер:</b> {manager_name}{manager_mention}\n"
                    "Можете связаться с ним в Telegram при необходимости."
                )

                kb = InlineKeyboardBuilder()

                if callback.from_user.username:
                    kb.button(
                        text="💬 Связаться с менеджером",
                        url=f"https://t.me/{callback.from_user.username}",
                    )
                else:
                    kb.button(
                        text="💬 Связаться с менеджером",
                        url=f"tg://user?id={callback.from_user.id}",
                    )

                kb.adjust(1)

                await callback.bot.send_message(
                    chat_id=user.telegram_id,
                    text=user_message,
                    parse_mode="HTML",
                    reply_markup=kb.as_markup(),
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить сообщение пользователю о начале работ по заявке #{request_id}: {send_err}"
                )

            await update_chat_keyboard(callback.bot, request_id)
            await callback.answer("✅ Заявка в работе")

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка перевода заявки #{request_id} в работу: {e}")
            await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)


async def complete_request(callback: CallbackQuery, request_id: int):
    """Завершить заявку (completed)."""
    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data
            current_status = request.status or "new"
            logging.info(f"✅ complete_request #{request_id}, current_status={current_status}")

            if current_status in ("rejected", "completed"):
                await callback.answer(
                    "❌ Заявка уже завершена или отклонена",
                    show_alert=True,
                )
                return

            if current_status != "in_progress":
                await callback.answer(
                    "❌ Завершить можно только заявку, находящуюся в работе",
                    show_alert=True,
                )
                return

            request.status = "completed"
            request.completed_at = datetime.now()
            await session.commit()
            logging.info(f"✅ Заявка #{request_id} завершена в {request.completed_at}")

            # Уведомляем пользователя
            try:
                await callback.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "✅ <b>Работы по вашей заявке завершены.</b>\n\n"
                        f"📋 <b>Номер заявки:</b> #{request.id}\n"
                        f"🛠️ <b>Услуга:</b> {request.service_type}"
                    ),
                    parse_mode="HTML",
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить сообщение пользователю о завершении заявки #{request_id}: {send_err}"
                )

            await update_chat_keyboard(callback.bot, request_id)
            await callback.answer("✅ Заявка завершена")

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка завершения заявки #{request_id}: {e}")
            await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)


async def reject_request(callback: CallbackQuery, request_id: int):
    """Отклонить заявку (rejected). Сейчас разрешено только из статуса NEW."""
    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data
            current_status = request.status or "new"
            logging.info(f"✅ reject_request #{request_id}, current_status={current_status}")

            # Нельзя второй раз отклонять или трогать завершённые
            if current_status in ("rejected", "completed"):
                await callback.answer(
                    "❌ Заявка уже завершена или отклонена",
                    show_alert=True,
                )
                return

            # Важное изменение: отклонить можно только пока заявка новая.
            if current_status != "new":
                await callback.answer(
                    "❌ Отклонить можно только новую заявку до согласования с клиентом",
                    show_alert=True,
                )
                return

            request.status = "rejected"
            request.rejected_at = datetime.now()
            await session.commit()
            logging.info(f"❌ Заявка #{request_id} отклонена в {request.rejected_at}")

            # Сообщаем клиенту
            try:
                await callback.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        "❌ <b>К сожалению, ваша заявка была отклонена.</b>\n\n"
                        f"📋 <b>Номер заявки:</b> #{request.id}\n"
                        f"🛠️ <b>Услуга:</b> {request.service_type}"
                    ),
                    parse_mode="HTML",
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить сообщение пользователю об отклонении заявки #{request_id}: {send_err}"
                )

            await update_chat_keyboard(callback.bot, request_id)
            await callback.answer("✅ Заявка отклонена")

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка отклонения заявки #{request_id}: {e}")
            await callback.answer("❌ Ошибка при изменении статуса", show_alert=True)
