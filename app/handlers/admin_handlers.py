import logging
from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode
from sqlalchemy import select, func

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import User, Request, ServiceCenter, Car
from app.keyboards.main_kb import SERVICE_SPECIALIZATION_OPTIONS

router = Router()
logger = logging.getLogger(__name__)


# ------------------------------
# Проверка прав администратора
# ------------------------------
def is_admin(user_id: int) -> bool:
    """
    Проверка: является ли пользователь администратором бота.

    Сейчас опираемся на config.ADMIN_USER_ID / ADMIN_USER_IDS.
    Если у тебя несколько админов, можно сделать set(...) в config.
    """
    # В логах у тебя печатается ADMIN_USER_IDS, но в config сейчас ADMIN_USER_ID.
    # Делаем универсально: поддерживаем и одиночный ID, и множество.
    admin_ids = getattr(config, "ADMIN_USER_IDS", None)
    if isinstance(admin_ids, set):
        return user_id in admin_ids

    single_admin_id = getattr(config, "ADMIN_USER_ID", None)
    return user_id == single_admin_id


# Словарь код -> человекочитаемая категория, по тем же кодам, что в регистрации СТО
SPEC_LABELS = {code: label for code, label in SERVICE_SPECIALIZATION_OPTIONS}


# ------------------------------
# Команда /admin
# ------------------------------
@router.message(F.text == "/admin")
async def admin_panel(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав администратора.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика", callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Пользователи", callback_data="admin_users"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏭 СТО", callback_data="admin_services"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Все заявки", callback_data="admin_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Создать заявку", callback_data="admin_create_request"
                )
            ],
        ]
    )

    await msg.answer(
        "🛠 <b>Панель администратора</b>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


# ------------------------------
# Статистика
# ------------------------------
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        total_users = await session.scalar(select(func.count(User.id)))
        total_requests = await session.scalar(select(func.count(Request.id)))
        completed = await session.scalar(
            select(func.count(Request.id)).where(Request.status == "completed")
        )
        in_progress = await session.scalar(
            select(func.count(Request.id)).where(Request.status == "in_progress")
        )

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"📝 Заявок всего: <b>{total_requests}</b>\n"
        f"✔️ Выполнено: <b>{completed}</b>\n"
        f"⚙️ В работе: <b>{in_progress}</b>\n"
    )

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()


# ------------------------------
# Список пользователей
# ------------------------------
@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).order_by(User.id.desc()))
        users = result.scalars().all()

    text_lines: list[str] = ["👥 <b>Пользователи</b>\n"]
    for u in users:
        role = u.role or "client"
        name = u.full_name or f"ID {u.telegram_id}"
        text_lines.append(
            f"{u.id}. {name} — <code>{role}</code>"
        )

    text = "\n".join(text_lines)

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()


# ------------------------------
# Список сервисов (СТО + категории)
# ------------------------------
@router.callback_query(F.data == "admin_services")
async def admin_services(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).order_by(ServiceCenter.id.asc())
        )
        services = result.scalars().all()

    lines: list[str] = ["🏭 <b>СТО</b>\n"]

    for s in services:
        codes = []
        if s.specializations:
            codes = [c.strip() for c in s.specializations.split(",") if c.strip()]

        labels = [SPEC_LABELS.get(code, code) for code in codes]
        categories_str = ", ".join(labels) if labels else "—"

        address = s.address or ""
        line = (
            f"{s.id}. <b>{s.name}</b>\n"
            f"   📍 {address}\n"
            f"   🧩 Категории: {categories_str}\n"
        )
        lines.append(line)

    text = "\n".join(lines) if services else "🏭 <b>СТО пока нет</b>"

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()


# ------------------------------
# Все заявки (с пользователем, авто, СТО и временем)
# ------------------------------
@router.callback_query(F.data == "admin_requests")
async def admin_all_requests(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Request, User, Car, ServiceCenter)
            .join(User, Request.user_id == User.id)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .join(
                ServiceCenter,
                Request.service_center_id == ServiceCenter.id,
                isouter=True,
            )
            .order_by(Request.created_at.desc())
            .limit(50)
        )
        result = await session.execute(stmt)
        rows = result.all()

    if not rows:
        await callback.message.edit_text(
            "📝 <b>Заявок пока нет</b>",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return

    lines: list[str] = ["📝 <b>Последние заявки (50)</b>\n"]

    for req, user, car, sc in rows:
        created_str = (
            req.created_at.strftime("%d.%m %H:%M") if req.created_at else "—"
        )

        user_name = user.full_name or f"ID {user.telegram_id}"
        car_str = ""
        if car:
            parts = [
                p for p in [
                    car.brand,
                    car.model,
                    str(car.year) if car.year else None,
                ] if p
            ]
            base = " ".join(parts) if parts else "Авто"
            plate = car.license_plate or ""
            car_str = f"{base} {plate}".strip()

        service_name = sc.name if sc else "—"

        lines.append(
            f"#{req.id}: <b>{req.service_type or req.category_code or 'Без типа'}</b> — "
            f"<code>{req.status}</code>\n"
            f"   👤 {user_name}\n"
            f"   🚗 {car_str}\n"
            f"   🏭 {service_name}\n"
            f"   🕒 {created_str}\n"
        )

    text = "\n".join(lines)

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await callback.answer()


# ------------------------------
# Заглушка для "Создать заявку" (пока не реализуем)
# ------------------------------
@router.callback_query(F.data == "admin_create_request")
async def admin_create_request_stub(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "➕ Создание заявки из админки пока не реализовано.\n"
        "Если нужно, можем добавить мастер создания заявки для тестов.",
        parse_mode=ParseMode.HTML,
    )
