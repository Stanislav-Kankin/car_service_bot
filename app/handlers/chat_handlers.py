import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.services.chat_service import update_chat_keyboard
from app.services.bonus_service import add_bonus

router = Router()

# request_id -> "offer" | "reject"
PENDING_ACTIONS: Dict[int, str] = {}

# message_id сервисного сообщения ("Введите условия...", "Введите причину...")
# -> request_id
PROMPT_MESSAGES: Dict[int, int] = {}



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
    Проверяем, что коллбек пришёл из чата менеджеров.
    """
    if not callback.message or not callback.message.chat:
        return False

    if callback.message.chat.id != config.MANAGER_CHAT_ID:
        return False

    return True


# =======================
# 1. Менеджер: отправка условий / отказ
# =======================


@router.callback_query(F.data.startswith("mgr_offer:"))
async def manager_offer(callback: CallbackQuery):
    """
    Менеджер нажал "Ответить клиенту" в чате менеджеров.
    Дальше он должен ответить (reply) на сообщение с заявкой
    текстом с ценой и сроками.
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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

    # Запоминаем, что для этой заявки ожидаем текст условий
    PENDING_ACTIONS[request_id] = "offer"

    prompt = await callback.message.reply(
        "💬 Введите условия для клиента (цена, сроки и т.п.) одним сообщением.\n\n"
        "‼️ Ответьте <b>reply</b> на ЭТО сообщение или на сообщение с заявкой.",
        parse_mode="HTML",
    )
    # Запомним, что этот prompt относится к заявке request_id
    PROMPT_MESSAGES[prompt.message_id] = request_id

    await callback.answer()


@router.callback_query(F.data.startswith("mgr_reject:"))
async def manager_reject_start(callback: CallbackQuery):
    """
    Менеджер нажал "Отклонить заявку" в чате менеджеров.
    Дальше он должен ответить (reply) на сообщение с заявкой
    текстом с причиной отказа.
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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

    PENDING_ACTIONS[request_id] = "reject"

    prompt = await callback.message.reply(
        "❌ Введите причину отказа одним сообщением.\n\n"
        "‼️ Ответьте <b>reply</b> на ЭТО сообщение или на сообщение с заявкой.",
        parse_mode="HTML",
    )
    PROMPT_MESSAGES[prompt.message_id] = request_id

    await callback.answer()


@router.message(F.chat.id == config.MANAGER_CHAT_ID)
async def manager_reply_in_group(message: Message):
    """
    Обрабатываем сообщения менеджеров в чате менеджеров.

    Если это reply на сообщение с заявкой ИЛИ на сервисное сообщение
    ("Введите условия", "Введите причину") и для этой заявки есть
    ожидаемое действие (offer / reject) — выполняем его.
    """
    if not message.reply_to_message:
        return  # не reply — нас не интересует

    replied_msg_id = message.reply_to_message.message_id

    async with AsyncSessionLocal() as session:
        # 1) Пытаемся найти заявку по chat_message_id (карточка заявки)
        result = await session.execute(
            select(Request, User)
            .join(User, Request.user_id == User.id)
            .where(Request.chat_message_id == replied_msg_id)
        )
        row = result.first()

        # 2) Если не нашли — возможно, ответили на "подсказку"
        if not row:
            req_id_from_prompt = PROMPT_MESSAGES.get(replied_msg_id)
            if not req_id_from_prompt:
                # Ни карточки, ни подсказки — игнорируем
                return

            result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == req_id_from_prompt)
            )
            row = result.first()
            if not row:
                return

        request, user = row
        request_id = request.id

        action = PENDING_ACTIONS.get(request_id)
        text = (message.text or "").strip()

        if not action:
            logging.info(
                f"[chat] Комментарий менеджера без активного действия для заявки #{request_id}: {text!r}"
            )
            return

        if not text:
            await message.reply(
                "❌ Текст не должен быть пустым. Отправьте сообщение ещё раз."
            )
            return

        # Снимаем ожидание действия и очищаем привязку подсказки
        PENDING_ACTIONS.pop(request_id, None)
        PROMPT_MESSAGES.pop(replied_msg_id, None)

        if not action:
            # Нет активного действия — можно считать это обычным комментарием
            logging.info(
                f"[chat] Комментарий менеджера без активного действия для заявки #{request_id}: {text!r}"
            )
            return

        if not text:
            await message.reply(
                "❌ Текст не должен быть пустым. Отправьте сообщение ещё раз."
            )
            return

        # Снимаем ожидание действия
        PENDING_ACTIONS.pop(request_id, None)

        # ----- ОТПРАВКА УСЛОВИЙ КЛИЕНТУ -----
        if action == "offer":
            try:
                request.manager_comment = text
                request.status = "offer_sent"
                await session.commit()

                # Уведомляем клиента
                try:
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
                        f"💬 Условия от сервиса:\n{text}\n\n"
                        "Вы можете принять или отклонить эти условия:"
                    )

                    await message.bot.send_message(
                        chat_id=user.telegram_id,
                        text=offer_text,
                        reply_markup=kb,
                    )
                except Exception as send_err:
                    logging.error(
                        f"❌ Не удалось отправить условия клиенту по заявке #{request.id}: {send_err}"
                    )

                # Сообщаем в чат менеджеров
                await message.reply(
                    f"✅ Условия по заявке #{request.id} отправлены клиенту."
                )

                # Обновляем клавиатуру в чате
                await update_chat_keyboard(message.bot, request.id)

            except Exception as e:
                await session.rollback()
                logging.error(
                    f"❌ Ошибка при сохранении условий по заявке #{request.id}: {e}"
                )
                await message.reply("❌ Ошибка при сохранении условий. Попробуйте позже.")

        # ----- ОТКЛОНЕНИЕ ЗАЯВКИ -----
        elif action == "reject":
            try:
                request.manager_comment = text
                request.status = "rejected"
                request.rejected_at = datetime.now()
                await session.commit()

                # Уведомляем клиента
                try:
                    text_client = (
                        f"❌ Ваша заявка #{request.id} была отклонена.\n\n"
                        f"Причина:\n{text}"
                    )
                    await message.bot.send_message(
                        chat_id=user.telegram_id,
                        text=text_client,
                    )
                except Exception as send_err:
                    logging.error(
                        f"❌ Не удалось отправить сообщение клиенту об отклонении заявки #{request.id}: {send_err}"
                    )

                await message.reply(
                    f"✅ Заявка #{request.id} отклонена, причина отправлена клиенту."
                )
                await update_chat_keyboard(message.bot, request.id)

            except Exception as e:
                await session.rollback()
                logging.error(
                    f"❌ Ошибка при отклонении заявки #{request.id}: {e}"
                )
                await message.reply("❌ Ошибка при изменении статуса. Попробуйте позже.")


# =======================
# 2. Клиент: принять / отклонить предложение
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
        await add_bonus(callback.from_user.id, "accept_offer", description=f"Принятие условий по заявке #{request_id}")
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за принятие условий: {bonus_err}")

    # Сообщение клиенту
    await callback.answer("✅ Вы приняли условия сервиса.", show_alert=True)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Уведомляем менеджеров
    try:
        await callback.bot.send_message(
            chat_id=config.MANAGER_CHAT_ID,
            text=(
                f"✅ Клиент принял условия по заявке #{request_id}.\n"
                f"Теперь вы можете подтвердить заявку, взять её в работу или отменить."
            ),
        )
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(
            f"❌ Не удалось уведомить менеджеров о принятии условий по заявке #{request_id}: {e}"
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

    # Уведомляем менеджеров
    try:
        await callback.bot.send_message(
            chat_id=config.MANAGER_CHAT_ID,
            text=(
                f"❌ Клиент отклонил условия по заявке #{request_id}.\n"
                f"Вы можете предложить новые условия или оставить заявку в отклонённых."
            ),
        )
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(
            f"❌ Не удалось уведомить менеджеров об отказе по заявке #{request_id}: {e}"
        )


# =======================
# 3. Менеджер: принять / взять в работу / завершить / отменить
# =======================


@router.callback_query(F.data.startswith("chat_confirm:"))
async def manager_confirm_after_client(callback: CallbackQuery):
    """
    Менеджер подтверждает заявку после того, как клиент принял условия.
    Статус: accepted_by_client -> accepted
    """
    if not _ensure_manager_chat(callback):
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
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
        await callback.answer("Доступно только в чате менеджеров", show_alert=True)
        return

    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    await update_chat_keyboard(callback.bot, request_id)
    await callback.answer("🔄 Обновлено")
