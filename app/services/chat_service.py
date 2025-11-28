import logging
from typing import Optional
from datetime import datetime

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, Car, ServiceCenter


def _format_status(status: Optional[str]) -> str:
    """
    Человекочитаемый статус заявки для отображения в карточке.
    Используется и в админке, и в карточке заявки в чатах.
    """
    status = status or "new"
    mapping = {
        "new": "🆕 Новая",
        "offer_sent": "📩 Условия отправлены клиенту",
        "accepted_by_client": "✅ Принята клиентом (ожидает подтверждения сервиса)",
        "accepted": "✅ Принята сервисом",
        "in_progress": "⏳ В работе",
        "completed": "✅ Завершена",
        "rejected": "❌ Отклонена",
        "to_pay": "💰 К оплате",
    }
    return mapping.get(status, status)


def _build_chat_keyboard(request: Request) -> InlineKeyboardMarkup:
    """
    Формирует inline-клавиатуру под сообщение в группе/чате сервиса
    в зависимости от текущего статуса заявки.

    Логика:

    - new:
        • 💬 Ответить клиенту (цена/сроки)
        • ❌ Отклонить заявку (с комментарием)
        • 🔄 Обновить
    - offer_sent:
        • 🔄 Обновить
    - accepted_by_client:
        • ✅ Принять
        • 🔧 Взять в работу
        • ❌ Отменить
    - accepted:
        • 🔧 Взять в работу
        • ❌ Отменить
    - in_progress:
        • ✅ Завершить
        • ❌ Отменить
    - completed / rejected:
        • 🔄 Обновить
    """
    kb = InlineKeyboardBuilder()
    rid = request.id
    status = request.status or "new"

    if status == "new":
        kb.button(
            text="💬 Ответить клиенту",
            callback_data=f"mgr_offer:{rid}",
        )
        kb.button(
            text="❌ Отклонить заявку",
            callback_data=f"mgr_reject:{rid}",
        )
        kb.button(
            text="🔄 Обновить",
            callback_data=f"chat_refresh:{rid}",
        )
        kb.adjust(1, 1, 1)

    elif status == "offer_sent":
        kb.button(
            text="🔄 Обновить",
            callback_data=f"chat_refresh:{rid}",
        )
        kb.adjust(1)

    elif status == "accepted_by_client":
        kb.button(
            text="✅ Принять",
            callback_data=f"chat_confirm:{rid}",
        )
        kb.button(
            text="🔧 Взять в работу",
            callback_data=f"chat_start:{rid}",
        )
        kb.button(
            text="❌ Отменить",
            callback_data=f"chat_cancel:{rid}",
        )
        kb.adjust(1, 1, 1)

    elif status == "accepted":
        kb.button(
            text="🔧 Взять в работу",
            callback_data=f"chat_start:{rid}",
        )
        kb.button(
            text="❌ Отменить",
            callback_data=f"chat_cancel:{rid}",
        )
        kb.adjust(1, 1)

    elif status == "in_progress":
        kb.button(
            text="✅ Завершить",
            callback_data=f"chat_complete:{rid}",
        )
        kb.button(
            text="❌ Отменить",
            callback_data=f"chat_cancel:{rid}",
        )
        kb.adjust(1, 1)

    else:
        # completed / rejected / прочие
        kb.button(
            text="🔄 Обновить",
            callback_data=f"chat_refresh:{rid}",
        )
        kb.adjust(1)

    return kb.as_markup()


def _format_request_text(
    request: Request,
    user: User,
    car: Optional[Car],
    service_center: Optional[ServiceCenter] = None,
) -> str:
    """
    Формат карточки заявки для чата сервиса.

    ВАЖНО:
    - здесь НЕ показываем телефон и telegram-id клиента;
    - контакт сервис получает только после явного согласия клиента
      (отдельным сообщением из хендлеров offer_accept_*).
    """
    car_block = "🚗 Автомобиль: не указан"

    if car:
        car_block = (
            "🚗 Автомобиль:\n"
            f"   • Марка: {car.brand}\n"
            f"   • Модель: {car.model}\n"
            f"   • Год: {car.year}\n"
            f"   • Госномер: {car.license_plate}"
        )

    created_at = (
        request.created_at.strftime("%d.%m.%Y %H:%M")
        if request.created_at
        else "неизвестно"
    )

    # Информация о передвижении и местоположении
    drive_text = "Не указано"
    if request.can_drive is True:
        drive_text = "Да, может ехать сам"
    elif request.can_drive is False:
        drive_text = "Нет, требуется эвакуатор/перевозка"

    if request.location_lat and request.location_lon:
        location_text = (
            "📍 Местоположение:\n"
            f"   • Координаты: {request.location_lat:.5f}, {request.location_lon:.5f}\n"
            f"   • Ссылка: https://maps.google.com/?q={request.location_lat:.5f},{request.location_lon:.5f}"
        )
    elif request.location_description:
        location_text = f"📍 Местоположение:\n   • {request.location_description}"
    else:
        location_text = "📍 Местоположение: не указано"

    service_block = ""
    if service_center:
        service_block = (
            f"\n🏭 Автосервис: {service_center.name}\n"
            f"📍 Адрес сервиса: {service_center.address or '—'}"
        )

    text = (
        f"📋 Заявка #{request.id}\n\n"
        f"👤 Клиент: {user.full_name or 'Не указано'}\n\n"  # <- БЕЗ телефона и ID
        f"{car_block}\n\n"
        f"🛠️ Услуга: {request.service_type}\n\n"
        f"📝 Описание:\n{request.description}\n\n"
        f"🚚 Может ехать сам: {drive_text}\n"
        f"{location_text}\n\n"
        f"📊 Статус: {_format_status(request.status)}\n"
        f"⏰ Создана: {created_at}"
        f"{service_block}\n\n"
        "ℹ️ Чтобы ответить по заявке, нажмите нужную кнопку ниже.\n"
        "Если нужно просто оставить комментарий, ответьте на это сообщение (Reply)."
    )

    if request.manager_comment:
        text += f"\n\n💬 Комментарий менеджера:\n{request.manager_comment}"

    return text


async def create_request_chat(bot: Bot, request_id: int) -> None:
    """
    Создаёт "карточку заявки" в чате сервиса.

    ВАЖНО:
    - больше НЕТ фоллбэка на MANAGER_CHAT_ID из .env;
    - отправляем только в чаты, привязанные к ServiceCenter в БД:
        • группа сервиса (manager_chat_id при send_to_group=True)
        • ЛС владельца сервиса (owner_user_id -> User.telegram_id при send_to_owner=True).
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, User, Car, ServiceCenter)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id, isouter=True)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()

            if not row:
                logging.error(f"❌ create_request_chat: заявка #{request_id} не найдена")
                return

            request, user, car, service_center = row

            # Жёсткое требование: только из БД, global-чат не используем
            if not service_center:
                logging.error(
                    f"❌ create_request_chat: у заявки #{request_id} нет привязанного автосервиса "
                    f"(service_center_id IS NULL). Карточка не будет отправлена."
                )
                return

            primary_chat_id: Optional[int] = None
            extra_chat_ids: list[int] = []

            # Определяем основной и дополнительные каналы для сервиса
            owner_telegram_id: Optional[int] = None
            if service_center.owner_user_id:
                owner_res = await session.execute(
                    select(User).where(User.id == service_center.owner_user_id)
                )
                owner = owner_res.scalar_one_or_none()
                if owner and owner.telegram_id:
                    owner_telegram_id = owner.telegram_id

            # приоритет: группа → ЛС владельца
            if service_center.send_to_group and service_center.manager_chat_id:
                primary_chat_id = service_center.manager_chat_id

            if service_center.send_to_owner and owner_telegram_id:
                if primary_chat_id is None:
                    primary_chat_id = owner_telegram_id
                else:
                    extra_chat_ids.append(owner_telegram_id)

            if primary_chat_id is None:
                logging.error(
                    f"❌ create_request_chat: не удалось определить чат автосервиса "
                    f"для заявки #{request_id}. "
                    f"service_center.id={service_center.id}, "
                    f"send_to_group={service_center.send_to_group}, "
                    f"manager_chat_id={service_center.manager_chat_id}, "
                    f"send_to_owner={service_center.send_to_owner}, "
                    f"owner_telegram_id={owner_telegram_id}"
                )
                return

            text = _format_request_text(request, user, car, service_center)
            keyboard = _build_chat_keyboard(request)

            # Кнопка для менеджера: написать клиенту в Telegram (без показа номера)
            if user.telegram_id:
                keyboard.inline_keyboard.append(
                    [
                        InlineKeyboardButton(
                            text="📩 Написать клиенту",
                            url=f"tg://user?id={user.telegram_id}",
                        )
                    ]
                )

            async def _send_to_chat(chat_id: int) -> Optional[int]:
                """
                Отправляет карточку заявки в указанный чат.
                Если есть photo_file_id — пробуем отправить как фото с подписью.
                При любой ошибке или отсутствии фото отправляем обычный текст.
                """
                msg = None
                file_id = request.photo_file_id or None

                if file_id:
                    try:
                        msg = await bot.send_photo(
                            chat_id=chat_id,
                            photo=file_id,
                            caption=text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logging.error(
                            f"❌ Ошибка отправки фото в чат {chat_id} для заявки #{request_id}: {e}"
                        )
                        msg = None

                if msg is None:
                    # Фоллбек на обычное сообщение
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )

                return msg.message_id

            # Отправляем в основной канал
            primary_msg_id = await _send_to_chat(primary_chat_id)
            if primary_msg_id:
                request.chat_message_id = primary_msg_id
                await session.commit()
                logging.info(
                    f"✅ Чат для заявки #{request_id} создан и сообщение отправлено "
                    f"(chat_id={primary_chat_id}, msg_id={primary_msg_id})"
                )

            # Дополнительно — дублируем в остальные каналы (без сохранения message_id)
            for chat_id in extra_chat_ids:
                try:
                    await _send_to_chat(chat_id)
                    logging.info(
                        f"ℹ️ Дополнительно отправлена копия заявки #{request_id} в чат {chat_id}"
                    )
                except Exception as e:
                    logging.error(
                        f"❌ Не удалось отправить копию заявки #{request_id} в чат {chat_id}: {e}"
                    )

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка создания чата для заявки #{request_id}: {e}")


# app/services/chat_service.py
import logging
from datetime import datetime

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.database.db import AsyncSessionLocal
from app.database.models import Request, ServiceCenter, User


async def update_chat_keyboard(request_id: int, chat_id: int, bot) -> None:
    """
    Обновляет inline-клавиатуру под карточкой заявки в чате (чат заявки / группа сервиса).
    Теперь учитывает расширенный жизненный цикл:
    new -> offer_sent -> accepted_by_client -> in_progress -> completed / cancelled / rejected
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Request, ServiceCenter)
            .outerjoin(ServiceCenter, Request.service_center_id == ServiceCenter.id)
            .where(Request.id == request_id)
        )
        row = result.first()

        if not row:
            logging.warning(f"⚠️ update_chat_keyboard: заявка #{request_id} не найдена")
            return

        request, service_center = row

        if not request.chat_message_id:
            logging.warning(
                f"⚠️ update_chat_keyboard: у заявки #{request.id} нет chat_message_id, нечего обновлять"
            )
            return

        keyboard = _build_request_keyboard(request, service_center)

    logging.info(
        f"🔧 update_chat_keyboard #{request.id}, status={request.status}, chat_id={chat_id}"
    )

    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=request.chat_message_id,
            reply_markup=keyboard,
        )
    except Exception as e:
        # Например: 'message is not modified'
        logging.info(f"ℹ️ Клавиатура для заявки #{request.id} уже актуальна: {e}")


def _build_request_keyboard(
    request: Request,
    service_center: ServiceCenter | None,
) -> InlineKeyboardMarkup:
    """
    Строим inline-клавиатуру в зависимости от статуса заявки.

    Статусы:
      - new                 — заявка создана, условия не отправлены
      - offer_sent          — сервис отправил предложение
      - accepted_by_client  — клиент принял условия
      - in_progress         — сервис взял в работу
      - completed           — работа завершена
      - cancelled           — отменена после принятия
      - rejected            — отказ / автоотказ
    """
    buttons: list[list[InlineKeyboardButton]] = []

    # Кнопка "Написать менеджеру" — общая, если есть сервис
    if service_center is not None:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✉️ Написать менеджеру",
                    callback_data=f"open_chat:{request.id}",
                )
            ]
        )

    # --- Статусы / действия ---

    if request.status == "new":
        # Тут обычно только менеджер может отправить предложение (у тебя это уже реализовано)
        # Никаких дополнительных кнопок не добавляем.
        pass

    elif request.status == "offer_sent":
        # Клиент может принять или отказаться (это уже реализовано в клиентских хендлерах).
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Принять условия",
                    callback_data=f"client_accept_offer:{request.id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отказаться",
                    callback_data=f"client_reject_offer:{request.id}",
                ),
            ]
        )

    elif request.status == "accepted_by_client":
        # Клиент уже подтвердил, теперь ход за сервисом:
        # Принять в работу / Отменить заявку
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔧 Принять в работу",
                    callback_data=f"manager_start_work:{request.id}",
                ),
                InlineKeyboardButton(
                    text="🚫 Отменить заявку",
                    callback_data=f"manager_cancel_after_accept:{request.id}",
                ),
            ]
        )

    elif request.status == "in_progress":
        # Заявка в работе: сервис может завершить или отменить
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Работа выполнена",
                    callback_data=f"manager_finish_work:{request.id}",
                ),
                InlineKeyboardButton(
                    text="🚫 Отменить заявку",
                    callback_data=f"manager_cancel_after_accept:{request.id}",
                ),
            ]
        )

    elif request.status in ("completed",):
        # Работа завершена — управление дальше за клиентом (оценка и отзыв, сделаем следующим шагом)
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Работа завершена",
                    callback_data="noop_completed",
                )
            ]
        )

    elif request.status in ("cancelled", "rejected"):
        # Отменённые/отклонённые — только статичное сообщение
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❌ Заявка закрыта",
                    callback_data="noop_closed",
                )
            ]
        )

    # На всякий случай: если почему-то нет ни одной кнопки — вернём пустую клаву,
    # чтобы edit_message_reply_markup не падал
    if not buttons:
        buttons = [[]]

    return InlineKeyboardMarkup(inline_keyboard=buttons)
