import logging
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Router, F, Bot
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, ServiceCenter
from app.services.chat_service import update_chat_keyboard
from app.services.bonus_service import add_bonus
from app.keyboards.main_kb import get_rating_kb


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


async def _notify_service_about_client_action(
    bot,
    session,
    request: Request,
    service_center: Optional[ServiceCenter],
    text: str,
) -> None:
    """
    Отправляет уведомление в основной чат сервиса по заявке.

    Логика выбора чата:
    - если у заявки есть service_center:
        • если send_to_group и manager_chat_id → туда
        • иначе, если send_to_owner → ЛС владельца
    - иначе — fallback на MANAGER_CHAT_ID (если он задан)

    Дополнительно:
    - к уведомлению прикрепляем кнопку "📩 Написать клиенту" (по telegram_id),
      чтобы можно было сразу открыть чат, не зная номера телефона.
    """
    primary_chat_id: Optional[int] = None

    # 1. Определяем основной чат сервиса
    owner_telegram_id: Optional[int] = None
    if service_center:
        # Владелец сервиса (для ЛС)
        if service_center.owner_user_id:
            owner_res = await session.execute(
                select(User).where(User.id == service_center.owner_user_id)
            )
            owner = owner_res.scalar_one_or_none()
            if owner and owner.telegram_id:
                owner_telegram_id = owner.telegram_id

        # Отправка в группу сервиса
        if service_center.send_to_group and service_center.manager_chat_id:
            primary_chat_id = service_center.manager_chat_id
        # Или в ЛС владельцу
        elif service_center.send_to_owner and owner_telegram_id:
            primary_chat_id = owner_telegram_id

    # Fallback на MANAGER_CHAT_ID
    if primary_chat_id is None and config.MANAGER_CHAT_ID:
        primary_chat_id = config.MANAGER_CHAT_ID

    if primary_chat_id is None:
        logging.error(
            f"❌ Не удалось определить чат сервиса для уведомления по заявке #{request.id}"
        )
        return

    # 2. Ищем telegram_id клиента, чтобы сделать кнопку "Написать клиенту"
    client_tg_id: Optional[int] = None
    try:
        user_res = await session.execute(
            select(User).where(User.id == request.user_id)
        )
        db_user = user_res.scalar_one_or_none()
        if db_user and db_user.telegram_id:
            client_tg_id = db_user.telegram_id
    except Exception as e:
        logging.error(
            f"❌ Ошибка поиска клиента для уведомления по заявке #{request.id}: {e}"
        )

    # 3. Собираем клавиатуру
    kb = None
    if client_tg_id:
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📩 Написать клиенту",
            url=f"tg://user?id={client_tg_id}",
        )
        kb = builder.as_markup()

    # 4. Отправляем уведомление
    try:
        await bot.send_message(
            chat_id=primary_chat_id,
            text=text,
            reply_markup=kb,
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось отправить уведомление в чат сервиса {primary_chat_id} "
            f"по заявке #{request.id}: {e}"
        )


# =======================
# 1. Менеджер: отправка условий / отказ (FSM, БЕЗ reply)
# =======================

@router.callback_query(F.data.startswith("mgr_offer:"))
async def manager_offer_start(callback: CallbackQuery, state: FSMContext):
    """
    Менеджер нажал "Ответить клиенту" под карточкой заявки.

    Новый вариант: сразу просим одним сообщением написать все условия
    (стоимость, сроки, комментарий).
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

        # Разрешаем отправлять условия только по "живым" заявкам
        if request.status not in ("new", "rejected", "offer_sent"):
            await callback.answer(
                "Статус заявки не позволяет отправить условия", show_alert=True
            )
            return

    # Сбрасываем предыдущие состояния и запускаем новый сценарий
    await state.clear()
    await state.update_data(request_id=request_id)

    await callback.message.answer(
        f"💬 Заявка #{request_id}\n\n"
        "Напишите одним сообщением предложение для клиента:\n"
        "• ориентировочную стоимость;\n"
        "• примерные сроки выполнения;\n"
        "• при необходимости дополнительные условия.\n\n"
        "Пример: <code>Диагностика от 40 BYN, ремонт от 120 BYN, завтра после 14:00</code>",
        parse_mode="HTML",
    )
    # Сразу ждём общий комментарий, price/time больше не спрашиваем
    await state.set_state(ManagerOfferStates.waiting_comment)
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


# В начале файла убедись, что есть:
# from datetime import datetime, timedelta
# from sqlalchemy import select
# from app.database.models import Request, User, ServiceCenter
# from app.services.chat_service import update_chat_keyboard  # если ещё нет импорта


async def _auto_decline_other_requests(
    bot: Bot,
    session: AsyncSession,
    accepted_request: Request,
) -> None:
    """
    Автоматически отклоняет все другие активные заявки клиента
    по тому же авто и типу работ, если он принял условия по одной.

    Логика:
    - тот же user_id;
    - тот же car_id;
    - тот же service_type;
    - статус в ('new', 'offer_sent', 'accepted_by_client');
    - другой request.id.
    """
    try:
        result = await session.execute(
            select(Request, ServiceCenter)
            .join(
                ServiceCenter,
                Request.service_center_id == ServiceCenter.id,
                isouter=True,
            )
            .where(
                Request.user_id == accepted_request.user_id,
                Request.id != accepted_request.id,
                Request.service_type == accepted_request.service_type,
                Request.car_id == accepted_request.car_id,
                Request.status.in_(["new", "offer_sent", "accepted_by_client"]),
            )
        )
        rows = result.all()
    except Exception as e:
        logging.error(
            f"❌ Ошибка поиска параллельных заявок для auto-decline по #{accepted_request.id}: {e}"
        )
        return

    if not rows:
        return

    now = datetime.now()

    for other_req, other_sc in rows:
        # подстраховка, вдруг статус уже изменился где-то ещё
        if other_req.status in ("completed", "rejected"):
            continue

        other_req.status = "rejected"
        other_req.rejected_at = now

        # дописываем в комментарий менеджера пометку
        auto_text = "Автоотказ: клиент выбрал другой сервис."
        if not other_req.manager_comment:
            other_req.manager_comment = auto_text
        else:
            other_req.manager_comment = f"{other_req.manager_comment}\n\n{auto_text}"

        try:
            await _notify_service_about_client_action(
                bot,
                session,
                other_req,
                other_sc,
                text=(
                    f"❌ Клиент выбрал другой сервис по заявке #{other_req.id}.\n"
                    f"Заявка автоматически переведена в статус «Отклонена»."
                ),
            )
        except Exception as e:
            logging.error(
                f"❌ Не удалось уведомить сервис об автоотказе по заявке #{other_req.id}: {e}"
            )

        try:
            await update_chat_keyboard(bot, other_req.id)
        except Exception as e:
            logging.error(
                f"❌ Не удалось обновить клавиатуру по заявке #{other_req.id} после auto-decline: {e}"
            )



@router.message(ManagerOfferStates.waiting_comment)
async def manager_offer_comment(message: Message, state: FSMContext):
    """
    Менеджер присылает единый текстовый комментарий с условиями:
    цена + сроки + любые доп. комментарии.
    """
    comment_text = (message.text or "").strip()
    if not comment_text:
        await message.answer(
            "❌ Текст предложения не может быть пустым. "
            "Напишите условия одним сообщением."
        )
        return

    data = await state.get_data()
    request_id = data.get("request_id")

    if not request_id:
        await message.answer(
            "❌ Состояние диалога потеряно. Попробуйте ещё раз с кнопки под заявкой."
        )
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

            # Сохраняем комментарий менеджера и переводим в offer_sent
            request.manager_comment = comment_text
            request.status = "offer_sent"
            await session.commit()

            # Определяем контакт менеджера для кнопки связи
            manager_telegram_id = None
            if request.service_center_id:
                sc_res = await session.execute(
                    select(ServiceCenter).where(
                        ServiceCenter.id == request.service_center_id
                    )
                )
                sc = sc_res.scalar_one_or_none()
                if sc and sc.owner_user_id:
                    owner_res = await session.execute(
                        select(User).where(User.id == sc.owner_user_id)
                    )
                    owner = owner_res.scalar_one_or_none()
                    if owner and owner.telegram_id:
                        manager_telegram_id = owner.telegram_id

            # Кнопки для клиента:
            # принять с номером / без номера, отклонить + написать менеджеру
            kb_rows = [
                [
                    InlineKeyboardButton(
                        text="✅ Принять (показать номер)",
                        callback_data=f"offer_accept_show_phone:{request.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✅ Принять (не показывать номер)",
                        callback_data=f"offer_accept_no_phone:{request.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"offer_reject:{request.id}",
                    ),
                ],
            ]

            if manager_telegram_id:
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text="💬 Написать менеджеру",
                            url=f"tg://user?id={manager_telegram_id}",
                        )
                    ]
                )

            kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

            offer_text = (
                f"📋 Ваша заявка #{request.id}\n\n"
                f"🛠 Услуга: {request.service_type}\n\n"
                f"💬 Условия от сервиса:\n{comment_text}\n\n"
                "Вы можете принять, отклонить эти условия или задать вопрос менеджеру."
            )

            try:
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=offer_text,
                    reply_markup=kb,
                )
            except Exception as send_err:
                logging.error(
                    f"❌ Не удалось отправить условия клиенту по заявке "
                    f"#{request.id}: {send_err}"
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
    В этот момент мы отправляем сервису номер телефона клиента.
    """
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User, ServiceCenter)
                .join(User, Request.user_id == User.id)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user, service_center = row

            # Проверяем, что это тот же пользователь
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

            # Текст для уведомления сервиса
            notify_text = f"✅ Клиент принял условия по заявке #{request.id}."
            if user.phone_number:
                notify_text += f"\n📞 Телефон клиента: {user.phone_number}"

            # Уведомляем сервис
            await _notify_service_about_client_action(
                callback.bot,
                session,
                request,
                service_center,
                text=notify_text,
            )

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
    await callback.answer(
        "✅ Вы приняли условия сервиса.\n"
        "Ваш номер телефона отправлен в автосервис для уточнения деталей.",
        show_alert=True,
    )

    # Убираем кнопки под сообщением клиента
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Обновляем карточку заявки в чате сервиса (кнопки)
    try:
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(
            f"❌ Не удалось обновить клавиатуру в чате заявки #{request_id}: {e}"
        )

@router.callback_query(F.data.startswith("offer_accept_no_phone:"))
async def client_accept_offer_no_phone(callback: CallbackQuery):
    """
    Клиент принимает условия сервиса, НО не отправляет номер телефона.
    Общение идёт только через чат Telegram.
    """
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User, ServiceCenter)
                .join(User, Request.user_id == User.id)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user, service_center = row

            # Защита от «чужих» заявок
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

            # Уведомляем сервис: клиент принял, но номер не дал
            await _notify_service_about_client_action(
                callback.bot,
                session,
                request,
                service_center,
                text=(
                    f"✅ Клиент принял условия по заявке #{request.id}.\n"
                    f"ℹ️ Клиент выбрал НЕ показывать номер телефона.\n"
                    f"Свяжитесь с ним через чат Telegram."
                ),
            )

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при подтверждении условий (без номера) клиентом для заявки #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # Бонус за принятие условий
    try:
        await add_bonus(
            callback.from_user.id,
            "accept_offer",
            description=f"Принятие условий без показа номера по заявке #{request_id}",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за принятие условий: {bonus_err}")

    await callback.answer("✅ Вы приняли условия сервиса, не показывая номер.", show_alert=True)

    # Убираем кнопки
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


@router.callback_query(F.data.startswith("offer_accept_show_phone:"))
async def client_accept_offer_show_phone(callback: CallbackQuery):
    """
    Клиент принимает предложение сервиса и СОГЛАСЕН передать свой номер телефона.
    """
    try:
        request_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User, ServiceCenter)
                .join(User, Request.user_id == User.id)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user, service_center = row

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

            # помечаем как принята клиентом
            request.status = "accepted_by_client"
            request.accepted_at = datetime.now()

            # уведомление сервису + передача телефона
            notify_text = f"✅ Клиент принял условия по заявке #{request.id}."
            if user.phone_number:
                notify_text += f"\n📞 Телефон клиента: {user.phone_number}"

            await _notify_service_about_client_action(
                callback.bot,
                session,
                request,
                service_center,
                text=notify_text,
            )

            # ⚙️ Автоотказ другим параллельным заявкам
            await _auto_decline_other_requests(callback.bot, session, request)

            # общий коммит
            await session.commit()

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при подтверждении условий клиентом (show_phone) для заявки #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    # бонусы
    try:
        await add_bonus(
            callback.from_user.id,
            "accept_offer",
            description=f"Принятие условий по заявке #{request_id}",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за принятие условий: {bonus_err}")

    await callback.answer("✅ Вы приняли условия сервиса и передали свой номер.")


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
                select(Request, User, ServiceCenter)
                .join(User, Request.user_id == User.id)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request, user, service_center = row

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

            # Уведомляем сервис о том, что клиент отклонил условия
            await _notify_service_about_client_action(
                callback.bot,
                session,
                request,
                service_center,
                text=f"❌ Клиент отклонил условия по заявке #{request.id}.",
            )

        except Exception as e:
            await session.rollback()
            logging.error(
                f"❌ Ошибка при отказе от условий клиентом для заявки #{request_id}: {e}"
            )
            await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
            return

    await callback.answer("❌ Вы отклонили условия.", show_alert=True)

    # Убираем кнопки у клиента
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Обновляем карточку заявки в чате сервиса (кнопки)
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
    # Бонус за завершённую заявку
    try:
        await add_bonus(
            user.telegram_id,
            "complete_request",
            description=f"Завершение заявки #{request_id}",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за завершение заявки: {bonus_err}")

    # Уведомляем клиента и просим оценить сервис
    try:
        await callback.bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"🏁 Работы по вашей заявке #{request.id} завершены.\n"
                f"Пожалуйста, оцените работу сервиса по шкале от 1 до 5."
            ),
            reply_markup=get_rating_kb(request.id),
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
