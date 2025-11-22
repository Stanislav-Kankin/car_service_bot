import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, Car, ServiceCenter


def _format_status(status: Optional[str]) -> str:
    """
    Человекочитаемый статус заявки для отображения в карточке.
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
    Формирует inline-клавиатуру под сообщение в группе менеджеров
    в зависимости от текущего статуса заявки.

    Логика:

    - new:
        • 💬 Ответить клиенту (цена/сроки)
        • ❌ Отклонить заявку (с комментарием)
    - offer_sent:
        • только 🔄 Обновить (ждём клиента)
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
        • 🔄 Обновить (по факту уже финальные)
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
            f"📍 Местоположение:\n"
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
        f"👤 Клиент: {user.full_name or 'Не указано'}\n"
        f"📞 Телефон: {user.phone_number or 'Не указан'}\n"
        f"🆔 ID пользователя: {user.telegram_id}\n\n"
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
    Создать/отправить сообщение о заявке в группу/ЛС автосервиса.

    Логика:
    - Берём заявку, пользователя, авто и сервис.
    - Определяем, куда слать:
        • если у заявки есть service_center:
            - если send_to_group и manager_chat_id → туда
            - если send_to_owner → в ЛС владельцу
            - если оба → основной канал = группа, вторичный = ЛС
        • иначе — fallback на глобальный MANAGER_CHAT_ID (обратная совместимость)
    - В основной канал сохраняем message_id в request.chat_message_id
      (для update_chat_keyboard).
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

            primary_chat_id: Optional[int] = None
            extra_chat_ids: list[int] = []

            # Определяем основной и дополнительные каналы для сервиса
            owner_telegram_id: Optional[int] = None
            if service_center and service_center.owner_user_id:
                owner_res = await session.execute(
                    select(User).where(User.id == service_center.owner_user_id)
                )
                owner = owner_res.scalar_one_or_none()
                if owner and owner.telegram_id:
                    owner_telegram_id = owner.telegram_id

            if service_center:
                # приоритет: группа → ЛС
                if service_center.send_to_group and service_center.manager_chat_id:
                    primary_chat_id = service_center.manager_chat_id

                if service_center.send_to_owner and owner_telegram_id:
                    if primary_chat_id is None:
                        primary_chat_id = owner_telegram_id
                    else:
                        extra_chat_ids.append(owner_telegram_id)

            # Fallback на глобальный MANAGER_CHAT_ID
            if primary_chat_id is None:
                if not config.MANAGER_CHAT_ID:
                    logging.error("❌ MANAGER_CHAT_ID не задан и нет service_center для заявки")
                    return
                try:
                    primary_chat_id = int(config.MANAGER_CHAT_ID)
                except ValueError:
                    logging.error(
                        f"❌ Некорректный MANAGER_CHAT_ID: {config.MANAGER_CHAT_ID}"
                    )
                    return

            text = _format_request_text(request, user, car, service_center)
            keyboard = _build_chat_keyboard(request)

            async def _send_to_chat(chat_id: int) -> Optional[int]:
                msg = None
                file_id = None
                if request.photo_file_id:
                    file_id = request.photo_file_id.split(",")[0].strip() or None

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

                if msg is None:
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
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


async def update_chat_keyboard(bot: Bot, request_id: int) -> None:
    """
    Обновить inline-клавиатуру под сообщением заявки в чате сервиса.
    Используется после изменения статуса/данных заявки.

    Логика выбора чата такая же, как в create_request_chat:
    - если есть service_center:
        • если send_to_group и manager_chat_id → туда
        • иначе, если send_to_owner → ЛС владельца
    - иначе — fallback на MANAGER_CHAT_ID
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Request, ServiceCenter)
                .join(
                    ServiceCenter,
                    Request.service_center_id == ServiceCenter.id,
                    isouter=True,
                )
                .where(Request.id == request_id)
            )
            row = result.first()
            if not row:
                logging.error(
                    f"❌ update_chat_keyboard: заявка #{request_id} не найдена"
                )
                return

            request, service_center = row

            if not request.chat_message_id:
                logging.warning(
                    f"⚠️ update_chat_keyboard: у заявки #{request_id} нет chat_message_id, нечего обновлять"
                )
                return

            primary_chat_id: Optional[int] = None

            owner_telegram_id: Optional[int] = None
            if service_center and service_center.owner_user_id:
                owner_res = await session.execute(
                    select(User).where(User.id == service_center.owner_user_id)
                )
                owner = owner_res.scalar_one_or_none()
                if owner and owner.telegram_id:
                    owner_telegram_id = owner.telegram_id

            if service_center:
                if service_center.send_to_group and service_center.manager_chat_id:
                    primary_chat_id = service_center.manager_chat_id
                elif service_center.send_to_owner and owner_telegram_id:
                    primary_chat_id = owner_telegram_id

            if primary_chat_id is None:
                if not config.MANAGER_CHAT_ID:
                    logging.error("❌ MANAGER_CHAT_ID не задан и не удалось определить чат сервиса")
                    return
                try:
                    primary_chat_id = int(config.MANAGER_CHAT_ID)
                except ValueError:
                    logging.error(
                        f"❌ Некорректный MANAGER_CHAT_ID: {config.MANAGER_CHAT_ID}"
                    )
                    return

            keyboard = _build_chat_keyboard(request)

            try:
                await bot.edit_message_reply_markup(
                    chat_id=primary_chat_id,
                    message_id=request.chat_message_id,
                    reply_markup=keyboard,
                )
                logging.info(
                    f"🔧 update_chat_keyboard #{request_id}, status={request.status}, chat_id={primary_chat_id}"
                )
            except Exception as e:
                if "message is not modified" in str(e):
                    logging.info(
                        f"ℹ️ Клавиатура для заявки #{request_id} уже актуальна, "
                        f"Telegram вернул 'message is not modified'"
                    )
                else:
                    logging.error(
                        f"❌ Не удалось обновить клавиатуру чата для заявки #{request_id}: {e}"
                    )

        except Exception as e:
            logging.error(f"❌ Ошибка в update_chat_keyboard для заявки #{request_id}: {e}")
