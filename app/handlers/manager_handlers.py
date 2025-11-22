import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from sqlalchemy import select, func

from app.config import config
from app.keyboards.main_kb import get_manager_main_kb
from app.database.db import AsyncSessionLocal
from app.database.models import Request, User, Car

router = Router()


def is_manager(user_id: int) -> bool:
    """
    Пока считаем менеджером только ADMIN_USER_ID.
    При необходимости можно расширить логику (роль 'service' и т.п.).
    """
    return user_id == config.ADMIN_USER_ID


# ==========================
#   FSM для поиска заявок
# ==========================
class ManagerSearchStates(StatesGroup):
    waiting_query = State()


# ───────────────────────────────────────────────
# 📌 MANAGER: Просмотр заявки в ЛС (кнопка из группы)
# ───────────────────────────────────────────────
@router.callback_query(F.data.startswith("manager_view_request"))
async def manager_view_request(callback: CallbackQuery):
    """
    Открывает подсказку по заявке в ЛС менеджера.
    """
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, raw_id = callback.data.split(":")
        request_id = int(raw_id)
    except Exception:
        await callback.answer("Ошибка ID", show_alert=True)
        return

    logging.info(f"🔧 Manager callback: manager_view_request:{request_id}")

    await callback.message.answer(
        f"📋 Заявка #{request_id}\n"
        f"Чтобы оставить комментарий, перейдите в группу менеджеров и ответьте реплаем на сообщение с заявкой.",
    )

    await callback.answer()


# ==========================
#   /manager — панель
# ==========================
@router.message(Command("manager"))
async def manager_command(message: Message):
    """
    /manager — вход в панель заявок автосервиса.
    Пока доступно только ADMIN_USER_ID.
    При необходимости можно добавить проверку роли 'service' из БД.
    """
    if not is_manager(message.from_user.id):
        await message.answer("❌ Команда доступна только представителям автосервисов.")
        return

    await message.answer(
        "🛠 Панель заявок автосервиса.\n\n"
        "Используйте кнопки ниже для просмотра и поиска заявок.",
        reply_markup=get_manager_main_kb(),
    )


# ==========================
#   Вспомогалки
# ==========================
def _format_request_short(req: Request, car: Car | None, user: User) -> str:
    created = (
        req.created_at.strftime("%d.%m %H:%M")
        if isinstance(req.created_at, datetime)
        else str(req.created_at)
    )
    car_part = ""
    if car:
        car_part = f"{car.brand or ''} {car.model or ''} [{car.license_plate or 'без номера'}]".strip()
    return (
        f"#{req.id} • {req.service_type}\n"
        f"🚗 {car_part or 'Авто не указано'}\n"
        f"👤 {user.full_name} • {created}\n"
        f"📍 {req.location_description or '—'}\n"
        f"🔖 Статус: {req.status}\n"
    )


async def _send_manager_list(
    callback: CallbackQuery,
    title: str,
    status_filter: list[str] | None = None,
) -> None:
    """Выводит список заявок менеджеру по заданным статусам."""
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Request, User, Car)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .order_by(Request.created_at.desc())
            .limit(20)
        )
        if status_filter:
            stmt = stmt.where(Request.status.in_(status_filter))

        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        await callback.message.edit_text(
            f"{title}\n\nЗаявок не найдено.",
            reply_markup=get_manager_main_kb(),
        )
        await callback.answer()
        return

    lines = [f"📋 {title}", ""]
    for req, user, car in rows:
        lines.append(_format_request_short(req, car, user))
        lines.append("—")

    text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=get_manager_main_kb(),
    )
    await callback.answer()


# ==========================
#   Кнопки панели менеджера
# ==========================
@router.callback_query(F.data == "manager_new_requests")
async def manager_new_requests(callback: CallbackQuery):
    """
    📥 Новые заявки — статус 'new' и 'offer_sent'
    """
    await _send_manager_list(
        callback,
        title="📥 Новые заявки",
        status_filter=["new", "offer_sent"],
    )


@router.callback_query(F.data == "manager_in_progress")
async def manager_in_progress(callback: CallbackQuery):
    """
    🔄 В обработке — принятые и в работе.
    """
    await _send_manager_list(
        callback,
        title="🔄 Заявки в обработке",
        status_filter=["accepted", "in_progress"],
    )


@router.callback_query(F.data == "manager_scheduled")
async def manager_scheduled(callback: CallbackQuery):
    """
    📅 Записи — клиент уже подтвердил дату/условия.
    """
    await _send_manager_list(
        callback,
        title="📅 Запланированные работы",
        status_filter=["accepted_by_client"],
    )


@router.callback_query(F.data == "manager_archive")
async def manager_archive(callback: CallbackQuery):
    """
    📁 Архив — завершённые/отклонённые.
    """
    await _send_manager_list(
        callback,
        title="📁 Архив заявок",
        status_filter=["completed", "rejected"],
    )


@router.callback_query(F.data == "manager_settings")
async def manager_settings(callback: CallbackQuery):
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "⚙️ Настройки автосервиса будут вынесены сюда (название, адрес, контактный телефон и т.д.).\n\n"
        "Пока эта страница-заглушка.",
        reply_markup=get_manager_main_kb(),
    )
    await callback.answer()


# ==========================
#   Поиск заявки
# ==========================
@router.callback_query(F.data == "manager_search")
async def manager_search_start(callback: CallbackQuery, state: FSMContext):
    """
    Старт поиска: просим ввести номер заявки или госномер.
    """
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await state.set_state(ManagerSearchStates.waiting_query)
    await callback.message.edit_text(
        "🔍 Поиск заявки.\n\n"
        "Введите:\n"
        "• номер заявки (например: 15)\n"
        "ИЛИ\n"
        "• госномер авто (полностью или часть, например: А123, 123РУ, КРА…)\n\n"
        "Для отмены — /manager",
    )
    await callback.answer()


@router.message(ManagerSearchStates.waiting_query)
async def manager_search_process(message: Message, state: FSMContext):
    """
    Обработка строки поиска: номер заявки или госномер.
    """
    if not is_manager(message.from_user.id):
        await message.answer("❌ Нет доступа")
        await state.clear()
        return

    query = (message.text or "").strip()
    if not query:
        await message.answer("Введите номер заявки или госномер.")
        return

    async with AsyncSessionLocal() as session:
        rows = []

        # Поиск по ID заявки
        if query.isdigit():
            req_id = int(query)
            stmt = (
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id, isouter=True)
                .where(Request.id == req_id)
            )
            result = await session.execute(stmt)
            rows = result.all()

        # Поиск по госномеру
        if not rows:
            pattern = f"%{query.upper()}%"
            stmt = (
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id, isouter=True)
                .where(
                    func.upper(Car.license_plate).like(pattern)
                )
                .order_by(Request.created_at.desc())
                .limit(20)
            )
            result = await session.execute(stmt)
            rows = result.all()

    if not rows:
        await message.answer(
            "Ничего не найдено по вашему запросу.\n"
            "Попробуйте ещё раз или откройте панель /manager."
        )
        return

    lines = ["🔍 Результаты поиска:", ""]
    for req, user, car in rows:
        lines.append(_format_request_short(req, car, user))
        lines.append("—")

    await message.answer("\n".join(lines), reply_markup=get_manager_main_kb())
    await state.clear()
