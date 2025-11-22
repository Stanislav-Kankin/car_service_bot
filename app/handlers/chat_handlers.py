import logging
from datetime import datetime
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.services.chat_service import update_chat_keyboard
from app.services.bonus_service import add_bonus

router = Router()


# =======================
#   FSM для менеджера
# =======================

class ManagerOfferStates(StatesGroup):
    waiting_price = State()
    waiting_time = State()
    waiting_comment = State()


class ManagerRejectStates(StatesGroup):
    waiting_reason = State()


# =======================
#   Вспомогалки
# =======================

async def _load_request_with_user(
    session, request_id: int
) -> Optional[Tuple[Request, User]]:
    result = await session.execute(
        select(Request, User)
        .join(User, Request.user_id == User.id)
        .where(Request.id == request_id)
    )
    row = result.first()
    if not row:
        return None
    return row[0], row[1]


def _ensure_manager_chat(callback: CallbackQuery) -> bool:
    """
    Проверяем, что коллбек пришёл из "менеджерского" контекста.

    Сейчас считаем менеджерским любой чат, где есть карточка заявки автосервиса:
    - ЛС сервиса
    - группа автосервиса

    Клиенты эти кнопки не видят, поэтому здесь достаточно такой проверки.
    """
    if not callback.message or not callback.message.chat:
        return False
    return True


# =======================
# 1. Менеджер: отправка условий / отказ (FSM, БЕЗ reply)
# =======================

@router.callback_query(F.data.startswith("mgr_offer:"))
async def manager_offer_start(callback: CallbackQuery, state: FSMContext):
    """
    Менеджер нажал "Ответить клиенту" под карточкой заявки.

    Дальше запускаем FSM:
    1) спрашиваем цену
    2) спрашиваем сроки
    3) спрашиваем доп. комментарий (опционально)
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        data = await _load_request_with_user(session, request_id)
        if not data:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return

        request, user = data

        if request.status not in ("new", "rejected"):
            await callback.answer(
                "Статус заявки не позволяет отправить условия", show_alert=True
            )
            return

    # Сбрасываем предыдущие состояния и запускаем новый сценарий
    await state.clear()
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"💬 Заявка #{request_id}\n\n"
        "Введите <b>стоимость работ</b> для клиента (например: <code>5000 руб</code>):",
        parse_mode="HTML",
    )
    await state.set_state(ManagerOfferStates.waiting_price)
    await callback.answer()


@router.message(ManagerOfferStates.waiting_price)
async def manager_offer_price(message: Message, state: FSMContext):
    price = (message.text or "").strip()
    if not price:
        await message.answer("❌ Стоимость не может быть пустой. Укажите цену одним сообщением.")
        return

    await state.update_data(price=price)
    await state.set_state(ManagerOfferStates.waiting_time)

    await message.answer(
        "⏱ Теперь укажите <b>сроки выполнения</b> (например: <code>завтра с 10 до 14</code>):",
        parse_mode="HTML",
    )


@router.message(ManagerOfferStates.waiting_time)
async def manager_offer_time(message: Message, state: FSMContext):
    time_text = (message.text or "").strip()
    if not time_text:
        await message.answer("❌ Сроки не могут быть пустыми. Укажите сроки одним сообщением.")
        return

    await state.update_data(time=time_text)
    await state.set_state(ManagerOfferStates.waiting_comment)

    await message.answer(
        "✏️ Если нужно, добавьте <b>дополнительный комментарий</b> для клиента "
        "(например, условия записи, предоплата и т.п.).\n\n"
        "Если комментарий не нужен — напишите <code>-</code>.",
        parse_mode="HTML",
    )


@router.message(ManagerOfferStates.waiting_comment)
async def manager_offer_comment(message: Message, state: FSMContext):
    comment_raw = (message.text or "").strip()
    extra_comment = None if not comment_raw or comment_raw == "-" else comment_raw

    data = await state.get_data()
    request_id = data.get("request_id")
    price = data.get("price")
    time_text = data.get("time")

    if not request_id or not price or not time_text:
        await message.answer("❌ Состояние диалога потеряно. Попробуйте ещё раз с кнопки под заявкой.")
        await state.clear()
        return

    async with AsyncSessionLocal() as session:
        try:
            loaded = await _load_request_with_user(session, request_id)
            if not loaded:
                await message.answer("❌ Заявка не найдена.")
                await state.clear()
                return

            request, user = loaded

            if request.status not in ("new", "rejected", "offer_sent"):
                await message.answer(
                    "Статус заявки больше не позволяет отправить условия. "
                    "Обновите карточку заявки и проверьте статус."
                )
                await state.clear()
                return

            # Формируем текст условий для хранения и показа
            comment_lines = [
                f"Стоимость: {price}",
                f"Сроки: {time_text}",
            ]
            if extra_comment:
                comment_lines.append(f"Комментарий: {extra_comment}")

            manager_comment = "\n".join(comment_lines)

            request.manager_comment = manager_comment
            request.status = "offer_sent"
            await session.commit()

            # Отправляем клиенту условия
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Принять",
                            callback_data=f"offer_accept:{request.id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"offer_reject:{request.id}",
                        ),
                    ]
                ]
            )

            offer_text = (
                f"📋 Ваша заявка #{request.id}\n\n"
                f"🛠 Услуга: {request.service_type}\n\n"
                f"💬 Условия от сервиса:\n{manager_comment}\n\n"
                "Вы можете принять или отклонить эти условия:"
            )

            try:
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=offer_text,
                    reply_markup=kb,
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить условия клиенту по заявке #{request.id}: {send_err}"
                )

            # Сообщаем менеджеру
            await message.answer(
                f"✅ Условия по заявке #{request.id} отправлены клиенту."
            )

            # Обновляем клавиатуру под карточкой заявки
            await update_chat_keyboard(message.bot, request.id)

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при сохранении условий по заявке #{request_id}: {e}"
            )
            await message.answer("❌ Ошибка при сохранении условий. Попробуйте позже.")

    await state.clear()


@router.callback_query(F.data.startswith("mgr_reject:"))
async def manager_reject_start(callback: CallbackQuery, state: FSMContext):
    """
    Менеджер нажал "Отклонить заявку".
    Дальше спрашиваем причину отказа (FSM).
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        data = await _load_request_with_user(session, request_id)
        if not data:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return

        request, user = data

        if request.status in ("completed", "rejected"):
            await callback.answer(
                "Заявка уже завершена или отклонена", show_alert=True
            )
            return

    await state.clear()
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"❌ Отклонение заявки #{request_id}\n\n"
        "Введите <b>причину отказа</b> одним сообщением. "
        "Это сообщение будет отправлено клиенту.",
        parse_mode="HTML",
    )
    await state.set_state(ManagerRejectStates.waiting_reason)
    await callback.answer()


@router.message(ManagerRejectStates.waiting_reason)
async def manager_reject_reason(message: Message, state: FSMContext):
    reason = (message.text or "").strip()
    if not reason:
        await message.answer(
            "❌ Причина отказа не может быть пустой. Введите текст одним сообщением."
        )
        return

    data = await state.get_data()
    request_id = data.get("request_id")
    if not request_id:
        await message.answer("❌ Состояние диалога потеряно. Попробуйте ещё раз с кнопки под заявкой.")
        await state.clear()
        return

    async with AsyncSessionLocal() as session:
        try:
            loaded = await _load_request_with_user(session, request_id)
            if not loaded:
                await message.answer("❌ Заявка не найдена.")
                await state.clear()
                return

            request, user = loaded

            if request.status in ("completed", "rejected"):
                await message.answer(
                    "Заявка уже завершена или отклонена. Статус изменить нельзя."
                )
                await state.clear()
                return

            request.manager_comment = reason
            request.status = "rejected"
            request.rejected_at = datetime.now()
            await session.commit()

            # Уведомляем клиента
            try:
                text_client = (
                    f"❌ Ваша заявка #{request.id} была отклонена.\n\n"
                    f"Причина:\n{reason}"
                )
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=text_client,
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить сообщение клиенту об отклонении заявки #{request.id}: {send_err}"
                )

            await message.answer(
                f"✅ Заявка #{request.id} отклонена, причина отправлена клиенту."
            )
            await update_chat_keyboard(message.bot, request.id)

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при отклонении заявки #{request_id}: {e}"
            )
            await message.answer("❌ Ошибка при изменении статуса. Попробуйте позже.")

    await state.clear()


# =======================
# 2. Клиент: принять / отклонить предложение (offer_accept / offer_reject)
# =======================

@router.callback_query(F.data.startswith("offer_accept:"))
async def client_accept_offer(callback: CallbackQuery):
    """
    Клиент принимает условия сервиса по заявке.
    """
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = row

            if user.telegram_id != callback.from_user.id:
                await callback.answer(
                    "❌ Эта заявка принадлежит другому пользователю",
                    show_alert=True,
                )
                return

            if request.status != "offer_sent":
                await callback.answer(
                    "Статус заявки не позволяет принять условия", show_alert=True
                )
                return

            request.status = "accepted_by_client"
            request.accepted_at = datetime.now()
            await session.commit()

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при подтверждении условий клиентом для заявки #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Бонус за принятие условий
    try:
        await add_bonus(
            callback.from_user.id,
            "accept_offer",
            description=f"Принятие условий по заявке #{request_id}",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за принятие условий: {bonus_err}")

    # Сообщение клиенту
    await callback.answer("✅ Вы приняли условия сервиса.", show_alert=True)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

        # Обновляем карточку заявки в чате сервиса
    try:
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(
            f"❌ Не удалось обновить клавиатуру в чате заявки #{request_id}: {e}"
        )


@router.callback_query(F.data.startswith("offer_reject:"))
async def client_reject_offer(callback: CallbackQuery):
    """
    Клиент отклоняет условия сервиса по заявке.
    """
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = row

            if user.telegram_id != callback.from_user.id:
                await callback.answer(
                    "❌ Эта заявка принадлежит другому пользователю",
                    show_alert=True,
                )
                return

            if request.status != "offer_sent":
                await callback.answer(
                    "Статус заявки не позволяет отклонить условия",
                    show_alert=True,
                )
                return

            request.status = "rejected"
            request.rejected_at = datetime.now()
            await session.commit()

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при отказе от условий клиентом для заявки #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    await callback.answer("❌ Вы отклонили условия.", show_alert=True)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

        # Обновляем карточку заявки в чате сервиса
    try:
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(
            f"❌ Не удалось обновить клавиатуру в чате заявки #{request_id}: {e}"
        )


# =======================
# 3. Менеджер: принять / взять в работу / завершить / отменить / обновить
# =======================

@router.callback_query(F.data.startswith("chat_confirm:"))
async def manager_confirm_after_client(callback: CallbackQuery):
    """
    Менеджер подтверждает заявку после того, как клиент принял условия.
    Статус: accepted_by_client -> accepted
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data

            if request.status != "accepted_by_client":
                await callback.answer(
                    "Заявка не находится в статусе 'принята клиентом'",
                    show_alert=True,
                )
                return

            request.status = "accepted"
            if not request.accepted_at:
                request.accepted_at = datetime.now()

            await session.commit()
        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при подтверждении заявки менеджером #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Уведомляем клиента
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"✅ Ваша заявка #{request.id} принята сервисом.\n"
                f"Скоро работы будут начаты."
            ),
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось уведомить клиента о подтверждении заявки #{request_id}: {e}"
        )

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("✅ Заявка подтверждена")


@router.callback_query(F.data.startswith("chat_start:"))
async def manager_start_work(callback: CallbackQuery):
    """
    Менеджер берёт заявку в работу.

    Возможные статусы до этого:
    - accepted_by_client (прямой старт, минуя отдельное подтверждение)
    - accepted
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data

            if request.status not in ("accepted_by_client", "accepted"):
                await callback.answer(
                    "Заявку можно взять в работу только после принятия условий клиентом",
                    show_alert=True,
                )
                return

            if not request.accepted_at:
                request.accepted_at = datetime.now()

            request.status = "in_progress"
            request.in_progress_at = datetime.now()
            await session.commit()
        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при переводе заявки #{request_id} в работу: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Уведомляем клиента
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"🔧 Ваш автомобиль по заявке #{request.id} взят в работу.\n"
                f"По окончании работ вы получите уведомление."
            ),
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось уведомить клиента о начале работ по заявке #{request_id}: {e}"
        )

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("✅ Заявка взята в работу")


@router.callback_query(F.data.startswith("chat_complete:"))
async def manager_complete_request(callback: CallbackQuery):
    """
    Менеджер завершает заявку (работы выполнены).
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data

            if request.status != "in_progress":
                await callback.answer(
                    "Завершить можно только заявку, находящуюся в работе",
                    show_alert=True,
                )
                return

            request.status = "completed"
            request.completed_at = datetime.now()
            await session.commit()
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка завершения заявки #{request_id}: {e}")
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Бонус за завершённую заявку
    try:
        await add_bonus(
            user.telegram_id,
            "complete_request",
            description=f"Завершение заявки #{request_id}",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за завершение заявки: {bonus_err}")

    # Уведомляем клиента
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"✅ Работы по вашей заявке #{request.id} завершены.\n"
                f"Спасибо за обращение!"
            ),
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось уведомить клиента о завершении заявки #{request_id}: {e}"
        )

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("✅ Заявка завершена")


@router.callback_query(F.data.startswith("chat_cancel:"))
async def manager_cancel_request(callback: CallbackQuery):
    """
    Менеджер отменяет заявку на любом этапе до завершения.
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            data = await _load_request_with_user(session, request_id)
            if not data:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user = data

            if request.status in ("completed", "rejected"):
                await callback.answer(
                    "Заявка уже завершена или отклонена", show_alert=True
                )
                return

            request.status = "rejected"
            request.rejected_at = datetime.now()
            await session.commit()
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка отмены заявки #{request_id}: {e}")
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Уведомляем клиента
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"❌ Ваша заявка #{request.id} была отменена сервисом.\n"
                f"При необходимости вы можете создать новую заявку."
            ),
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось отправить сообщение клиенту об отмене заявки #{request_id}: {e}"
        )

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("✅ Заявка отменена")


@router.callback_query(F.data.startswith("chat_refresh:"))
async def manager_refresh_keyboard(callback: CallbackQuery):
    """
    Ручное обновление клавиатуры под заявкой.
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате автосервиса", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("🔄 Обновлено")
