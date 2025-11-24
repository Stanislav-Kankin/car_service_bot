import logging
from datetime import datetime
from typing import Optional, List

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select, func

from app.config import config
from app.keyboards.main_kb import get_manager_main_kb, get_rating_kb
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, Car, ServiceCenter
from app.services.chat_service import update_chat_keyboard

router = Router()

PAGE_SIZE = 5


# ==========================
#   Проверка менеджера
# ==========================

async def is_manager(user_id: int) -> bool:
    """
    Проверяем, является ли пользователь менеджером автосервиса.

    Логика:
    - если user_id входит в ADMIN_USER_IDS → это администратор/менеджер;
    - иначе проверяем пользователя в БД:
        • пользователь существует
        • его роль == "service"
    """
    # 1. Глобальный админ
    if user_id in config.ADMIN_USER_IDS:
        return True

    # 2. Проверяем роль пользователя в БД
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

    if not user:
        return False

    return user.role == "service"


# ==========================
#   FSM для поиска
# ==========================

class ManagerSearchStates(StatesGroup):
    waiting_query = State()


# ==========================
#   Форматирование заявок
# ==========================

def _format_stage_times(request: Request) -> str:
    """
    Строка с временными метками переходов по стадиям для менеджера.
    """
    parts: List[str] = []

    if request.created_at:
        parts.append(f"📝 Создана: {request.created_at.strftime('%d.%m.%Y %H:%M')}")

    if request.accepted_at:
        parts.append(
            f"✅ Принята клиентом/сервисом: {request.accepted_at.strftime('%d.%m.%Y %H:%M')}"
        )

    if request.in_progress_at:
        parts.append(f"⚙️ В работе с: {request.in_progress_at.strftime('%d.%m.%Y %H:%M')}")

    if request.completed_at:
        parts.append(f"🏁 Завершена: {request.completed_at.strftime('%d.%m.%Y %H:%M')}")

    if request.rejected_at:
        parts.append(f"❌ Отклонена: {request.rejected_at.strftime('%d.%m.%Y %H:%M')}")

    if not parts:
        return "⏱ История стадий пока отсутствует."

    return "\n".join(parts)


def _format_request_short(req: Request, user: User, car: Optional[Car]) -> str:
    car_text = (
        f"{car.brand} {car.model} ({car.year or 'год не указан'}), {car.license_plate}"
        if car
        else "без привязанного авто"
    )
    created = req.created_at.strftime("%d.%m.%Y %H:%M") if req.created_at else "—"

    return (
        f"#{req.id} — {req.service_type}\n"
        f"👤 {user.full_name}\n"
        f"🚗 {car_text}\n"
        f"📅 {created}\n"
        f"📌 Статус: {req.status}"
    )


def _format_request_full(req: Request, user: User, car: Optional[Car]) -> str:
    car_text = (
        f"{car.brand} {car.model} ({car.year or 'год не указан'}), "
        f"{car.license_plate}, VIN: {car.vin or '—'}"
        if car
        else "без привязанного авто"
    )

    base = [
        f"📄 Заявка #{req.id}",
        "",
        f"👤 Клиент: {user.full_name}",
        f"📱 Телефон: {user.phone_number or 'не указан'}",
        "",
        f"🚗 Авто: {car_text}",
        f"🛠 Тип работ: {req.service_type}",
        "",
        f"📌 Текущий статус: {req.status}",
        "",
        "⏱ История стадий:",
        _format_stage_times(req),
    ]

    if req.manager_comment:
        base.extend(
            [
                "",
                "💬 Комментарий менеджера:",
                req.manager_comment,
            ]
        )

    return "\n".join(base)


# ==========================
#   Клавиатуры менеджера
# ==========================

def _get_request_actions_kb(req: Request) -> InlineKeyboardBuilder:
    """
    Клавиатура действий по заявке для менеджера.
    ВАЖНО: для завершённых/отклонённых только просмотр.
    """
    kb = InlineKeyboardBuilder()

    # Завершённые/отклонённые — только просмотр
    if req.status in ("completed", "rejected"):
        return kb

    # Логика переходов:
    # new/offer_sent/accepted_by_client -> можно принять
    if req.status in ("new", "offer_sent", "accepted_by_client"):
        kb.button(
            text="✅ Принять",
            callback_data=f"manager_set_status:accepted:{req.id}",
        )

    # accepted -> в работу
    if req.status in ("accepted", "accepted_by_client"):
        kb.button(
            text="⚙️ В работу",
            callback_data=f"manager_set_status:in_progress:{req.id}",
        )

    # in_progress -> завершить / отклонить
    if req.status == "in_progress":
        kb.button(
            text="🏁 Завершить",
            callback_data=f"manager_set_status:completed:{req.id}",
        )
        kb.button(
            text="❌ Отклонить",
            callback_data=f"manager_set_status:rejected:{req.id}",
        )

    kb.adjust(2)
    return kb


def _build_requests_list_kb(requests: list[Request]) -> InlineKeyboardBuilder:
    """
    Строим клавиатуру для списка заявок — кнопки "Открыть #id".
    """
    kb = InlineKeyboardBuilder()
    for req in requests:
        kb.button(
            text=f"🔍 Открыть #{req.id}",
            callback_data=f"manager_open_request:{req.id}",
        )
    kb.adjust(1)
    return kb


# ==========================
#   /manager — вход
# ==========================

@router.message(Command("manager"))
async def manager_command(message: Message):
    """
    /manager — вход в панель заявок автосервиса.
    Доступ:
      - ADMIN_USER_ID
      - пользователи с ролью 'service'
    """
    if not await is_manager(message.from_user.id):
        await message.answer("❌ Команда доступна только представителям автосервисов.")
        return

    await message.answer(
        "🛠 Панель заявок автосервиса.\n\n"
        "Выберите нужный раздел:",
        reply_markup=get_manager_main_kb(),
    )


# ==========================
#   Списки заявок
# ==========================

@router.callback_query(F.data == "manager_new_requests")
async def manager_new_requests(callback: CallbackQuery):
    """
    📥 Новые заявки.
    """
    await _send_requests_list(
        callback,
        title="📥 Новые заявки",
        status_filter=["new"],
        list_key="new",
        page=1,
    )


@router.callback_query(F.data == "manager_in_progress")
async def manager_in_progress(callback: CallbackQuery):
    """
    🔄 В обработке — принятые и в работе.
    """
    await _send_requests_list(
        callback,
        title="🔄 Заявки в обработке",
        status_filter=["accepted", "in_progress"],
        list_key="in_progress",
        page=1,
    )


@router.callback_query(F.data == "manager_scheduled")
async def manager_scheduled(callback: CallbackQuery):
    """
    📅 Записи — клиент уже подтвердил условия (accepted_by_client).
    """
    await _send_requests_list(
        callback,
        title="📅 Запланированные работы",
        status_filter=["accepted_by_client"],
        list_key="scheduled",
        page=1,
    )


@router.callback_query(F.data == "manager_archive")
async def manager_archive(callback: CallbackQuery):
    """
    📁 Архив — завершённые/отклонённые.
    """
    await _send_requests_list(
        callback,
        title="📁 Архив заявок",
        status_filter=["completed", "rejected"],
        list_key="archive",
        page=1,
    )


@router.callback_query(F.data.startswith("manager_list_page:"))
async def manager_list_page(callback: CallbackQuery):
    """
    Пагинация списков заявок менеджера.
    Формат callback_data: manager_list_page:<list_key>:<page>
    """
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, list_key, raw_page = callback.data.split(":")
        page = int(raw_page)
    except Exception:
        await callback.answer("Некорректные данные пагинации", show_alert=True)
        return

    if list_key == "noop":
        await callback.answer()
        return

    mapping = {
        "new": ("📥 Новые заявки", ["new"]),
        "in_progress": ("🔄 Заявки в обработке", ["accepted", "in_progress"]),
        "scheduled": ("📅 Запланированные работы", ["accepted_by_client"]),
        "archive": ("📁 Архив заявок", ["completed", "rejected"]),
    }

    title, statuses = mapping.get(list_key, ("📥 Новые заявки", ["new"]))

    await _send_requests_list(
        callback,
        title=title,
        status_filter=statuses,
        list_key=list_key,
        page=page,
    )


async def _send_requests_list(
    callback: CallbackQuery,
    title: str,
    status_filter: Optional[list[str]] = None,
    list_key: str = "new",
    page: int = 1,
):
    """
    Общая функция отправки списка заявок менеджеру.
    С учётом привязки к сервису и пагинации.
    """
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    if page < 1:
        page = 1

    # Определяем, к какому СТО относится менеджер
    sc_id = await get_manager_sc_id(callback.from_user.id)

    async with AsyncSessionLocal() as session:
        # Считаем общее количество заявок по фильтру
        count_stmt = select(func.count()).select_from(Request)
        if sc_id is not None:
            count_stmt = count_stmt.where(Request.service_center_id == sc_id)
        if status_filter:
            count_stmt = count_stmt.where(Request.status.in_(status_filter))

        total = (await session.execute(count_stmt)).scalar() or 0
        if total == 0:
            await callback.message.edit_text(
                f"{title}\n\nПо данному фильтру заявок не найдено.",
                reply_markup=get_manager_main_kb(),
            )
            await callback.answer()
            return

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > total_pages:
            page = total_pages

        offset = (page - 1) * PAGE_SIZE

        # Получаем нужную страницу
        stmt = (
            select(Request, User, Car)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
        )
        if sc_id is not None:
            stmt = stmt.where(Request.service_center_id == sc_id)
        if status_filter:
            stmt = stmt.where(Request.status.in_(status_filter))

        stmt = stmt.order_by(Request.created_at.desc()).offset(offset).limit(PAGE_SIZE)

        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        await callback.message.edit_text(
            f"{title}\n\nПо данному фильтру заявок не найдено.",
            reply_markup=get_manager_main_kb(),
        )
        await callback.answer()
        return

    requests = [r[0] for r in rows]

    lines = [f"{title} (стр. {page}/{total_pages})", ""]
    for req, user, car in rows:
        lines.append(_format_request_short(req, user, car))
        lines.append("")

    # Кнопки "Открыть #id"
    base_kb = _build_requests_list_kb(requests).as_markup()

    # Добавляем пагинацию
    nav_builder = InlineKeyboardBuilder()
    if total_pages > 1:
        if page > 1:
            nav_builder.button(
                text="⬅️ Назад",
                callback_data=f"manager_list_page:{list_key}:{page - 1}",
            )
        nav_builder.button(
            text=f"Стр. {page}/{total_pages}",
            callback_data="manager_list_page:noop:0",
        )
        if page < total_pages:
            nav_builder.button(
                text="Вперёд ➡️",
                callback_data=f"manager_list_page:{list_key}:{page + 1}",
            )
        nav_builder.adjust(3)

    nav_markup = nav_builder.as_markup()
    # Склеиваем клавиатуры: сначала заявки, потом навигация
    if nav_markup.inline_keyboard:
        base_kb.inline_keyboard.extend(nav_markup.inline_keyboard)

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=base_kb,
    )
    await callback.answer()


# ==========================
#   Поиск
# ==========================

@router.callback_query(F.data == "manager_search")
async def manager_search(callback: CallbackQuery, state: FSMContext):
    """
    Нажали "🔍 Поиск заявки" в /manager.
    """
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🔍 Введите текст для поиска заявок.\n"
        "Можно искать по имени клиента, телефону, госномеру, VIN, описанию.",
    )
    await state.set_state(ManagerSearchStates.waiting_query)
    await callback.answer()


@router.message(ManagerSearchStates.waiting_query)
async def manager_search_process(message: Message, state: FSMContext):
    """
    Обработка текстового запроса поиска.
    """
    if not await is_manager(message.from_user.id):
        await message.answer("❌ Нет доступа к поиску заявок.")
        return

    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите непустой поисковый запрос.")
        return

    like = f"%{query.upper()}%"

    # СТО менеджера (или None для админа)
    sc_id = await get_manager_sc_id(message.from_user.id)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Request, User, Car)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .where(
                func.upper(User.full_name).like(like)
                | func.upper(User.phone_number).like(like)
                | func.upper(Car.license_plate).like(like)
                | func.upper(Car.vin).like(like)
                | func.upper(Request.description).like(like)
            )
            .order_by(Request.created_at.desc())
            .limit(20)
        )

        if sc_id is not None:
            stmt = stmt.where(Request.service_center_id == sc_id)

        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        await message.answer(
            "Ничего не найдено по вашему запросу.\n"
            "Попробуйте ещё раз или откройте панель /manager."
        )
        await state.clear()
        return

    requests = [r[0] for r in rows]

    lines = ["🔍 Результаты поиска:", ""]
    for req, user, car in rows:
        lines.append(_format_request_short(req, user, car))
        lines.append("")

    kb = _build_requests_list_kb(requests)

    await message.answer(
        "\n".join(lines),
        reply_markup=kb.as_markup(),
    )
    await state.clear()


# ==========================
#   Открытие заявки менеджером
# ==========================

@router.callback_query(F.data.startswith("manager_open_request:"))
async def manager_open_request(callback: CallbackQuery):
    """
    Открытие полной информации по заявке из списка/поиска.
    Здесь же показываем времена стадий.
    """
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, raw_id = callback.data.split(":", 1)
        request_id = int(raw_id)
    except Exception:
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return

    # СТО менеджера (или None для админа)
    sc_id = await get_manager_sc_id(callback.from_user.id)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Request, User, Car)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .where(Request.id == request_id)
        )

        result = await session.execute(stmt)
        row = result.first()

    if not row:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    req, user, car = row

    # Проверка принадлежности заявки этому сервису
    if sc_id is not None and req.service_center_id != sc_id:
        await callback.answer("❌ У вас нет доступа к этой заявке.", show_alert=True)
        return

    text = _format_request_full(req, user, car)
    kb = _get_request_actions_kb(req)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup() if kb.buttons else None,
    )
    await callback.answer()


# ==========================
#   Изменение статуса заявки
# ==========================

@router.callback_query(F.data.startswith("manager_set_status:"))
async def manager_set_status(callback: CallbackQuery):
    """
    Менеджер меняет статус заявки из карточки /manager.

    Формат callback_data:
        manager_set_status:<status>:<request_id>
    """
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, status, raw_id = callback.data.split(":")
        request_id = int(raw_id)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # СТО менеджера (или None для админа)
    sc_id = await get_manager_sc_id(callback.from_user.id)

    # 1. Обновляем статус заявки
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Request).where(Request.id == request_id)
        )
        req = result.scalar_one_or_none()

        if not req:
            await callback.answer("Заявка не найдена", show_alert=True)
            return

        # Проверяем принадлежность заявки текущему сервису
        if sc_id is not None and req.service_center_id != sc_id:
            await callback.answer("❌ У вас нет прав изменять эту заявку.", show_alert=True)
            return

        # Не трогаем завершённые/отклонённые
        if req.status in ("completed", "rejected"):
            await callback.answer("Заявка уже завершена/отклонена.", show_alert=True)
            return

        now = datetime.now()

        # Применяем переходы
        if status == "accepted":
            req.status = "accepted"
            if not req.accepted_at:
                req.accepted_at = now

        elif status == "in_progress":
            req.status = "in_progress"
            if not req.in_progress_at:
                req.in_progress_at = now

        elif status == "completed":
            req.status = "completed"
            if not req.completed_at:
                req.completed_at = now

        elif status == "rejected":
            req.status = "rejected"
            if not req.rejected_at:
                req.rejected_at = now
        else:
            await callback.answer("Неизвестный статус", show_alert=True)
            return

        await session.commit()

    # 2. Ещё раз читаем заявку вместе с пользователем и машиной
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Request, User, Car)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .where(Request.id == request_id)
        )
        row = result.first()

    if not row:
        await callback.answer(
            "Заявка обновлена, но загрузить карточку не удалось.", show_alert=True
        )
        return

    req, user, car = row

    # 3. Уведомляем клиента о смене статуса
    reply_markup = None
    try:
        client_text: Optional[str] = None

        if req.status == "accepted":
            client_text = (
                f"✅ Ваша заявка #{req.id} принята автосервисом.\n"
                f"Скоро с вами свяжутся для уточнения деталей."
            )
        elif req.status == "in_progress":
            client_text = (
                f"⚙️ Ваша заявка #{req.id} сейчас в работе.\n"
                f"Автосервис выполняет согласованные работы."
            )
        elif req.status == "completed":
            client_text = (
                f"🏁 Работы по вашей заявке #{req.id} завершены.\n"
                f"Пожалуйста, оцените работу сервиса по шкале от 1 до 5."
            )
            # 👇 При завершении добавляем клавиатуру оценки
            reply_markup = get_rating_kb(req.id)
        elif req.status == "rejected":
            client_text = (
                f"❌ К сожалению, автосервис отклонил вашу заявку #{req.id}.\n"
                f"Вы можете создать новую заявку или выбрать другой сервис."
            )

        if client_text and user.telegram_id:
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=client_text,
                reply_markup=reply_markup,
            )
    except Exception as e:
        logging.error(
            f"❌ Не удалось отправить уведомление клиенту по заявке #{request_id}: {e}"
        )

    # 4. Обновляем карточку в /manager
    text = _format_request_full(req, user, car)
    kb = _get_request_actions_kb(req)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=kb.as_markup() if kb.buttons else None,
        )
    except Exception as e:
        logging.error(
            f"❌ Не удалось обновить сообщение менеджера по заявке #{request_id}: {e}"
        )

    # 5. Синхронизируем основную карточку в чате сервиса
    try:
        await update_chat_keyboard(callback.bot, request_id)
    except Exception as e:
        logging.error(f"❌ Не удалось обновить чат заявки #{request_id}: {e}")

    await callback.answer("Статус заявки обновлён.")


# ==========================
#   Вспомогалка: СТО менеджера
# ==========================

async def get_manager_sc_id(user_id: int) -> Optional[int]:
    """
    Возвращает id ServiceCenter, к которому относится менеджер.

    - Если это ADMIN_USER_ID — возвращаем None (видит все заявки).
    - Если пользователь — владелец сервиса, вернём id этого сервиса.
    """
    if user_id == config.ADMIN_USER_ID:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).join(
                User, ServiceCenter.owner_user_id == User.id
            ).where(User.telegram_id == user_id)
        )
        sc = result.scalar_one_or_none()
        return sc.id if sc else None
