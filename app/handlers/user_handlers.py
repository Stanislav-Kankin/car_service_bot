from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
)

from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func

from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
import logging

from app.services.notification_service import notify_manager_about_new_request
from app.services.bonus_service import add_bonus, get_user_balance
from app.database.models import User, Car, Request, ServiceCenter
from app.database.comment_models import Comment
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import (
    get_main_kb, get_registration_kb,
    get_phone_reply_kb, get_garage_kb,
    get_car_management_kb, get_car_cancel_kb,
    get_service_types_kb, get_tire_subtypes_kb,
    get_electric_subtypes_kb, get_aggregates_subtypes_kb,
    get_photo_skip_kb, get_request_confirm_kb,
    get_delete_confirm_kb, get_history_kb, get_edit_cancel_kb,
    get_can_drive_kb, get_location_reply_kb, get_role_kb,
    get_manager_main_kb, get_service_notifications_kb,
    get_service_specializations_kb, get_reset_profile_kb,
    get_search_radius_kb,
    get_time_slot_kb,
    get_request_edit_kb,
)

from app.config import config

logger = logging.getLogger(__name__)


class CarForm(StatesGroup):
    brand = State()
    model = State()
    year = State()
    vin = State()
    license_plate = State()
    # состояния для редактирования
    edit_brand = State()
    edit_model = State()
    edit_year = State()
    edit_vin = State()
    edit_license_plate = State()


class RequestForm(StatesGroup):
    # Шаг выбора автомобиля
    car_selection = State()

    # Шаг выбора автосервиса из подходящих
    service_center = State()

    # Внутренний под-диалог "Найти ближайший" внутри заявки
    nearest_radius = State()
    nearest_location = State()

    # Основной тип услуги (группа работ)
    service_type = State()
    # Уточняющий тип/подтип услуги внутри группы
    service_subtype = State()

    # Остальные шаги заявки
    description = State()
    photo = State()
    can_drive = State()
    location = State()
    # шаг ввода даты (текстом)
    preferred_date = State()
    # шаг выбора интервала времени по кнопкам
    preferred_time_slot = State()
    # финальное подтверждение
    confirm = State()
    # редактирование описания перед подтверждением
    edit_description = State()


class Registration(StatesGroup):
    role = State()
    name = State()
    service_name = State()
    service_address = State()
    service_location = State()
    service_specializations = State()
    phone = State()
    notifications = State()
    group_chat = State()


class ProfileStates(StatesGroup):
    waiting_new_phone = State()


class ServiceSearchStates(StatesGroup):
    """
    FSM для поиска сервиса (по радиусу/гео).
    Пока минимум — одно состояние, когда ждём геолокацию.
    """
    radius = State()
    location = State()


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    logger.info(f"🔄 Обработка /start для пользователя {message.from_user.id}")

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()

            # 1. Пользователя нет — новая регистрация
            if not user:
                logger.info(f"🆕 Новый пользователь {message.from_user.id}")
                await message.answer(
                    "👋 Добро пожаловать в CAR SERVICE BOT!\n\n"
                    "Я помогу вам с обслуживанием вашего автомобиля: "
                    "запись на сервис, шиномонтаж, эвакуатор и многое другое.\n\n"
                    "Для начала работы нужно пройти простую регистрацию:",
                    reply_markup=get_registration_kb(),
                )
                return

            # 2. Профиль есть, но заполнен не до конца
            if not user.role or not user.phone_number:
                logger.info(
                    f"ℹ Пользователь {message.from_user.id} есть в БД, "
                    f"но профиль неполный (role={user.role!r}, phone={user.phone_number!r}) — "
                    f"запускаем регистрацию заново"
                )
                await message.answer(
                    "👋 Похоже, ваш профиль заполнён не полностью.\n"
                    "Пройдите регистрацию ещё раз:",
                    reply_markup=get_registration_kb(),
                )
                return

            # 3. Пользователь — автосервис
            if user.role == "service":
                sc_result = await session.execute(
                    select(ServiceCenter).where(ServiceCenter.owner_user_id == user.id)
                )
                service_center = sc_result.scalar_one_or_none()

                # На всякий случай — сервис не найден
                if not service_center:
                    logger.warning(
                        f"⚠️ Для пользователя {message.from_user.id} role=service "
                        f"не найден ServiceCenter"
                    )
                    await message.answer(
                        "⚠️ Ваш профиль обозначен как автосервис, "
                        "но карточка сервиса не найдена.\n\n"
                        "Пройдите регистрацию ещё раз:",
                        reply_markup=get_registration_kb(),
                    )
                    return

                # Выбрана группа, но ещё не привязали manager_chat_id
                if service_center.send_to_group and not service_center.manager_chat_id:
                    await message.answer(
                        "⚠️ Вы выбрали получать заявки в группу, но она ещё не привязана.\n\n"
                        "1️⃣ Добавьте бота в нужную группу и сделайте его администратором.\n"
                        "2️⃣ В этой группе отправьте команду /bind_group.\n\n"
                        "После этого заявки начнут приходить в группу.",
                    )
                    return

                # Обычный случай: сервис уже настроен
                logger.info(
                    f"✅ Пользователь {message.from_user.id} уже зарегистрирован как автосервис"
                )
                await message.answer(
                    "🛠 Вы уже зарегистрированы как автосервис.\n\n"
                    "Используйте панель ниже или команду /manager для работы с заявками.\n\n"
                    "Чтобы привязать или поменять группу для заявок:\n"
                    "• добавьте бота в нужную группу и сделайте админом;\n"
                    "• отправьте в этой группе команду <code>/bind_group</code>.",
                    parse_mode="HTML",
                    reply_markup=get_manager_main_kb(),
                )
                return

            # 4. Обычный клиент
            logger.info(
                f"✅ Пользователь {message.from_user.id} уже зарегистрирован как клиент"
            )
            await message.answer(
                "🏠 Вы уже зарегистрированы. Главное меню:",
                reply_markup=get_main_kb(),
            )

        except Exception as e:
            logger.error(f"❌ Ошибка при обработке /start: {e}")
            await message.answer(
                "❌ Произошла ошибка при запуске. Попробуйте позже."
            )


@router.callback_query(F.data == "cancel_reset_registration")
async def cancel_reset_registration(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отменено. Регистрация не сброшена.")
    await callback.answer()


@router.callback_query(F.data == "confirm_reset_registration")
async def confirm_reset_registration(callback: CallbackQuery, state: FSMContext):
    """
    Подтверждение сброса регистрации:
    - очищаем phone_number
    - (опционально можно сбросить роль/поля сервиса, если решишь)
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.edit_text(
                "Вы ещё не зарегистрированы. Отправьте /start, чтобы начать."
            )
            await callback.answer()
            return

        # Сбрасываем телефон
        user.phone_number = None

        # Если хочешь заодно сбрасывать сервисные поля, можно раскомментировать:
        # user.role = "client"
        # user.service_name = None
        # user.service_address = None

        await session.commit()

    await state.clear()

    await callback.message.edit_text(
        "✅ Ваш номер телефона сброшен.\n\n"
        "Чтобы пройти регистрацию заново, отправьте команду /start.",
    )
    await callback.answer()


@router.message(Command("reset"))
async def cmd_reset_profile(message: Message, state: FSMContext):
    """
    Меню сброса профиля:
    1) Полный сброс (роль/данные сервиса/телефон)
    2) Только смена номера телефона
    """
    await state.clear()
    await message.answer(
        "Что вы хотите сделать с профилем?",
        reply_markup=get_reset_profile_kb(),
    )


@router.callback_query(F.data == "reset_profile_full")
async def reset_profile_full(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("❌ Профиль не найден. Нажмите /start.", show_alert=True)
            return

        # Сбрасываем ключевые поля профиля,
        # но НЕ трогаем бонусы, авто и заявки
        user.phone_number = None

        # ВАЖНО: не ставим None в поле с NOT NULL
        # Превращаем любого в клиента
        user.role = "client"

        user.service_name = None
        user.service_address = None

        # Если был владельцем СТО — отвяжем, но не удаляем сам сервис
        sc_result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.owner_user_id == user.id)
        )
        service_center = sc_result.scalar_one_or_none()
        if service_center:
            service_center.owner_user_id = None

        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        "✅ Ваш профиль сброшен.\n\n"
        "Теперь вы можете заново зарегистрироваться как клиент или как автосервис.\n"
        "Просто отправьте команду /start.",
    )
    await callback.answer()


@router.callback_query(F.data == "reset_profile_phone")
async def reset_profile_phone(callback: CallbackQuery, state: FSMContext):
    """
    Вариант 2: меняем только номер телефона.
    Бонусы, авто, заявки и роль остаются.
    """
    await state.set_state(ProfileStates.waiting_new_phone)

    # убираем inline-клавиатуру у старого сообщения (по возможности)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # шлём новое сообщение с reply-клавой
    await callback.message.answer(
        "Введите новый номер телефона или отправьте его кнопкой ниже:",
        reply_markup=get_phone_reply_kb(),
    )

    await callback.answer()


@router.message(ProfileStates.waiting_new_phone)
async def process_new_phone(message: Message, state: FSMContext):
    """
    Записываем новый телефон в профиль пользователя.
    """
    if message.contact and message.contact.phone_number:
        new_phone = message.contact.phone_number
    else:
        new_phone = (message.text or "").strip()

    if not new_phone:
        await message.answer(
            "❌ Не удалось прочитать номер телефона. "
            "Попробуйте ещё раз или используйте кнопку отправки контакта.",
            reply_markup=get_phone_reply_kb(),
        )
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Профиль не найден. Нажмите /start для регистрации.")
            await state.clear()
            return

        user.phone_number = new_phone
        await session.commit()

    await state.clear()

    # ✅ Сначала убираем реплай-клавиатуру
    await message.answer(
        "✅ Номер телефона обновлён.",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Потом показываем главное меню
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_kb(),
    )


# Обработчик кнопки "Назад в меню"
@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🏠 Главное меню\n\nВыберите действие:",
        reply_markup=get_main_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "service_centers_list")
async def service_centers_list(callback: CallbackQuery, state: FSMContext):
    """
    Показать пользователю список доступных автосервисов.
    Показываем только активные СТО (есть владелец),
    плюс, если есть координаты — даём ссылку на карту.
    """
    await state.clear()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.owner_user_id.isnot(None))
        )
        services = result.scalars().all()

    if not services:
        await callback.message.edit_text(
            "🏭 Пока нет доступных автосервисов.\n\n"
            "Попробуйте позже.",
            reply_markup=get_main_kb(),
        )
        await callback.answer()
        return

    lines = ["🏭 <b>Список автосервисов</b>\n"]
    for sc in services:
        rating_text = ""
        if sc.ratings_count and sc.ratings_count > 0:
            rating_text = f"⭐ {sc.rating:.1f} ({sc.ratings_count} оценок)"

        # ссылка на карту, если есть координаты
        geo_link = ""
        if sc.location_lat is not None and sc.location_lon is not None:
            geo_url = (
                f"https://www.google.com/maps?q={sc.location_lat},{sc.location_lon}"
            )
            geo_link = (
                f"  🌍 <a href='{geo_url}'>Открыть на карте</a>\n"
            )

        lines.append(
            f"• <b>{sc.name}</b>\n"
            f"  📍 {sc.address or 'Адрес не указан'}\n"
            f"  ☎️ {sc.phone or 'Телефон не указан'}\n"
            f"  {rating_text}\n"
            f"{geo_link}"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_main_kb(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


# Обработчик нажатия на кнопку "Зарегистрироваться"
@router.callback_query(F.data == "start_registration")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    """
    Первый шаг регистрации: выбор роли (клиент / автосервис).
    """
    await state.clear()
    await callback.message.edit_text(
        "Кто вы?\n\n"
        "Выберите один из вариантов ниже:",
        reply_markup=get_role_kb(),
    )
    await state.set_state(Registration.role)
    await callback.answer()


# Обработчик "Не сейчас" при регистрации
@router.callback_query(F.data == "skip_registration")
async def skip_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Вы можете зарегистрироваться позже.\n\n"
        "Главное меню:",
        reply_markup=get_main_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_registration")
async def back_to_registration(callback: CallbackQuery, state: FSMContext):
    """
    Возврат к экрану с предложением зарегистрироваться.
    """
    await state.clear()
    await callback.message.edit_text(
        "Для начала работы нужно пройти простую регистрацию:",
        reply_markup=get_registration_kb(),
    )
    await callback.answer()


@router.callback_query(Registration.role, F.data.in_(["reg_role_client", "reg_role_service"]))
async def choose_role(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбирает роль: клиент или автосервис.
    """
    if callback.data == "reg_role_client":
        role = "client"
        role_text = "клиент"
    else:
        role = "service"
        role_text = "представитель автосервиса"

    await state.update_data(role=role)

    await callback.message.edit_text(
        f"Отлично, вы указали, что вы — {role_text}.\n\n"
        "Теперь введите ваше полное имя (как в профиле или как удобно к вам обращаться):",
        reply_markup=None,
    )
    await state.set_state(Registration.name)
    await callback.answer()


# Обработчик имени при регистрации
@router.message(Registration.name)
async def process_name_registration(message: Message, state: FSMContext):
    name = (message.text or "").strip()

    if len(name) < 2:
        await message.answer(
            "❌ Имя слишком короткое. Пожалуйста, введите полное имя:",
        )
        return

    data = await state.get_data()
    role = data.get("role") or "client"

    await state.update_data(name=name)

    # Если это клиент — сразу просим телефон
    if role == "client":
        await message.answer(
            f"✅ Приятно познакомиться, {name}!\n\n"
            "Теперь нажмите на кнопку ниже, чтобы отправить номер телефона:",
            reply_markup=get_phone_reply_kb(),
        )
        await state.set_state(Registration.phone)
    else:
        # Автосервис — спрашиваем название сервиса
        await message.answer(
            f"✅ Отлично, {name}!\n\n"
            "Укажите, пожалуйста, <b>название автосервиса</b> "
            "(как его видит клиент, например, «СТО АвтоЛюкс»):",
            parse_mode="HTML",
        )
        await state.set_state(Registration.service_name)


@router.message(Registration.service_name)
async def process_service_name(message: Message, state: FSMContext):
    service_name = (message.text or "").strip()
    if len(service_name) < 2:
        await message.answer(
            "❌ Название слишком короткое. Пожалуйста, укажите корректное название сервиса:"
        )
        return

    await state.update_data(service_name=service_name)

    await message.answer(
        "Теперь укажите, пожалуйста, <b>адрес автосервиса</b>.\n\n"
        "Можно в свободной форме: город, улица, дом, ориентиры.",
        parse_mode="HTML",
    )
    await state.set_state(Registration.service_address)


@router.message(Registration.service_address)
async def process_service_address(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if len(address) < 5:
        await message.answer(
            "❌ Адрес слишком короткий. Пожалуйста, укажите более подробный адрес:"
        )
        return

    await state.update_data(service_address=address)

    data = await state.get_data()
    role = data.get("role") or "client"

    # Для автосервиса — сразу спрашиваем расположение на карте
    if role == "service":
        await message.answer(
            "Теперь укажите <b>расположение автосервиса</b>.\n\n"
            "Лучше всего отправить геолокацию через кнопку ниже.\n"
            "Если хотите пропустить этот шаг — напишите «Пропустить».",
            parse_mode="HTML",
            reply_markup=get_location_reply_kb(),  # уже есть клавиатура с 📍 и «Пропустить»
        )
        await state.set_state(Registration.service_location)
        return

    # Теоретически сюда клиент не попадёт, но оставим фоллбек на телефон
    await message.answer(
        "Отлично! Теперь нажмите на кнопку ниже, чтобы отправить номер телефона:",
        reply_markup=get_phone_reply_kb(),
    )
    await state.set_state(Registration.phone)


# гео от сервиса
@router.message(Registration.service_location, F.location)
async def process_service_location_geo(message: Message, state: FSMContext):
    """
    Автосервис отправил геолокацию — сохраняем координаты точки сервиса.
    """
    loc = message.location

    await state.update_data(
        service_location_lat=loc.latitude,
        service_location_lon=loc.longitude,
    )

    # ✅ Убираем клавиатуру с гео
    await message.answer(
        "✅ Локация сервиса получена.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await message.answer(
        "Отлично! Теперь выберите, <b>какие виды работ вы выполняете</b>.\n\n"
        "Можно выбрать несколько пунктов, нажимая на них.\n"
        "Когда закончите — нажмите «✅ Готово».\n\n"
        "Если вы готовы принимать любые заявки, нажмите «⏭️ Пропустить».",
        parse_mode="HTML",
        reply_markup=get_service_specializations_kb(),
    )
    await state.set_state(Registration.service_specializations)


# текст / «пропустить»
@router.message(Registration.service_location)
async def process_service_location_text(message: Message, state: FSMContext):
    """
    Обработка текстового ответа на шаге расположения сервиса.
    Если пользователь пишет «Пропустить» — координаты остаются пустыми.
    """
    text = (message.text or "").strip().lower()

    if "пропустить" in text or "⏭️" in text:
        # Явно решили не указывать координаты
        await state.update_data(
            service_location_lat=None,
            service_location_lon=None,
        )
    else:
        # Адрес мы уже сохранили на предыдущем шаге в service_address,
        # здесь дополнительные текстовые данные можно игнорировать
        await state.update_data(
            service_location_lat=None,
            service_location_lon=None,
        )

    # ✅ Убираем клавиатуру с гео / текстом
    await message.answer(
        "✅ Локация сервиса сохранена.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await message.answer(
        "Отлично! Теперь выберите, <b>какие виды работ вы выполняете</b>.\n\n"
        "Можно выбрать несколько пунктов, нажимая на них.\n"
        "Когда закончите — нажмите «✅ Готово».\n\n"
        "Если вы готовы принимать любые заявки, нажмите «⏭️ Пропустить».",
        parse_mode="HTML",
        reply_markup=get_service_specializations_kb(),
    )
    await state.set_state(Registration.service_specializations)


@router.callback_query(
    Registration.service_specializations,
    F.data.startswith("spec_toggle:")
)
async def toggle_service_specialization(callback: CallbackQuery, state: FSMContext):
    """
    Переключение отдельной специализации (выбрана/не выбрана).
    """
    _, code = callback.data.split(":", maxsplit=1)

    data = await state.get_data()
    selected = set(data.get("service_specializations") or [])

    if code in selected:
        selected.remove(code)
    else:
        selected.add(code)

    await state.update_data(service_specializations=list(selected))

    # Обновляем клавиатуру с учетом выбранных пунктов
    await callback.message.edit_reply_markup(
        reply_markup=get_service_specializations_kb(selected)
    )
    await callback.answer()


@router.callback_query(
    Registration.service_specializations,
    F.data == "spec_done",
)
async def done_service_specializations(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал «Готово».
    Если ничего не выбрано — просим либо выбрать, либо нажать «Пропустить».
    """
    data = await state.get_data()
    selected = data.get("service_specializations") or []

    if not selected:
        await callback.answer(
            "Выберите хотя бы одну специализацию или нажмите «Пропустить».",
            show_alert=True,
        )
        return

    # Снимаем inline-клавиатуру со старого сообщения (не обязательно, но аккуратно)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Отправляем НОВОЕ сообщение с reply-клавиатурой (это уже можно)
    await callback.message.answer(
        "Отлично! Теперь нажмите на кнопку ниже, чтобы отправить номер телефона:",
        reply_markup=get_phone_reply_kb(),
    )

    await state.set_state(Registration.phone)
    await callback.answer()


@router.callback_query(
    Registration.service_specializations,
    F.data == "spec_skip",
)
async def skip_service_specializations(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь решил принимать любые заявки — не задаём специализации.
    specializations в БД останется NULL → трактуем как «универсальный сервис».
    """
    await state.update_data(service_specializations=None)

    # Убираем inline-клаву
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Новое сообщение с reply-клавиатурой
    await callback.message.answer(
        "Хорошо, вы будете получать <b>все типы заявок</b>.\n\n"
        "Теперь нажмите на кнопку ниже, чтобы отправить номер телефона:",
        parse_mode="HTML",
        reply_markup=get_phone_reply_kb(),
    )

    await state.set_state(Registration.phone)
    await callback.answer()


@router.message(Registration.phone)
async def process_phone_registration(message: Message, state: FSMContext):
    """
    Завершение шага регистрации:
    - получаем телефон (контакт),
    - создаём/обновляем User,
    - при необходимости создаём/обновляем ServiceCenter,
    - коммитим всё одной транзакцией.
    """
    # Должен прийти именно контакт
    if not message.contact or not message.contact.phone_number:
        await message.answer(
            "📱 Пожалуйста, используйте кнопку для отправки номера телефона:",
            reply_markup=get_phone_reply_kb(),
        )
        return

    phone_number = message.contact.phone_number

    # Сразу убираем клавиатуру с номером
    await message.answer(
        "✅ Номер телефона получен.",
        reply_markup=ReplyKeyboardRemove(),
    )

    data = await state.get_data()
    name = data.get("name") or (message.from_user.full_name or "").strip() or "Без имени"
    role = data.get("role") or "client"
    service_name = data.get("service_name")
    service_address = data.get("service_address")
    service_specializations = data.get("service_specializations")  # может быть None/список

    # Координаты сервиса (если проходили шаг гео)
    service_location_lat = data.get("service_location_lat")
    service_location_lon = data.get("service_location_lon")

    async with AsyncSessionLocal() as session:
        try:
            # --- 1. Находим или создаём пользователя ---
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user: User | None = result.scalar_one_or_none()
            is_new_user = user is None

            if user:
                # Обновляем существующего
                user.full_name = name
                user.phone_number = phone_number
                user.role = role
                if role == "service":
                    user.service_name = service_name or name
                    user.service_address = service_address
                else:
                    user.service_name = None
                    user.service_address = None
            else:
                # Создаём нового
                user = User(
                    telegram_id=message.from_user.id,
                    full_name=name,
                    phone_number=phone_number,
                    role=role,
                    service_name=service_name if role == "service" else None,
                    service_address=service_address if role == "service" else None,
                )
                session.add(user)

            service_center_id: int | None = None

            # --- 2. Если это автосервис — создаём/обновляем ServiceCenter ---
            if role == "service":
                sc_result = await session.execute(
                    select(ServiceCenter).where(ServiceCenter.owner_user_id == user.id)
                )
                service_center: ServiceCenter | None = sc_result.scalar_one_or_none()

                if not service_center:
                    service_center = ServiceCenter(
                        name=user.service_name or user.full_name,
                        address=user.service_address,
                        phone=user.phone_number,
                        owner_user_id=user.id,
                        location_lat=service_location_lat,
                        location_lon=service_location_lon,
                        send_to_owner=True,
                        send_to_group=False,
                        manager_chat_id=None,
                    )
                    session.add(service_center)
                else:
                    service_center.name = user.service_name or user.full_name
                    service_center.address = user.service_address
                    service_center.phone = user.phone_number

                    if (
                        service_location_lat is not None
                        and service_location_lon is not None
                    ):
                        service_center.location_lat = service_location_lat
                        service_center.location_lon = service_location_lon

                # Специализации сервиса
                if service_specializations is not None:
                    if service_specializations:
                        service_center.specializations = ",".join(service_specializations)
                    else:
                        service_center.specializations = None

            # --- 3. Один общий коммит ---
            await session.commit()

            # Обновляем объекты в памяти
            await session.refresh(user)
            if role == "service":
                await session.refresh(service_center)
                service_center_id = service_center.id
                logging.info(
                    f"✅ Зарегистрирован/обновлён автосервис для пользователя {message.from_user.id} "
                    f"(ServiceCenter id={service_center.id}, "
                    f"specializations={service_center.specializations!r}, "
                    f"location=({service_center.location_lat}, {service_center.location_lon}))"
                )
            else:
                logging.info(
                    f"✅ Пользователь {message.from_user.id} зарегистрирован/обновлён как клиент "
                    f"(role={role}, phone={phone_number})"
                )

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении регистрации: {e}")
            await message.answer(
                "❌ Произошла ошибка при сохранении данных. Попробуйте позже.",
            )
            await state.clear()
            return

    # Сохраняем id в FSM (на всякий случай)
    await state.update_data(user_id=user.id, service_center_id=service_center_id)

    # --- 4. Бонус за регистрацию только для новых ---
    if is_new_user:
        try:
            await add_bonus(
                message.from_user.id,
                "register",
                description="Регистрация в боте",
            )
        except Exception as bonus_err:
            logging.error(f"❌ Ошибка начисления бонуса за регистрацию: {bonus_err}")

    # --- 5. Продолжение сценария в зависимости от роли ---
    if role == "service":
        await message.answer(
            "📨 Куда вам удобнее получать заявки от клиентов?\n\n"
            "Выберите вариант ниже:",
            reply_markup=get_service_notifications_kb(),
        )
        await state.set_state(Registration.notifications)
    else:
        # Клиент — регистрация завершена
        await state.clear()
        await message.answer(
            "✅ Регистрация завершена.\n\nГлавное меню:",
            reply_markup=get_main_kb(),
        )


# Обработчик нажатия на "Мой гараж"
async def my_garage(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    msg = callback.message
    # Сообщение бота, если отправитель сообщения != пользователь, который нажал кнопку
    is_bot_message = msg.from_user.id != callback.from_user.id

    async with AsyncSessionLocal() as session:
        try:
            # Получаем пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = result.scalar_one_or_none()

            # Если пользователь не найден — просим зарегистрироваться
            if not user:
                text = (
                    "❌ Вы еще не зарегистрированы.\n"
                    "Нажмите /start для регистрации."
                )
                if is_bot_message:
                    await msg.edit_text(text, reply_markup=None)
                else:
                    await msg.answer(text, reply_markup=None)

                await callback.answer()
                return

            # Получаем автомобили
            result = await session.execute(
                select(Car).where(Car.user_id == user.id)
            )
            cars = result.scalars().all()

            # Если в гараже нет машин
            if not cars:
                text = (
                    "🚗 В вашем гараже пока нет автомобилей.\n\n"
                    "Нажмите кнопку ниже, чтобы добавить первый автомобиль:"
                )
                kb = get_garage_kb()

                if is_bot_message:
                    await msg.edit_text(text, reply_markup=kb)
                else:
                    await msg.answer(text, reply_markup=kb)
            else:
                # Строим список машин
                builder = InlineKeyboardBuilder()
                for car in cars:
                    builder.row(
                        InlineKeyboardButton(
                            text=f"🚗 {car.brand} {car.model}",
                            callback_data=f"select_car:{car.id}",
                        )
                    )
                builder.row(
                    InlineKeyboardButton(
                        text="➕ Добавить автомобиль",
                        callback_data="add_car",
                    )
                )
                builder.row(
                    InlineKeyboardButton(
                        text="⬅️ В меню",
                        callback_data="back_to_main",
                    )
                )

                text = (
                    "🚗 Ваш гараж:\n\n"
                    "Выберите автомобиль для управления или добавьте новый:"
                )
                kb = builder.as_markup()

                if is_bot_message:
                    await msg.edit_text(text, reply_markup=kb)
                else:
                    await msg.answer(text, reply_markup=kb)

        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке гаража: {e}")
            text = "❌ Ошибка при загрузке гаража. Попробуйте позже."

            # В случае ошибки тоже стараемся не редактировать пользовательские сообщения
            if is_bot_message:
                try:
                    await msg.edit_text(text, reply_markup=get_main_kb())
                except Exception:
                    await msg.answer(text, reply_markup=get_main_kb())
            else:
                await msg.answer(text, reply_markup=get_main_kb())

        # В конце — аккуратно отвечаем только на “живой” callback
    try:
        if getattr(callback, "id", None) != "fake":
            await callback.answer()
    except Exception:
        # На всякий случай вообще не падаем из-за answer()
        pass


@router.callback_query(
    Registration.notifications,
    F.data.in_(["sc_notif_owner", "sc_notif_group"]),
)
async def registration_choose_notifications(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service_center_id = data.get("service_center_id")

    if not service_center_id:
        await state.clear()
        await callback.message.edit_text(
            "❌ Не найден профиль автосервиса. Попробуйте /start ещё раз."
        )
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        from app.database.models import ServiceCenter

        result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.id == service_center_id)
        )
        service_center = result.scalar_one_or_none()

        if not service_center:
            await state.clear()
            await callback.message.edit_text(
                "❌ Профиль автосервиса не найден. Попробуйте /start ещё раз."
            )
            await callback.answer()
            return

        choice = callback.data

        if choice == "sc_notif_owner":
            # Только ЛС владельцу
            service_center.send_to_owner = True
            service_center.send_to_group = False
            service_center.manager_chat_id = None
            await session.commit()

            await state.clear()

            await callback.message.edit_text(
                "✅ Заявки будут приходить вам в личные сообщения этого аккаунта.\n\n"
                "Регистрация автосервиса завершена!",
            )
            await callback.message.answer(
                "🛠 Вы зарегистрированы как <b>автосервис</b>.\n\n"
                "Новые заявки будут приходить вам в этот бот.\n"
                "Позже вы сможете привязать группу командой /bind_group.",
                parse_mode="HTML",
                reply_markup=get_manager_main_kb(),
            )

            # Бонус за регистрацию сервиса
            try:
                await add_bonus(
                    callback.from_user.id,
                    "register",
                    description="Регистрация автосервиса в боте",
                )
            except Exception as bonus_err:
                logging.error(f"❌ Ошибка начисления бонуса за регистрацию (service): {bonus_err}")

            await callback.answer()
            return

        # Вариант с группой: заявки только в группу
        service_center.send_to_owner = False
        service_center.send_to_group = True
        service_center.manager_chat_id = None
        await session.commit()

    await state.clear()

    # Инструкции по /bind_group
    await callback.message.edit_text(
        "✅ Настройки сохранены.\n\n"
        "Теперь нужно привязать группу Telegram для получения заявок:\n\n"
        "1️⃣ Добавьте бота в вашу группу и назначьте его администратором.\n"
        "2️⃣ В этой группе выполните команду /bind_group.\n\n"
        "После этого новые заявки будут отправляться в указанную группу.",
    )

    # Бонус за регистрацию сервиса
    try:
        await add_bonus(
            callback.from_user.id,
            "register",
            description="Регистрация автосервиса в боте",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за регистрацию (service): {bonus_err}")

    await callback.answer()


@router.message(Registration.group_chat)
async def registration_bind_group_chat(message: Message, state: FSMContext):
    data = await state.get_data()
    service_center_id = data.get("service_center_id")
    send_to_owner_also = data.get("send_to_owner_also", False)

    if not service_center_id:
        await state.clear()
        await message.answer(
            "❌ Не найден профиль автосервиса. Попробуйте /start ещё раз.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    fwd_chat = message.forward_from_chat
    if not fwd_chat:
        await message.answer(
            "❌ Не удалось определить группу.\n\n"
            "Пожалуйста, перешлите <b>сообщение из группы</b>, "
            "куда нужно отправлять заявки.",
            parse_mode="HTML",
        )
        return

    if fwd_chat.type not in ("group", "supergroup"):
        await message.answer(
            "❌ Это не группа.\n\n"
            "Перешлите сообщение именно из <b>группы или супергруппы</b>, "
            "куда вы хотите получать заявки.",
            parse_mode="HTML",
        )
        return

    group_chat_id = fwd_chat.id

    async with AsyncSessionLocal() as session:
        from app.database.models import ServiceCenter  # на случай локального импорта

        result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.id == service_center_id)
        )
        service_center = result.scalar_one_or_none()

        if not service_center:
            await state.clear()
            await message.answer(
                "❌ Профиль автосервиса не найден. Попробуйте /start ещё раз.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        service_center.manager_chat_id = group_chat_id
        service_center.send_to_group = True
        service_center.send_to_owner = bool(send_to_owner_also)

        await session.commit()

    await state.clear()

    await message.answer(
        "✅ Группа успешно привязана!\n\n"
        "Теперь новые заявки будут отправляться в указанную группу"
        + (" и вам в личные сообщения." if send_to_owner_also else ".")
        + "\n\nЕсли вы захотите поменять группу, просто добавьте бота "
          "в другую группу и отправьте там команду /bind_group.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await message.answer(
        "🛠 Вы зарегистрированы как <b>автосервис</b>.\n\n"
        "Используйте панель ниже или команду /manager для работы с заявками.",
        parse_mode="HTML",
        reply_markup=get_manager_main_kb(),
    )

    # Бонус за регистрацию
    try:
        await add_bonus(
            message.from_user.id,
            "register",
            description="Регистрация автосервиса в боте (с привязкой группы)",
        )
    except Exception as bonus_err:
        logging.error(f"❌ Ошибка начисления бонуса за регистрацию (service+group): {bonus_err}")


# Регистрация обработчика нажатия на кнопку "Мой гараж"
@router.callback_query(F.data == "my_garage")
async def my_garage_callback(callback: CallbackQuery, state: FSMContext):
    """
    Входная точка для callback-кнопки "Мой гараж".
    Просто прокидываем вызов в общий обработчик my_garage().
    """
    await my_garage(callback, state)


# Обработчик кнопки "Добавить автомобиль"
@router.callback_query(F.data == "add_car")
async def add_car(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🚗 Добавление автомобиля\n\n"
        "Введите марку автомобиля (например, 'Toyota'):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.brand)
    await callback.answer()


# Обработчик отмены при добавлении/редактировании авто
@router.callback_query(F.data == "cancel_car_action")
async def cancel_car_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await my_garage(callback, state)


# Обработчик ввода марки авто
@router.message(CarForm.brand)
async def process_car_brand(message: Message, state: FSMContext):
    brand = message.text.strip()
    
    if len(brand) < 2:
        await message.answer(
            "❌ Марка слишком короткая. Пожалуйста, введите корректную марку:",
            reply_markup=get_car_cancel_kb()
        )
        return

    await state.update_data(brand=brand)
    await message.answer(
        "Теперь введите модель автомобиля (например, 'Camry'):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.model)


# Обработчик ввода модели авто
@router.message(CarForm.model)
async def process_car_model(message: Message, state: FSMContext):
    model = message.text.strip()
    
    if len(model) < 1:
        await message.answer(
            "❌ Модель не может быть пустой. Пожалуйста, введите модель:",
            reply_markup=get_car_cancel_kb()
        )
        return

    await state.update_data(model=model)
    await message.answer(
        "Введите год выпуска автомобиля (например, 2015):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.year)


# Обработчик ввода года авто
@router.message(CarForm.year)
async def process_car_year(message: Message, state: FSMContext):
    try:
        year = int(message.text.strip())
        current_year = datetime.now().year
        
        if year < 1980 or year > current_year + 1:
            await message.answer(
                f"❌ Пожалуйста, введите год в диапазоне 1980-{current_year + 1}:",
                reply_markup=get_car_cancel_kb()
            )
            return
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите год числом (например, 2015):",
            reply_markup=get_car_cancel_kb()
        )
        return

    await state.update_data(year=year)
    await message.answer(
        "Введите VIN автомобиля (17 символов, если знаете).\n"
        "Если VIN неизвестен — можете указать любое удобное обозначение или написать «нет».",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.vin)


@router.message(CarForm.vin)
async def process_car_vin(message: Message, state: FSMContext):
    vin = (message.text or "").strip().upper()

    if len(vin) < 3:
        await message.answer(
            "❌ VIN слишком короткий. Укажите хотя бы 3 символа или напишите «нет»:",
            reply_markup=get_car_cancel_kb()
        )
        return

    await state.update_data(vin=vin)
    await message.answer(
        "Введите госномер автомобиля (например, А123ВС777):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.license_plate)


# Обработчик ввода госномера
@router.message(CarForm.license_plate)
async def process_car_license_plate(message: Message, state: FSMContext):
    license_plate = message.text.strip().upper()
    
    if len(license_plate) < 4:
        await message.answer(
            "❌ Госномер слишком короткий. Пожалуйста, введите корректный номер:",
            reply_markup=get_car_cancel_kb()
        )
        return

    data = await state.get_data()
    brand = data.get("brand")
    model = data.get("model")
    year = data.get("year")
    vin = data.get("vin")

    async with AsyncSessionLocal() as session:
        try:
            # Получаем пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                await message.answer(
                    "❌ Пользователь не найден. Начните с /start",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                return

            # Создаем автомобиль
            new_car = Car(
                user_id=user.id,
                brand=brand,
                model=model,
                year=year,
                license_plate=license_plate,
                vin=vin,
            )
            session.add(new_car)
            await session.commit()
            
            await message.answer(
                f"✅ Автомобиль {brand} {model} ({year}), госномер {license_plate} добавлен в ваш гараж.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении автомобиля: {e}")
            await message.answer(
                "❌ Произошла ошибка при сохранении автомобиля. Попробуйте позже."
            )
            await state.clear()
            return

    await state.clear()
    # Показываем гараж
    fake_callback = CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data="my_garage"
    )
    await my_garage(fake_callback, state)


# Обработчик выбора автомобиля в гараже
@router.callback_query(F.data.startswith("select_car:"))
async def select_car(callback: CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await callback.message.edit_text(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_garage_kb()
                )
                await callback.answer()
                return
            
            await callback.message.edit_text(
                f"🚗 {car.brand} {car.model} ({car.year})\n"
                f"Госномер: {car.license_plate}\n\n"
                "Выберите действие:",
                reply_markup=get_car_management_kb(car.id)
            )
        except Exception as e:
            logging.error(f"❌ Ошибка при выборе автомобиля: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при загрузке данных автомобиля.",
                reply_markup=get_garage_kb()
            )
    await callback.answer()


# Обработчик редактирования авто
@router.callback_query(F.data.startswith("edit_car:"))
async def edit_car(callback: CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    await state.update_data(car_id=car_id)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Марка", callback_data="edit_car_brand"),
        InlineKeyboardButton(text="✏️ Модель", callback_data="edit_car_model")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Год выпуска", callback_data="edit_car_year"),
        InlineKeyboardButton(text="✏️ Госномер", callback_data="edit_car_license")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"select_car:{car_id}")
    )
    
    await callback.message.edit_text(
        "✏️ Что вы хотите изменить?",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "edit_car_brand")
async def edit_car_brand(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите новую марку автомобиля:",
        reply_markup=get_edit_cancel_kb()
    )
    await state.set_state(CarForm.edit_brand)
    await callback.answer()


@router.callback_query(F.data == "edit_car_model")
async def edit_car_model(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите новую модель автомобиля:",
        reply_markup=get_edit_cancel_kb()
    )
    await state.set_state(CarForm.edit_model)
    await callback.answer()


@router.callback_query(F.data == "edit_car_year")
async def edit_car_year(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите новый год выпуска автомобиля:",
        reply_markup=get_edit_cancel_kb()
    )
    await state.set_state(CarForm.edit_year)
    await callback.answer()


@router.callback_query(F.data == "edit_car_license")
async def edit_car_license(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите новый госномер автомобиля:",
        reply_markup=get_edit_cancel_kb()
    )
    await state.set_state(CarForm.edit_license_plate)
    await callback.answer()


@router.callback_query(F.data == "cancel_edit")
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    car_id = data.get("car_id")
    
    await state.clear()
    
    if car_id:
        fake_callback = CallbackQuery(
            id="fake",
            from_user=callback.from_user,
            chat_instance="",
            message=callback.message,
            data=f"select_car:{car_id}"
        )
        await select_car(fake_callback, state)
    else:
        await my_garage(callback, state)
    
    await callback.answer()


@router.message(CarForm.edit_brand)
async def process_edit_brand(message: Message, state: FSMContext):
    new_brand = message.text.strip()
    
    if len(new_brand) < 2:
        await message.answer(
            "❌ Марка слишком короткая. Пожалуйста, введите корректную марку:",
            reply_markup=get_edit_cancel_kb()
        )
        return
    
    data = await state.get_data()
    car_id = data.get("car_id")
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await message.answer(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                return
            
            car.brand = new_brand
            await session.commit()
            
            await message.answer(
                f"✅ Марка обновлена на {new_brand}.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при обновлении марки: {e}")
            await message.answer(
                "❌ Ошибка при обновлении марки. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
            await state.clear()
            return

    await state.clear()
    fake_callback = CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data=f"select_car:{car_id}"
    )
    await select_car(fake_callback, state)


@router.message(RequestForm.location, F.location)
async def process_location_geo(message: Message, state: FSMContext):
    """
    Пользователь отправил геопозицию автомобиля (через кнопку
    «📍 Отправить геопозицию»).

    Сохраняем координаты и двигаемся к выбору даты.
    """
    loc = message.location

    await state.update_data(
        location_lat=loc.latitude,
        location_lon=loc.longitude,
        # Можно сохранить короткое описание, чтобы потом показать ссылку на карту
        location_description=(
            f"Координаты: {loc.latitude:.5f}, {loc.longitude:.5f}\n"
            f"https://maps.google.com/?q={loc.latitude:.5f},{loc.longitude:.5f}"
        ),
    )

    # Убираем клавиатуру с гео
    await message.answer(
        "✅ Геопозиция автомобиля получена.",
        reply_markup=ReplyKeyboardRemove(),
    )

    await message.answer(
        "⏰ Когда вам удобно выполнить работу?\n\n"
        "Напишите удобную дату или период (например, "
        "«Сегодня после 18:00», «Завтра утром», «В субботу»).",
    )
    await state.set_state(RequestForm.preferred_date)


@router.message(RequestForm.location)
async def process_location_text(message: Message, state: FSMContext):
    """
    Пользователь ввёл местоположение текстом или решил пропустить.
    Используется в сценарии, когда авто НЕ может ехать само
    (эвакуатор / выездной мастер), а пользователь:
      - либо написал адрес/ориентиры,
      - либо выбрал «⏭️ Пропустить (укажу позже)».
    """
    text_raw = (message.text or "").strip()
    text_lower = text_raw.lower()

    # Пропуск локации
    if text_lower.startswith("⏭️".lower()) or "пропустить" in text_lower:
        await state.update_data(
            location_lat=None,
            location_lon=None,
            location_description=None,
        )
    else:
        # Сохраняем текстовый адрес/описание
        await state.update_data(
            location_lat=None,
            location_lon=None,
            location_description=text_raw,
        )

    await message.answer(
        "⏰ Когда вам удобно выполнить работу?\n\n"
        "Напишите удобную дату или период (например, "
        "«Сегодня после 18:00», «Завтра утром», «В субботу»).",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RequestForm.preferred_date)


#  Учитываем может ли ехать + гео
@router.message(RequestForm.preferred_date)
async def process_preferred_date(message: Message, state: FSMContext):
    """
    Шаг выбора даты/периода.
    Затем предложим выбрать интервал времени отдельной инлайн-клавиатурой.
    """
    date_text = (message.text or "").strip()

    if len(date_text) < 3:
        await message.answer(
            "❌ Слишком короткий ответ.\n"
            "Пожалуйста, укажите дату или период, когда вам удобно выполнить работу "
            "(например, «Сегодня после 18:00», «Завтра утром», «В субботу»)."
        )
        return

    # Сохраняем сырой текст даты
    await state.update_data(preferred_date_raw=date_text)

    await message.answer(
        "⏰ Теперь выберите удобное время:",
        reply_markup=get_time_slot_kb(),
    )
    await state.set_state(RequestForm.preferred_time_slot)


@router.message(CarForm.edit_model)
async def process_edit_model(message: Message, state: FSMContext):
    new_model = message.text.strip()
    
    if len(new_model) < 1:
        await message.answer(
            "❌ Модель не может быть пустой. Пожалуйста, введите модель:",
            reply_markup=get_edit_cancel_kb()
        )
        return
    
    data = await state.get_data()
    car_id = data.get("car_id")
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await message.answer(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                return
            
            car.model = new_model
            await session.commit()
            
            await message.answer(
                f"✅ Модель обновлена на {new_model}.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при обновлении модели: {e}")
            await message.answer(
                "❌ Ошибка при обновлении модели. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
            await state.clear()
            return

    await state.clear()
    fake_callback = CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data=f"select_car:{car_id}"
    )
    await select_car(fake_callback, state)


def _build_request_preview_text(data: dict) -> str:
    """
    Формирует текст превью заявки на этапе подтверждения.
    Используется и при первичном создании, и при редактировании.
    """
    service_type = data.get("service_type", "Не указано")
    description = data.get("description", "Не указано")
    photo_id = data.get("photo")
    photos_text = "есть" if photo_id else "нет"

    can_drive = data.get("can_drive")
    if can_drive is True:
        can_drive_text = "Да, может ехать сам"
    elif can_drive is False:
        can_drive_text = "Нет, требуется эвакуатор/перевозка"
    else:
        can_drive_text = "Не указано"

    # Локация
    location_lat = data.get("location_lat")
    location_lon = data.get("location_lon")
    location_description = data.get("location_description")

    if location_lat and location_lon:
        location_text = (
            f"Координаты: {location_lat:.5f}, {location_lon:.5f}\n"
            f"https://maps.google.com/?q={location_lat:.5f},{location_lon:.5f}"
        )
    elif location_description:
        location_text = location_description
    else:
        location_text = "Не указано"

    preferred = data.get("preferred_date") or "Не указано"

    text = (
        "📄 Заявка на услугу\n\n"
        f"🔧 Услуга: {service_type}\n"
        f"📝 Описание: {description}\n"
        f"📷 Фото: {photos_text}\n"
        f"🚚 Может ехать сам: {can_drive_text}\n"
        f"📍 Местоположение: {location_text}\n"
        f"⏰ Когда удобно: {preferred}\n\n"
        "Подтвердите создание заявки:"
    )
    return text


@router.callback_query(RequestForm.preferred_time_slot, F.data.startswith("time_slot:"))
async def process_time_slot(callback: CallbackQuery, state: FSMContext):
    """
    Клиент выбирает удобный интервал времени: до 12, 12–18, после 18.
    После выбора формируем текст заявки и переходим к подтверждению.
    """
    action = callback.data.split(":", 1)[1]

    # Клиент хочет изменить дату — возвращаем на предыдущий шаг
    if action == "change_date":
        await callback.message.edit_text(
            "⏰ Пожалуйста, напишите дату или период, когда вам удобно "
            "выполнить работу:",
            reply_markup=get_car_cancel_kb(),
        )
        await state.set_state(RequestForm.preferred_date)
        await callback.answer()
        return

    slot_map = {
        "morning": "до 12:00",
        "day": "с 12:00 до 18:00",
        "evening": "после 18:00",
    }
    slot_label = slot_map.get(action)
    if not slot_label:
        await callback.answer("Некорректный выбор времени", show_alert=True)
        return

    data = await state.get_data()
    date_raw = (data.get("preferred_date_raw") or "").strip()

    # Формируем финальный текст "дата + интервал"
    if date_raw:
        preferred = f"{date_raw}, {slot_label}"
    else:
        preferred = slot_label

    # Кладём финальный текст туда, откуда его потом возьмёт создание заявки
    await state.update_data(preferred_date=preferred)

    # Берём актуальные данные и формируем превью
    new_data = await state.get_data()
    preview_text = _build_request_preview_text(new_data)

    await callback.message.edit_text(
        preview_text,
        reply_markup=get_request_confirm_kb(),
    )
    await state.set_state(RequestForm.confirm)
    await callback.answer()


@router.message(CarForm.edit_year)
async def process_edit_year(message: Message, state: FSMContext):
    try:
        new_year = int(message.text.strip())
        current_year = datetime.now().year
        
        if new_year < 1980 or new_year > current_year + 1:
            await message.answer(
                f"❌ Пожалуйста, введите год в диапазоне 1980-{current_year + 1}:",
                reply_markup=get_edit_cancel_kb()
            )
            return
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите год числом (например, 2015):",
            reply_markup=get_edit_cancel_kb()
        )
        return

    data = await state.get_data()
    car_id = data.get("car_id")
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await message.answer(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                return
            
            car.year = new_year
            await session.commit()
            
            await message.answer(
                f"✅ Год выпуска обновлен на {new_year}.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при обновлении года: {e}")
            await message.answer(
                "❌ Ошибка при обновлении года. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
            await state.clear()
            return

    await state.clear()
    fake_callback = CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data=f"select_car:{car_id}"
    )
    await select_car(fake_callback, state)


@router.message(CarForm.edit_license_plate)
async def process_edit_license_plate(message: Message, state: FSMContext):
    new_license = message.text.strip().upper()
    
    if len(new_license) < 4:
        await message.answer(
            "❌ Госномер слишком короткий. Пожалуйста, введите корректный номер:",
            reply_markup=get_edit_cancel_kb()
        )
        return

    data = await state.get_data()
    car_id = data.get("car_id")
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await message.answer(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                return
            
            car.license_plate = new_license
            await session.commit()
            
            await message.answer(
                f"✅ Госномер обновлен на {new_license}.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при обновлении госномера: {e}")
            await message.answer(
                "❌ Ошибка при обновлении госномера. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
            await state.clear()
            return

    await state.clear()
    fake_callback = CallbackQuery(
        id="fake",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data=f"select_car:{car_id}"
    )
    await select_car(fake_callback, state)


@router.callback_query(F.data.startswith("delete_car:"))
async def delete_car(callback: CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    await state.update_data(car_id=car_id)
    
    await callback.message.edit_text(
        "❗ Вы уверены, что хотите удалить этот автомобиль?\n"
        "Это действие нельзя будет отменить.",
        reply_markup=get_delete_confirm_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_car")
async def confirm_delete_car(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    car_id = data.get("car_id")
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(Car).where(Car.id == car_id)
            )
            car = result.scalar_one_or_none()
            
            if not car:
                await callback.message.edit_text(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                await callback.answer()
                return
            
            session.delete(car)
            await session.commit()
            
            await callback.message.edit_text(
                "✅ Автомобиль удален из вашего гаража.",
                reply_markup=get_main_kb()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при удалении автомобиля: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при удалении автомобиля. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_delete_car")
async def cancel_delete_car(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    car_id = data.get("car_id")

    await state.clear()

    if car_id:
        fake_callback = CallbackQuery(
            id="fake",
            from_user=callback.from_user,
            chat_instance="",
            message=callback.message,
            data=f"select_car:{car_id}"
        )
        await select_car(fake_callback, state)
    else:
        await my_garage(callback, state)

    await callback.answer()


@router.callback_query(F.data == "create_request")
async def create_request(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        try:
            user_id = callback.from_user.id

            # Получаем пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                await callback.message.edit_text(
                    "❌ Пользователь не найден. Начните с /start"
                )
                await callback.answer()
                return

            # Получаем автомобили пользователя
            cars_result = await session.execute(
                select(Car).where(Car.user_id == user.id)
            )
            cars = cars_result.scalars().all()

            if not cars:
                await callback.message.edit_text(
                    "🚗 В вашем гараже пока нет автомобилей.\n\n"
                    "Сначала добавьте автомобиль:",
                    reply_markup=get_garage_kb(),
                )
                await callback.answer()
                return

            # Показываем выбор автомобиля
            builder = InlineKeyboardBuilder()
            for car in cars:
                builder.row(
                    InlineKeyboardButton(
                        text=f"🚗 {car.brand} {car.model}",
                        callback_data=f"select_car_for_request:{car.id}",
                    )
                )
            builder.row(
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data="cancel_request"
                )
            )

            await callback.message.edit_text(
                "📝 Создание заявки\n\n"
                "Выберите автомобиль, для которого создаётся заявка:",
                reply_markup=builder.as_markup(),
            )

            # ВАЖНО: ставим стейт выбора авто
            await state.set_state(RequestForm.car_selection)

        except Exception as e:
            logging.error(f"❌ Ошибка при создании заявки: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при создании заявки. Попробуйте позже.",
                reply_markup=get_main_kb(),
            )
    await callback.answer()


@router.callback_query(StateFilter(None), F.data.startswith("select_sc_for_request:"))
async def start_request_from_service_search(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал автосервис из поиска / из кнопки 'Показать всех',
    когда мастер заявки ещё не запущен.

    Запускаем создание НОВОЙ заявки с заранее выбранным СТО:
    1) сохраняем service_center_id в FSM
    2) спрашиваем, для какого авто создать заявку (как в create_request)
    """
    try:
        sc_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Не удалось понять, какой автосервис выбран 🤔", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        # Проверяем, что СТО существует
        result_sc = await session.execute(
            select(ServiceCenter).where(ServiceCenter.id == sc_id)
        )
        sc = result_sc.scalar_one_or_none()

        if not sc:
            await callback.answer("Автосервис не найден, попробуйте ещё раз 🙏", show_alert=True)
            return

        # На всякий случай очищаем старое состояние
        await state.clear()

        # Сохраняем выбранный сервис в FSM
        await state.update_data(service_center_id=sc.id)

        # Получаем пользователя
        result_user = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result_user.scalar_one_or_none()

        if not user:
            await callback.message.edit_text(
                "❌ Пользователь не найден. Начните с /start"
            )
            await callback.answer()
            return

        # Получаем автомобили пользователя
        result_cars = await session.execute(
            select(Car).where(Car.user_id == user.id)
        )
        cars = result_cars.scalars().all()

    # Вне сессии — только отправка сообщений

    if not cars:
        await callback.message.edit_text(
            "🚗 В вашем гараже пока нет автомобилей.\n\n"
            "Сначала добавьте автомобиль:",
            reply_markup=get_garage_kb(),
        )
        await callback.answer()
        return

    # Показываем выбор автомобиля (как в create_request)
    builder = InlineKeyboardBuilder()
    for car in cars:
        builder.row(
            InlineKeyboardButton(
                text=f"🚗 {car.brand} {car.model}",
                callback_data=f"select_car_for_request:{car.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить", callback_data="cancel_request"
        )
    )

    await callback.message.edit_text(
        f"📝 Создание заявки в автосервис <b>{sc.name}</b>\n\n"
        "Выберите автомобиль, для которого создаётся заявка:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )

    # Ставим стейт выбора авто
    await state.set_state(RequestForm.car_selection)
    await callback.answer()


@router.callback_query(F.data.startswith("create_request_for_car:"))
async def create_request_for_car(callback: CallbackQuery, state: FSMContext):
    """
    Кнопка на карточке авто "Создать заявку" —
    сначала привязываем авто, потом спрашиваем тип работ, а не СТО.
    """
    await state.clear()

    try:
        _, car_id_str = callback.data.split(":")
        car_id = int(car_id_str)
    except (ValueError, IndexError):
        await callback.answer("Не удалось определить автомобиль 🤔", show_alert=True)
        return

    await state.update_data(car_id=car_id)
    logger.info("📝 Создание заявки из карточки авто id=%s", car_id)

    await _start_request_service_type_step(callback, state)
    await callback.answer()


async def _start_request_service_type_step(callback: CallbackQuery, state: FSMContext):
    """
    Переход к шагу выбора вида работ для заявки.
    Общая функция, чтобы не дублировать текст.
    """
    await callback.message.edit_text(
        "🛠️ Выберите вид работ:\n\n"
        "• 🧼 <b>Автомойки</b> — мойка, химчистка, детейлинг\n"
        "• 🛞 <b>Шиномонтаж</b> — переобувка, ремонт шин и дисков\n"
        "• ⚡ <b>Автоэлектрик</b> — диагностика и ремонт электрики\n"
        "• 🔧 <b>Слесарные работы</b> — подвеска, тормоза, ДВС и т.п.\n"
        "• 🎨 <b>Малярные работы</b> — кузовной ремонт, покраска\n"
        "• 🛠️ <b>Техобслуживание</b> — ТО, масла, фильтры\n"
        "• ⚙️ <b>Ремонт агрегатов</b> — турбины, стартер, генератор, рейка",
        parse_mode="HTML",
        reply_markup=get_service_types_kb()
    )
    await state.set_state(RequestForm.service_type)


async def _ask_service_center_for_request(callback: CallbackQuery, state: FSMContext):
    """
    Шаг выбора автосервиса после того, как:
    - выбран автомобиль
    - выбран тип/подтип работы (category_code)

    Новая логика:
    - Показываем список подходящих СТО с адресом и рейтингом в тексте кнопки.
    - Добавляем:
        • 📤 Отправить всем подходящим
        • 🔍 Найти ближайший (пока заглушка)
    """
    data = await state.get_data()
    category_code = data.get("category_code")
    can_drive = data.get("can_drive")  # может пригодиться дальше

    async with AsyncSessionLocal() as session:
        # Базовый запрос: только активные СТО (есть владелец)
        base_query = select(ServiceCenter).where(ServiceCenter.owner_user_id.isnot(None))

        if category_code:
            # Сервисы, у которых либо:
            # - есть специализации и среди них есть наш category_code
            # - либо специализации нет (универсальный сервис)
            spec_like = f"%{category_code}%"
            base_query = base_query.where(
                (ServiceCenter.specializations.ilike(spec_like))
                | (ServiceCenter.specializations.is_(None))
            )

        # Упорядочим по рейтингу (сначала самые высокие), потом по id
        base_query = base_query.order_by(
            ServiceCenter.rating.desc().nullslast(),
            ServiceCenter.id.desc(),
        )

        result = await session.execute(base_query)
        services = result.scalars().all()

    # Если подходящих нет — позволяем создать заявку без привязки к СТО
    if not services:
        await callback.message.edit_text(
            "❌ Подходящих автосервисов сейчас не найдено.\n\n"
            "Но вы всё равно можете создать заявку — менеджеры увидят её в общем списке.\n\n"
            "Опишите, пожалуйста, проблему с автомобилем:",
            reply_markup=None,
            parse_mode="HTML",
        )
        await state.set_state(RequestForm.description)
        await callback.answer()
        return

    # Если один подходящий сервис — сразу выбираем его, но говорим об этом пользователю
    if len(services) == 1:
        service = services[0]
        await state.update_data(service_center_id=service.id)

        rating_text = ""
        if service.ratings_count and service.ratings_count > 0:
            rating_text = f" (⭐ {service.rating:.1f} на основе {service.ratings_count} оценок)"

        await callback.message.edit_text(
            f"🏭 Автосервис для заявки выбран автоматически:\n\n"
            f"<b>{service.name}</b>\n"
            f"📍 {service.address or 'Адрес не указан'}\n"
            f"{rating_text}\n\n"
            "Теперь опишите, пожалуйста, проблему с автомобилем:",
            parse_mode="HTML",
        )
        await state.set_state(RequestForm.description)
        await callback.answer()
        return

    # Несколько подходящих СТО — показываем список
    builder = InlineKeyboardBuilder()

    for sc in services:
        title_parts: list[str] = []

        # Название
        title_parts.append(sc.name)

        # Рейтинг
        if sc.ratings_count and sc.ratings_count > 0:
            title_parts.append(f"⭐ {sc.rating:.1f}")

        # Короткий адрес
        if sc.address:
            # Чтобы не раздувать кнопку, обрежем адрес, если он очень длинный
            short_addr = sc.address.strip()
            if len(short_addr) > 40:
                short_addr = short_addr[:37] + "…"
            title_parts.append(short_addr)

        button_text = " | ".join(title_parts)

        builder.row(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_sc_for_request:{sc.id}",
            )
        )

    # Дополнительные опции
    builder.row(
        InlineKeyboardButton(
            text="📤 Отправить всем подходящим",
            callback_data="request_send_to_all",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔍 Найти ближайший",
            callback_data="request_find_nearby",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить",
            callback_data="cancel_request",
        )
    )

    await callback.message.edit_text(
        "🏭 Выберите автосервис, который будет выполнять работы:\n\n"
        "• Нажмите на сервис из списка (видно название, рейтинг и адрес);\n"
        "• или используйте «📤 Отправить всем подходящим»;\n"
        "• в следующей итерации добавим полноценный поиск ближайшего по геолокации.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(RequestForm.service_center)
    await callback.answer()


@router.callback_query(RequestForm.service_center, F.data == "request_find_nearby")
async def request_find_nearby(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал '🔍 Найти ближайший' внутри процесса создания заявки.
    Шаг 1: спрашиваем радиус поиска.
    """
    await callback.message.edit_text(
        "🌍 Чтобы найти ближайшие СТО, сначала выберите радиус поиска:",
        reply_markup=get_search_radius_kb(),
    )
    # Переходим в под-состояние выбора радиуса (в контексте заявки)
    await state.set_state(RequestForm.nearest_radius)
    await callback.answer()


@router.callback_query(RequestForm.nearest_radius, F.data.startswith("radius:"))
async def request_nearest_radius(callback: CallbackQuery, state: FSMContext):
    """
    Шаг 2: выбран радиус (из get_search_radius_kb),
    дальше попросим геолокацию пользователя.
    """
    try:
        radius_km = float(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Не удалось понять радиус 😕", show_alert=True)
        return

    # Сохраняем радиус в состоянии
    await state.update_data(nearest_radius_km=radius_km)

    await callback.message.edit_text(
        "📍 Теперь отправьте геолокацию автомобиля,\n"
        "чтобы мы нашли ближайшие подходящие СТО.",
    )
    await callback.message.answer(
        "Нажмите кнопку ниже, чтобы отправить геолокацию:",
        reply_markup=get_location_reply_kb(),
    )

    await state.set_state(RequestForm.nearest_location)
    await callback.answer()

@router.message(RequestForm.nearest_location)
async def request_nearest_location(message: Message, state: FSMContext):
    """
    Шаг 3: получаем геолокацию, считаем расстояния и показываем
    ближайшие СТО для выбора в рамках текущей заявки.
    """
    # Пользователь должен отправить гео
    if not message.location:
        text = (message.text or "").strip().lower()
        if "отмена" in text or "cancel" in text:
            # Отмена поиска ближайших — возвращаемся к обычному списку СТО
            await message.answer(
                "Поиск ближайших сервисов отменён.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await _ask_service_center_for_request_from_message(message, state)
            return

        await message.answer(
            "Пожалуйста, отправьте геолокацию через кнопку "
            "«📍 Отправить геолокацию» внизу экрана.\n"
            "Или напишите «отмена» для возврата к списку сервисов."
        )
        return

    # Геолокация есть
    loc = message.location
    user_lat = loc.latitude
    user_lon = loc.longitude

    data = await state.get_data()
    radius_km = float(data.get("nearest_radius_km", 10))
    category_code = data.get("category_code")

    async with AsyncSessionLocal() as session:
        # Берём только "живые" сервисы, у которых есть владелец и координаты
        query = select(ServiceCenter).where(
            ServiceCenter.owner_user_id.isnot(None),
            ServiceCenter.location_lat.is_not(None),
            ServiceCenter.location_lon.is_not(None),
        )

        if category_code:
            spec_like = f"%{category_code}%"
            query = query.where(
                (ServiceCenter.specializations.ilike(spec_like))
                | (ServiceCenter.specializations.is_(None))
            )

        result = await session.execute(query)
        services = result.scalars().all()

    nearby: list[tuple[ServiceCenter, float]] = []
    for sc in services:
        dist = _haversine_km(user_lat, user_lon, sc.location_lat, sc.location_lon)
        if dist <= radius_km:
            nearby.append((sc, dist))

    nearby.sort(key=lambda x: x[1])

    # Убираем реплай-клавиатуру с гео
    await message.answer("Спасибо, локация получена ✅", reply_markup=ReplyKeyboardRemove())

    # Если в радиусе никого нет — предлагаем альтернативы
    if not nearby:
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(
                text="📤 Отправить всем подходящим",
                callback_data="request_send_to_all",
            )
        )
        kb.row(
            InlineKeyboardButton(
                text="📋 Показать весь список сервисов",
                callback_data="request_back_to_service_list",
            )
        )

        await message.answer(
            f"😔 В радиусе {radius_km:.0f} км подходящих СТО не найдено.\n\n"
            "Вы можете:\n"
            "• отправить заявку всем подходящим сервисам;\n"
            "• или вернуться к полному списку СТО.",
            reply_markup=kb.as_markup(),
        )

        # Возвращаемся к состоянию выбора сервиса
        await state.set_state(RequestForm.service_center)
        return

    # Есть хотя бы один сервис в радиусе — показываем список
    lines = [f"🏭 <b>Сервисы рядом с вами (до {radius_km:.0f} км)</b>\n"]
    kb = InlineKeyboardBuilder()

    for sc, dist in nearby:
        parts = [sc.name]

        # Добавим рейтинг, если есть
        if sc.ratings_count and sc.ratings_count > 0:
            parts.append(f"⭐ {sc.rating:.1f}")

        parts.append(f"{dist:.1f} км")

        # Короткий адрес
        if sc.address:
            short_addr = sc.address.strip()
            if len(short_addr) > 40:
                short_addr = short_addr[:37] + "…"
            parts.append(short_addr)

        btn_text = " | ".join(parts)
        kb.row(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"select_sc_for_request:{sc.id}",
            )
        )
        lines.append(f"• <b>{sc.name}</b> — {dist:.1f} км")

    kb.row(
        InlineKeyboardButton(
            text="📤 Отправить всем подходящим",
            callback_data="request_send_to_all",
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="⬅️ К полному списку",
            callback_data="request_back_to_service_list",
        )
    )

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )

    # Возвращаемся к состоянию выбора сервиса (дальше сработает select_sc_for_request)
    await state.set_state(RequestForm.service_center)


async def _ask_service_center_for_request_from_message(message: Message, state: FSMContext):
    """
    Обёртка над _ask_service_center_for_request, когда мы в контексте Message,
    а не CallbackQuery (например, после отмены поиска ближайших).
    """
    fake_callback = CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data="",
    )
    await _ask_service_center_for_request(fake_callback, state)


@router.callback_query(RequestForm.service_center, F.data == "request_send_to_all")
async def request_send_to_all(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал вариант 'Отправить всем подходящим'.
    Логика:
    - Явно НЕ привязываем заявку к конкретному СТО (service_center_id = None).
    - Созданная заявка уйдёт в общий менеджерский канал / MANAGER_CHAT_ID.
    """
    # Явно обнуляем привязку к конкретному сервису
    await state.update_data(service_center_id=None, send_mode="all")

    await callback.message.edit_text(
        "📤 Заявка будет отправлена всем подходящим автосервисам.\n\n"
        "Теперь опишите, пожалуйста, проблему с автомобилем как можно подробнее:\n"
        "что случилось, при каких условиях проявляется, были ли уже ремонты и т.п.",
        reply_markup=None,
    )
    await state.set_state(RequestForm.description)
    await callback.answer()


@router.callback_query(F.data == "cancel_request")
async def cancel_request(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Создание заявки отменено.\n\n"
        "Главное меню:",
        reply_markup=get_main_kb()
    )
    await callback.answer()


@router.callback_query(
    RequestForm.car_selection, F.data.startswith("select_car_for_request:")
)
async def select_car_for_request(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал авто из списка при создании заявки.

    Новая логика:
    1) Сохраняем car_id.
    2) Переходим к выбору типа/подтипа работ.
    3) Только после этого показываем список СТО, подходящих по категории.
    """
    try:
        car_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Не удалось определить автомобиль 🤔", show_alert=True)
        return

    # Сохраняем ID автомобиля в состоянии
    await state.update_data(car_id=car_id)

    # Дальше — единый шаг выбора вида работ
    await _start_request_service_type_step(callback, state)
    await callback.answer()


@router.callback_query(RequestForm.service_center, F.data.startswith("select_sc_for_request:"))
async def select_sc_for_request(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал конкретный автосервис из списка.
    После этого просим описать проблему.
    """
    try:
        sc_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Не удалось понять, какой автосервис выбран 🤔", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).where(
                ServiceCenter.id == sc_id,
                ServiceCenter.owner_user_id.isnot(None),
            )
        )
        sc: ServiceCenter | None = result.scalar_one_or_none()

    if not sc:
        await callback.answer(
            "❌ Автосервис не найден или недоступен. Попробуйте выбрать другой.",
            show_alert=True,
        )
        return

    # Сохраняем выбранный сервис в состоянии заявки
    await state.update_data(service_center_id=sc.id)

    rating_text = ""
    if sc.ratings_count and sc.ratings_count > 0:
        rating_text = f"\n⭐ Рейтинг: {sc.rating:.1f} (на основе {sc.ratings_count} оценок)"

    await callback.message.edit_text(
        f"🏭 Вы выбрали автосервис:\n\n"
        f"<b>{sc.name}</b>\n"
        f"📍 {sc.address or 'Адрес не указан'}"
        f"{rating_text}\n\n"
        "Теперь опишите, пожалуйста, проблему с автомобилем как можно подробнее.",
        parse_mode="HTML",
    )

    await state.set_state(RequestForm.description)
    await callback.answer()


@router.callback_query(RequestForm.service_center, F.data == "request_back_to_service_list")
async def request_back_to_service_list(callback: CallbackQuery, state: FSMContext):
    """
    Возврат к обычному списку подходящих СТО (без учёта георадиуса).
    """
    await _ask_service_center_for_request(callback, state)
    await callback.answer()


@router.callback_query(RequestForm.service_type, F.data.startswith("service_group_"))
async def process_service_type(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал основную группу услуг.
    Для некоторых групп сразу ставим category_code и идём к выбору СТО,
    для других — уточняем подтип (шины, электрика, агрегаты).
    """
    group = callback.data  # например, "service_group_wash"

    # Группы, где нет подтипов — сразу пишем category_code
    direct_groups = {
        "service_group_wash": ("Мойка", "wash"),
        "service_group_mechanic": ("Слесарные работы", "mechanic"),
        "service_group_paint": ("Малярные работы", "paint"),
        "service_group_maint": ("ТО / техобслуживание", "maint"),
    }

    # Группы, где нужно уточнение подтипа
    subtype_groups = {
        "service_group_tire": get_tire_subtypes_kb,
        "service_group_electric": get_electric_subtypes_kb,
        "service_group_aggregates": get_aggregates_subtypes_kb,
    }

    # Если нужна детализация — показываем подтипы
    if group in subtype_groups:
        kb = subtype_groups[group]()
        await state.update_data(service_group=group)
        await callback.message.edit_text(
            "Уточните тип работ:",
            reply_markup=kb,
        )
        await state.set_state(RequestForm.service_subtype)
        await callback.answer()
        return

    # Прямые группы — сразу сохраняем тип и категорию и переходим к выбору СТО
    if group in direct_groups:
        service_name, category_code = direct_groups[group]

        await state.update_data(
            service_type=service_name,
            category_code=category_code,
        )

        logger.info(
            "✅ Выбран тип работ без подтипа: %s (category_code=%s)",
            service_name, category_code,
        )

        # Сначала тип работ → затем список подходящих СТО
        await _ask_service_center_for_request(callback, state)
        await callback.answer()
        return

    await callback.answer("Неизвестный тип работ 🤔", show_alert=True)


@router.callback_query(
    RequestForm.service_subtype,
    (F.data.startswith("service_tire_") |
     F.data.startswith("service_electric_") |
     F.data.startswith("service_agg_"))
)
async def process_service_subtype(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал подтип услуг (шиномонтаж, электрика, агрегаты).
    Сохраняем человекочитаемое имя + category_code и переходим к выбору СТО.
    """
    service_data = callback.data  # например, "service_tire_stationary"

    subtype_map = {
        "service_tire_stationary": (
            "Стационарный шиномонтаж",
            "tire",
        ),
        "service_tire_mobile": (
            "Выездной шиномонтаж",
            "tire",
        ),
        "service_electric_stationary": (
            "Автоэлектрик / диагностика (в сервисе)",
            "electric",
        ),
        "service_electric_mobile": (
            "Выездной автоэлектрик",
            "electric",
        ),
        "service_agg_turbo": (
            "Ремонт турбин",
            "agg_turbo",
        ),
        "service_agg_starter": (
            "Ремонт стартеров и генераторов",
            "agg_starter",
        ),
        "service_agg_generator": (
            "Ремонт генераторов",
            "agg_generator",
        ),
        "service_agg_steering": (
            "Ремонт рулевых реек и ГУР",
            "agg_steering",
        ),
    }

    info = subtype_map.get(service_data)
    if not info:
        await callback.answer("Неизвестный подтип услуги 🤔", show_alert=True)
        return

    service_name, category_code = info

    await state.update_data(
        service_type=service_name,
        category_code=category_code,
    )

    logger.info(
        "✅ Выбран подтип работ: %s (category_code=%s, raw=%s)",
        service_name,
        category_code,
        service_data,
    )

    # Дальше — выбор автосервиса, который оказывает такие услуги
    await _ask_service_center_for_request(callback, state)
    await callback.answer()


@router.message(RequestForm.description)
async def process_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    
    if len(description) < 5:
        await message.answer(
            "❌ Описание слишком короткое. Пожалуйста, опишите проблему подробнее "
            "(минимум 5 символов):",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    await state.update_data(description=description)
    
    await message.answer(
        "📷 Прикрепите фото проблемы (если есть) или нажмите «Пропустить».\n\n"
        "Важно: бот ожидает <b>одно</b> фото. После его отправки вы перейдёте к выбору времени.",
        parse_mode="HTML",
        reply_markup=get_photo_skip_kb()
    )
    await state.set_state(RequestForm.photo)



@router.callback_query(RequestForm.photo, F.data == "attach_photo")
async def attach_photo(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал отправку фото — просим одно фото.
    """
    await callback.message.edit_text(
        "📷 Пожалуйста, отправьте <b>одно</b> фото, иллюстрирующее проблему.\n\n"
        "После получения фото я спрошу, когда вам удобно выполнить работу.",
        parse_mode="HTML",
        reply_markup=None  # Без лишних кнопок, чтобы не путать пользователя
    )
    # Состояние остаётся RequestForm.photo — теперь мы ждём сообщение с photo
    await callback.answer()


@router.message(RequestForm.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """
    Принимаем одно фото, сохраняем его в состоянии и переходим к вопросу
    о возможности самостоятельного передвижения авто.
    """
    file_id = message.photo[-1].file_id  # самое большое превью
    
    await state.update_data(photo=file_id)
    
    await message.answer(
        "✅ Фото получено.\n\n"
        "Может ли автомобиль передвигаться своим ходом?",
        reply_markup=get_can_drive_kb(),
    )
    await state.set_state(RequestForm.can_drive)


@router.callback_query(RequestForm.photo, F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь решил не прикреплять фото.
    Переходим к вопросу: может ли авто ехать само.
    """
    await callback.message.edit_text(
        "Может ли автомобиль передвигаться своим ходом?",
        reply_markup=get_can_drive_kb(),
    )
    await state.set_state(RequestForm.can_drive)
    await callback.answer()


@router.callback_query(RequestForm.can_drive, F.data.in_(["can_drive_yes", "can_drive_no"]))
async def process_can_drive(callback: CallbackQuery, state: FSMContext):
    """
    Обработка ответа на вопрос:
    Может ли автомобиль передвигаться своим ходом?

    Текущая логика (пока без перестановки шагов):
    - если машина МОЖЕТ ехать сама → локацию не спрашиваем, сразу спрашиваем дату;
    - если НЕ может → спрашиваем местоположение (гео/адрес) по новому сценарию.
    """
    can_drive = callback.data == "can_drive_yes"
    await state.update_data(can_drive=can_drive)

    if can_drive:
        # Машина едет сама — не трогаем геолокацию, сразу спрашиваем дату
        await callback.message.edit_text(
            "⏰ Когда вам удобно выполнить работу?\n\n"
            "Напишите дату или период в свободной форме "
            "(например, «Сегодня», «Завтра после обеда», «В выходные»)."
        )
        await state.set_state(RequestForm.preferred_date)
    else:
        # Нужен эвакуатор / выездной мастер — местоположение важно
        # Новый текст ближе к ТЗ: «Отправьте геолокацию или укажите местоположение на карте…»
        await callback.message.edit_text(
            "📍 Отправьте геолокацию или укажите местоположение автомобиля на карте.\n\n"
            "Вы можете:\n"
            "• нажать «📍 Отправить геопозицию» и выбрать точку на карте в Telegram;\n"
            "• или написать адрес/ориентиры вручную (улица, дом, ориентир).\n\n"
            "Если не хотите указывать местоположение сейчас, нажмите "
            "«⏭️ Пропустить (укажу позже)».",
        )
        await callback.message.answer(
            "Отправьте геопозицию через кнопку ниже или введите адрес текстом:",
            reply_markup=get_location_reply_kb(),
        )
        await state.set_state(RequestForm.location)

    await callback.answer()


@router.callback_query(RequestForm.confirm, F.data == "confirm_request")
async def confirm_request(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    car_id = data.get("car_id")
    service_type = data.get("service_type")
    description = data.get("description")
    photo_id = data.get("photo")
    preferred_date = data.get("preferred_date")

    can_drive = data.get("can_drive")
    loc_lat = data.get("location_lat")
    loc_lon = data.get("location_lon")
    loc_desc = data.get("location_description")
    service_center_id = data.get("service_center_id")
    category_code = data.get("category_code")  # 🔹 новое поле

    if not car_id:
        await callback.message.edit_text(
            "❌ Автомобиль для заявки не выбран.",
            reply_markup=get_main_kb()
        )
        await state.clear()
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        try:
            # Находим пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                await callback.message.edit_text(
                    "❌ Пользователь не найден. Начните с /start",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                await callback.answer()
                return

            # Проверяем, что авто принадлежит пользователю
            car_result = await session.execute(
                select(Car).where(Car.id == car_id, Car.user_id == user.id)
            )
            car = car_result.scalar_one_or_none()

            if not car:
                await callback.message.edit_text(
                    "❌ Автомобиль не найден.",
                    reply_markup=get_main_kb()
                )
                await state.clear()
                await callback.answer()
                return

            # Создаём заявку
            new_request = Request(
                user_id=user.id,
                car_id=car.id,
                service_type=service_type,
                category_code=category_code,
                description=description,
                photo_file_id=photo_id,
                status="new",
                preferred_date=preferred_date,
                can_drive=can_drive,
                location_lat=loc_lat,
                location_lon=loc_lon,
                location_description=loc_desc,
                service_center_id=service_center_id,
            )

            session.add(new_request)
            await session.commit()

            # ✅ Бонус за создание заявки
            try:
                await add_bonus(
                    callback.from_user.id,
                    "new_request",
                    description=f"Создание заявки #{new_request.id}",
                )
            except Exception as bonus_err:
                logging.error(f"❌ Ошибка начисления бонуса за создание заявки: {bonus_err}")

            # 🔔 Уведомляем менеджера/сервис о новой заявке
            try:
                await notify_manager_about_new_request(callback.bot, new_request.id)
            except Exception as notify_error:
                logging.error(f"❌ Ошибка при отправке уведомления менеджеру: {notify_error}")

            await callback.message.edit_text(
                "✅ Ваша заявка отправлена менеджеру!\n\n"
                "Вам придет уведомление, когда менеджер начнет обработку.",
                reply_markup=get_main_kb()
            )
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении заявки: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при создании заявки. Попробуйте позже.",
                reply_markup=get_main_kb()
            )

    await state.clear()
    await callback.answer()


@router.callback_query(RequestForm.confirm, F.data == "edit_request")
async def edit_request(callback: CallbackQuery, state: FSMContext):
    """
    Вход в режим редактирования заявки до сохранения.
    Показываем меню: что именно пользователь хочет изменить.
    """
    data = await state.get_data()
    current_preferred = data.get("preferred_date") or data.get("preferred_date_raw") or "не указано"
    location_desc = data.get("location_description")
    if data.get("location_lat") and data.get("location_lon"):
        location_short = "указаны координаты"
    elif location_desc:
        location_short = location_desc[:70] + ("…" if len(location_desc) > 70 else "")
    else:
        location_short = "не указано"

    text = (
        "✏️ <b>Редактирование заявки</b>\n\n"
        "Вы можете изменить отдельные поля заявки перед отправкой менеджеру:\n"
        "• описание проблемы;\n"
        "• местоположение автомобиля;\n"
        "• дату и удобный интервал времени.\n\n"
        f"Текущая дата/время: <i>{current_preferred}</i>\n"
        f"Текущее местоположение: <i>{location_short}</i>\n\n"
        "Что вы хотите изменить?"
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_request_edit_kb(),
    )
    await callback.answer()


@router.callback_query(RequestForm.confirm, F.data == "edit_req_description")
async def edit_req_description(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет изменить описание проблемы.
    Переводим в отдельное состояние RequestForm.edit_description.
    """
    data = await state.get_data()
    current_descr = data.get("description") or "ещё не заполнено"

    await callback.message.edit_text(
        "📝 Отправьте новое описание проблемы.\n\n"
        "Чем подробнее вы опишете симптомы, тем точнее будет диагностика и расчёт стоимости.\n\n"
        f"<b>Сейчас указано:</b>\n{current_descr}",
        parse_mode="HTML",
        reply_markup=get_car_cancel_kb(),
    )
    await state.set_state(RequestForm.edit_description)
    await callback.answer()


@router.callback_query(RequestForm.confirm, F.data == "edit_req_location")
async def edit_req_location(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет изменить местоположение автомобиля.
    Возвращаем его на шаг RequestForm.location и даём те же подсказки,
    что и при первичном вводе локации.
    """
    data = await state.get_data()
    can_drive = data.get("can_drive")

    # Общий текст без привязки к тому, может ли ехать сам:
    # пользователь сам решает, указать ли текущее место или район.
    await callback.message.edit_text(
        "📍 Давайте обновим местоположение автомобиля.\n\n"
        "Вы можете:\n"
        "• нажать «📍 Отправить геопозицию» и выбрать точку на карте в Telegram;\n"
        "• или написать адрес/ориентиры вручную (улица, дом, ориентир).\n\n"
        "Если не хотите указывать местоположение сейчас, нажмите "
        "«⏭️ Пропустить (укажу позже)».",
    )
    await callback.message.answer(
        "Отправьте геопозицию через кнопку ниже или введите адрес текстом:",
        reply_markup=get_location_reply_kb(),
    )

    await state.set_state(RequestForm.location)
    await callback.answer()


@router.message(RequestForm.edit_description)
async def process_edit_description(message: Message, state: FSMContext):
    """
    Обработка нового описания проблемы в режиме редактирования.
    После сохранения заново показываем превью заявки и возвращаемся к confirm.
    """
    text = (message.text or "").strip()

    if len(text) < 5:
        await message.answer(
            "❌ Описание слишком короткое. Пожалуйста, опишите проблему чуть подробнее.",
            reply_markup=get_car_cancel_kb(),
        )
        return

    # Обновляем описание в состоянии
    await state.update_data(description=text)
    data = await state.get_data()

    preview_text = _build_request_preview_text(data)

    await message.answer(
        preview_text,
        reply_markup=get_request_confirm_kb(),
    )
    await state.set_state(RequestForm.confirm)


@router.callback_query(RequestForm.confirm, F.data == "edit_req_time")
async def edit_req_time(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь хочет изменить дату/время выполнения работ.
    Возвращаемся на шаг ввода preferred_date, сохранив остальные данные.
    """
    data = await state.get_data()
    current = data.get("preferred_date") or data.get("preferred_date_raw") or "не указано"

    await callback.message.edit_text(
        "⏰ Когда вам удобно выполнить работу?\n\n"
        "Напишите дату или период (например, «Сегодня», «Завтра после 18:00», "
        "«На этой неделе»).\n\n"
        f"Сейчас указано: {current}",
        reply_markup=get_car_cancel_kb(),
    )
    await state.set_state(RequestForm.preferred_date)
    await callback.answer()


@router.callback_query(RequestForm.confirm, F.data == "edit_req_cancel")
async def edit_req_cancel(callback: CallbackQuery, state: FSMContext):
    """
    Отмена создания заявки из меню редактирования.
    Полностью очищаем состояние и возвращаем в главное меню.
    """
    await state.clear()
    await callback.message.edit_text(
        "❌ Создание заявки отменено.\n\n"
        "Главное меню:",
        reply_markup=get_main_kb(),
    )
    await callback.answer()


CLIENT_PAGE_SIZE = 5

# Ключи фильтров для истории заявок клиента
CLIENT_STATUS_FILTERS = {
    "all": None,  # все заявки
    "active": ["new", "offer_sent", "accepted", "accepted_by_client", "in_progress"],
    "archived": ["completed", "rejected"],
    "new": ["new", "offer_sent"],
    "accepted": ["accepted", "accepted_by_client"],
    "in_progress": ["in_progress"],
    "completed": ["completed"],
    "rejected": ["rejected"],
}

CLIENT_FILTER_TITLES = {
    "all": "Все заявки",
    "active": "Активные заявки",
    "archived": "Архив заявок",
    "new": "Новые заявки",
    "accepted": "Принятые заявки",
    "in_progress": "Заявки в работе",
    "completed": "Завершённые заявки",
    "rejected": "Отклонённые заявки",
}


@router.callback_query(F.data == "my_requests")
async def my_requests(callback: CallbackQuery, state: FSMContext):
    """
    Мои заявки — сразу показываем список с фильтрами и пагинацией.
    По умолчанию — все заявки.
    """
    await state.clear()
    await show_requests_list(callback, filter_key="all", page=1)
    await callback.answer()


@router.callback_query(F.data == "history_active")
async def history_active(callback: CallbackQuery, state: FSMContext):
    """
    Старый пункт меню "Активные" — делаем просто пресет фильтра.
    """
    await state.clear()
    await show_requests_list(callback, filter_key="active", page=1)
    await callback.answer()


@router.callback_query(F.data == "history_archived")
async def history_archived(callback: CallbackQuery, state: FSMContext):
    """
    Старый пункт меню "Архив" — пресет фильтра archived.
    """
    await state.clear()
    await show_requests_list(callback, filter_key="archived", page=1)
    await callback.answer()


@router.callback_query(F.data.startswith("history_filter:"))
async def history_filter(callback: CallbackQuery, state: FSMContext):
    """
    Универсальный обработчик фильтров/страниц истории.
    Формат callback_data: history_filter:<filter_key>:<page>
    """
    if not callback.data:
        await callback.answer()
        return

    try:
        _, filter_key, raw_page = callback.data.split(":")
        page = int(raw_page)
    except Exception:
        await callback.answer("Некорректные данные фильтра.", show_alert=True)
        return

    await state.clear()
    await show_requests_list(callback, filter_key=filter_key, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("open_request:"))
async def open_request(callback: CallbackQuery, state: FSMContext):
    """
    Клиент открывает карточку своей заявки.
    Показываем полную информацию + кнопку '📩 Написать в сервис'.
    """
    try:
        request_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректный ID заявки", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Request, ServiceCenter, Car)
            .join(Car, Request.car_id == Car.id)
            .outerjoin(ServiceCenter, Request.service_center_id == ServiceCenter.id)
            .where(Request.id == request_id)
        )
        row = result.first()

    if not row:
        await callback.message.edit_text("❌ Заявка не найдена.", reply_markup=get_main_kb())
        await callback.answer()
        return

    request, sc, car = row

    # Формируем текст
    status_map = {
        "new": "🆕 Новая",
        "offer_sent": "📨 Есть предложение от сервиса",
        "accepted_by_client": "👍 Принята клиентом",
        "accepted": "👌 Принята сервисом",
        "in_progress": "🔧 В работе",
        "completed": "🏁 Завершена",
        "rejected": "❌ Отклонена",
    }
    status_text = status_map.get(request.status, request.status)

    text_lines = [
        f"📄 <b>Заявка #{request.id}</b>",
        "",
        f"🚗 Автомобиль: {car.brand} {car.model} ({car.year})",
        f"🔧 Работы: {request.service_type}",
        f"📝 Описание: {request.description}",
        f"📷 Фото: {'Есть' if request.photo_file_id else 'Нет'}",
        f"⏰ Удобное время: {request.preferred_date}",
        "",
        f"📍 Статус: <b>{status_text}</b>",
    ]

    if sc:
        text_lines.append("")
        text_lines.append(f"🏭 Сервис: <b>{sc.name}</b>")
        text_lines.append(f"📍 Адрес: {sc.address or '—'}")
        text_lines.append(f"☎️ Телефон скрыт (покажем после выбора сервиса)")

    # ==== Клавиатура ====
    kb = InlineKeyboardBuilder()

    # Кнопка "Написать в сервис"
    if sc and sc.owner_user_id:
        async with AsyncSessionLocal() as session:
            owner_res = await session.execute(
                select(User).where(User.id == sc.owner_user_id)
            )
            owner = owner_res.scalar_one_or_none()

        if owner and owner.telegram_id:
            kb.row(
                InlineKeyboardButton(
                    text="📩 Написать в сервис",
                    url=f"tg://user?id={owner.telegram_id}"
                )
            )

    kb.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="my_requests"
        )
    )

    await callback.message.edit_text(
        "\n".join(text_lines),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await callback.answer()


async def show_requests_list(
    callback: CallbackQuery,
    filter_key: str = "all",
    page: int = 1,
):
    """
    Список заявок клиента с учётом фильтра и пагинации.

    Используется хендлерами:
      - my_requests
      - history_active
      - history_archived
      - history_filter
    """
    if page < 1:
        page = 1

    # Проверяем фильтр
    if filter_key not in CLIENT_STATUS_FILTERS:
        filter_key = "all"

    status_filter = CLIENT_STATUS_FILTERS[filter_key]

    async with AsyncSessionLocal() as session:
        # 1. Находим пользователя
        user_res = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_res.scalar_one_or_none()

        if not user:
            await callback.message.edit_text(
                "❌ Пользователь не найден. Начните с /start"
            )
            await callback.answer()
            return

        # 2. Загружаем ВСЕ его заявки + привязанное авто
        req_res = await session.execute(
            select(Request, Car)
            .join(Car, Request.car_id == Car.id, isouter=True)
            .where(Request.user_id == user.id)
            .order_by(Request.created_at.desc())
        )
        rows = req_res.all()

    # Фильтруем по статусу в Python, чтобы не тянуть func/count и т.п.
    if status_filter:
        rows = [row for row in rows if row[0].status in status_filter]

    total = len(rows)
    if total == 0:
        title = CLIENT_FILTER_TITLES.get(filter_key, "Заявки")
        await callback.message.edit_text(
            f"📋 <b>{title}</b>\n\n"
            "По данному фильтру у вас пока нет заявок.",
            parse_mode="HTML",
            reply_markup=_build_history_kb(filter_key, 1, 1),
        )
        await callback.answer()
        return

    total_pages = max(1, (total + CLIENT_PAGE_SIZE - 1) // CLIENT_PAGE_SIZE)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * CLIENT_PAGE_SIZE
    end = start + CLIENT_PAGE_SIZE
    page_rows = rows[start:end]

    status_map = {
        "new": "🆕 Новая",
        "offer_sent": "📨 Есть предложение",
        "accepted_by_client": "👍 Принята вами",
        "accepted": "👌 Принята сервисом",
        "in_progress": "🔧 В работе",
        "completed": "🏁 Завершена",
        "rejected": "❌ Отклонена",
    }

    title = CLIENT_FILTER_TITLES.get(filter_key, "Заявки")
    lines: list[str] = [
        f"📋 <b>{title}</b> (стр. {page}/{total_pages})",
        "",
    ]

    for req, car in page_rows:
        status_txt = status_map.get(req.status, req.status)

        created = (
            req.created_at.strftime("%d.%m.%Y %H:%M") if req.created_at else "—"
        )

        if car:
            car_str_parts = [
                p
                for p in [
                    car.brand,
                    car.model,
                    str(car.year) if car.year else None,
                    car.license_plate,
                ]
                if p
            ]
            car_str = " ".join(car_str_parts) if car_str_parts else "Авто"
        else:
            car_str = "Авто не указано"

        lines.append(
            f"• <b>Заявка #{req.id}</b> — {status_txt}\n"
            f"   🚗 {car_str}\n"
            f"   🕒 {created}\n"
        )

    # Кнопки: открыть заявку + фильтры/пагинация
    base_kb = InlineKeyboardBuilder()
    for req, _car in page_rows:
        base_kb.row(
            InlineKeyboardButton(
                text=f"🔍 Открыть заявку #{req.id}",
                callback_data=f"open_request:{req.id}",
            )
        )

    # Склеиваем с навигацией по фильтрам/страницам
    nav_kb = _build_history_kb(filter_key, page, total_pages)

    # Соберём итоговую клавиатуру: сначала кнопки заявок, потом фильтры/страницы
    full_kb = InlineKeyboardBuilder()
    for row in base_kb.as_markup().inline_keyboard:
        full_kb.row(*row)
    for row in nav_kb.inline_keyboard:
        full_kb.row(*row)

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=full_kb.as_markup(),
    )
    await callback.answer()


def _build_history_kb(filter_key: str, page: int, total_pages: int):
    """
    Клавиатура для истории заявок: фильтры + пагинация.
    """
    builder = InlineKeyboardBuilder()

    def ftxt(key: str, label: str) -> str:
        return f"• {label}" if key == filter_key else label

        # Основные фильтры
    builder.row(
        InlineKeyboardButton(
            text=ftxt("all", "📋 Все"),
            callback_data="history_filter:all:1",
        ),
        InlineKeyboardButton(
            text=ftxt("active", "🟢 Активные"),
            callback_data="history_filter:active:1",
        ),
        InlineKeyboardButton(
            text=ftxt("archived", "📁 Архив"),
            callback_data="history_filter:archived:1",
        ),
    )

    # Детальные фильтры
    builder.row(
        InlineKeyboardButton(
            text=ftxt("new", "🆕 Новые"),
            callback_data="history_filter:new:1",
        ),
        InlineKeyboardButton(
            text=ftxt("accepted", "👍 Приняты"),
            callback_data="history_filter:accepted:1",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=ftxt("in_progress", "🔧 В работе"),
            callback_data="history_filter:in_progress:1",
        ),
        InlineKeyboardButton(
            text=ftxt("completed", "🏁 Завершённые"),
            callback_data="history_filter:completed:1",
        ),
        InlineKeyboardButton(
            text=ftxt("rejected", "❌ Отклонённые"),
            callback_data="history_filter:rejected:1",
        ),
    )

    # Пагинация
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"history_filter:{filter_key}:{page - 1}",
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"Стр. {page}/{total_pages}",
                callback_data=f"history_filter:{filter_key}:{page}",
            )
        )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Вперёд ➡️",
                    callback_data=f"history_filter:{filter_key}:{page + 1}",
                )
            )

        builder.row(*nav_buttons)

    # Назад в меню
    builder.row(
        InlineKeyboardButton(
            text="⬅️ В меню",
            callback_data="back_to_main",
        )
    )

    return builder.as_markup()


@router.callback_query(F.data.startswith("client_accept_offer:"))
async def client_accept_offer(callback: CallbackQuery):
    """Клиент подтверждает условия менеджера по заявке"""
    try:
        request_id = int(callback.data.split(":")[1])

        async with AsyncSessionLocal() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("❌ Пользователь не найден. Нажмите /start", show_alert=True)
                return

            req_result = await session.execute(
                select(Request).where(
                    Request.id == request_id,
                    Request.user_id == user.id,
                )
            )
            request = req_result.scalar_one_or_none()
            if not request:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request.status = "accepted"
            await session.commit()

        # ✅ Бонус за подтверждение условий
        try:
            await add_bonus(
                callback.from_user.id,
                "accept_offer",
                description=f"Подтверждение условий по заявке #{request_id}",
            )
        except Exception as bonus_err:
            logging.error(f"❌ Ошибка начисления бонуса за подтверждение условий: {bonus_err}")

        await callback.message.edit_text(
            f"✅ Вы подтвердили условия по заявке #{request_id}.\n"
            f"Менеджер свяжется с вами для записи и выполнения работ."
        )

        try:
            await callback.bot.send_message(
                chat_id=config.MANAGER_CHAT_ID,
                text=(
                    f"✅ Клиент подтвердил условия по заявке #{request_id}\n\n"
                    f"Комментарий менеджера:\n"
                    f"{request.manager_comment or '—'}"
                ),
            )
        except Exception as e:
            logging.error(f"❌ Не удалось уведомить менеджеров о принятии условий: {e}")

        try:
            from app.handlers.chat_handlers import update_chat_keyboard
            await update_chat_keyboard(callback.bot, request_id)
        except Exception as e:
            logging.error(f"❌ Не удалось обновить клавиатуру в чате заявки: {e}")

        await callback.answer()

    except Exception as e:
        logging.error(f"❌ Ошибка при подтверждении условий клиентом: {e}")
        await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)


@router.callback_query(F.data.startswith("client_reject_offer:"))
async def client_reject_offer(callback: CallbackQuery):
    """Клиент отклоняет условия менеджера по заявке"""
    try:
        request_id = int(callback.data.split(":")[1])

        async with AsyncSessionLocal() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("❌ Пользователь не найден. Нажмите /start", show_alert=True)
                return

            req_result = await session.execute(
                select(Request).where(
                    Request.id == request_id,
                    Request.user_id == user.id,
                )
            )
            request = req_result.scalar_one_or_none()
            if not request:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return

            request.status = "rejected"
            await session.commit()

        await callback.message.edit_text(
            f"❌ Вы отклонили условия по заявке #{request_id}.\n"
            f"Если хотите, вы можете создать новую заявку."
        )

        try:
            await callback.bot.send_message(
                chat_id=config.MANAGER_CHAT_ID,
                text=(
                    f"❌ Клиент отклонил условия по заявке #{request_id}\n\n"
                    f"Комментарий менеджера:\n"
                    f"{request.manager_comment or '—'}"
                ),
            )
        except Exception as e:
            logging.error(f"❌ Не удалось уведомить менеджеров об отказе: {e}")

        try:
            from app.handlers.chat_handlers import update_chat_keyboard
            await update_chat_keyboard(callback.bot, request_id)
        except Exception as e:
            logging.error(f"❌ Не удалось обновить клавиатуру в чате заявки: {e}")

        await callback.answer()

    except Exception as e:
        logging.error(f"❌ Ошибка при отказе от условий клиентом: {e}")
        await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)


# ✅ Новый хэндлер: экран "Мои бонусы"
@router.callback_query(F.data == "my_points")
async def my_points(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    balance, history = await get_user_balance(callback.from_user.id)

    if balance is None:
        await callback.message.edit_text(
            "❌ Пользователь не найден. Нажмите /start для регистрации.",
            reply_markup=get_main_kb(),
        )
        await callback.answer()
        return

    text_lines = [
        "🎁 <b>Ваши бонусы</b>\n",
        f"💰 Баланс: <b>{balance}</b> баллов\n",
    ]

    if history:
        text_lines.append("\n🕒 Последние начисления:\n")
        for tx in history:
            created_at = tx.created_at.strftime("%d.%m.%Y %H:%M") if tx.created_at else ""
            # action пока строкой, позже можем маппить в человекочитаемый текст
            text_lines.append(f"• {created_at} — +{tx.amount} за <i>{tx.action}</i>\n")
    else:
        text_lines.append("\nПока начислений нет. Совершайте действия в боте, чтобы получать баллы.\n")

    text_lines.append(
        "\nВ дальнейшем баллы можно будет использовать для скидок, акций и других механик монетизации."
    )

    await callback.message.edit_text(
        "".join(text_lines),
        parse_mode="HTML",
        reply_markup=get_main_kb(),
    )
    await callback.answer()


@router.message(Command("bind_group"))
async def bind_group_cmd(message: Message):
    """
    Привязка текущей группы к автосервису.

    Работает только:
    - если команда отправлена В ГРУППЕ/СУПЕРГРУППЕ,
    - и отправитель зарегистрирован как автосервис (owner).
    """
    # 1. Проверяем, что это группа
    if message.chat.type not in ("group", "supergroup"):
        await message.answer(
            "Эту команду нужно отправить в той группе, где вы хотите получать заявки.\n\n"
            "Зайдите в нужную группу и введите /bind_group."
        )
        return

    async with AsyncSessionLocal() as session:
        # 2. Находим пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role != "service":
            await message.answer(
                "Команда доступна только владельцам автосервисов.\n\n"
                "Отправьте /bind_group из-под аккаунта, который регистрировал сервис.",
            )
            return

        # 3. Находим автосервис этого пользователя
        sc_result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.owner_user_id == user.id)
        )
        service_center = sc_result.scalar_one_or_none()

        if not service_center:
            await message.answer(
                "Профиль автосервиса не найден.\n"
                "Попробуйте пройти регистрацию заново через /start.",
            )
            return

        # 4. Привязываем текущую группу
        service_center.manager_chat_id = message.chat.id
        service_center.send_to_group = True
        # send_to_owner не трогаем — сохраняем выбор из мастера
        await session.commit()

    await message.answer(
        "✅ Эта группа успешно привязана к вашему автосервису.\n"
        "Теперь все новые заявки будут отправляться сюда.",
    )


@router.callback_query(F.data.startswith("rate_request:"))
async def handle_rate_request(callback: CallbackQuery):
    """
    Клиент ставит оценку сервису по заявке.

    Формат callback_data:
        rate_request:<request_id>:<score>
    """
    try:
        _, raw_req_id, raw_score = callback.data.split(":")
        request_id = int(raw_req_id)
        score = int(raw_score)
    except Exception:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    if score < 1 or score > 5:
        await callback.answer("Оценка должна быть от 1 до 5", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        # 1. Грузим заявку с клиентом и сервисом
        result = await session.execute(
            select(Request, User, ServiceCenter)
            .join(User, Request.user_id == User.id)
            .join(ServiceCenter, Request.service_center_id == ServiceCenter.id, isouter=True)
            .where(Request.id == request_id)
        )
        row = result.first()

        if not row:
            await callback.answer("Заявка не найдена", show_alert=True)
            return

        request, user, service_center = row

        # Проверяем, что оценку ставит владелец заявки
        if user.telegram_id != callback.from_user.id:
            await callback.answer("Вы не можете оценить чужую заявку.", show_alert=True)
            return

        # Разрешаем оценку только по завершённой заявке
        if request.status != "completed":
            await callback.answer(
                "Оценить можно только завершённую заявку.",
                show_alert=True,
            )
            return

        # 2. Проверяем, не ставил ли пользователь уже рейтинг по этой заявке
        result = await session.execute(
            select(Comment)
            .where(
                Comment.request_id == request.id,
                Comment.user_id == user.id,
                Comment.message.like("RATING:%"),
            )
        )
        existing_rating = result.scalar_one_or_none()
        if existing_rating:
            await callback.answer("Вы уже оценили этот сервис по данной заявке.", show_alert=True)
            return

        # 3. Сохраняем "оценочный" комментарий
        rating_comment = Comment(
            request_id=request.id,
            user_id=user.id,
            message=f"RATING:{score}",
            is_manager=False,
        )
        session.add(rating_comment)

        # 4. Обновляем средний рейтинг сервиса
        if service_center:
            old_avg = service_center.rating or 0.0
            old_count = service_center.ratings_count or 0

            new_count = old_count + 1
            new_avg = (old_avg * old_count + score) / new_count

            service_center.rating = new_avg
            service_center.ratings_count = new_count

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении оценки по заявке #{request_id}: {e}")
            await callback.answer("Ошибка при сохранении оценки, попробуйте позже.", show_alert=True)
            return

    # 5. Начисляем бонус за оценку
    try:
        await add_bonus(
            callback.from_user.id,
            "rate_service",
            description=f"Оценка сервиса по заявке #{request_id} на {score}⭐",
        )
    except Exception as bonus_err:
        logging.error(f"⚠️ Не удалось начислить бонус за оценку: {bonus_err}")

    await callback.answer("Спасибо за вашу оценку! 🙌", show_alert=True)


@router.callback_query(
    RequestForm.service_subtype,
    F.data == "service_back_to_groups",
)
async def service_back_to_groups(callback: CallbackQuery, state: FSMContext):
    """
    Возврат из подтипов к выбору основной группы услуг.
    """
    # Можно при желании чистить старый подтип/категорию:
    await state.update_data(service_type=None, category_code=None)
    await _start_request_service_type_step(callback, state)
    await callback.answer()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Расстояние между двумя точками по сфере (приблизительно по Земле) в километрах.
    """
    R = 6371.0  # радиус Земли, км

    lat1_r = radians(lat1)
    lon1_r = radians(lon1)
    lat2_r = radians(lat2)
    lon2_r = radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


@router.callback_query(F.data == "service_centers_search")
async def service_centers_search(callback: CallbackQuery, state: FSMContext):
    """
    Начало поиска сервисов по радиусу.
    """
    await state.clear()

    await callback.message.edit_text(
        "🌍 Выберите радиус поиска:",
        reply_markup=get_search_radius_kb()
    )
    await state.set_state(ServiceSearchStates.radius)
    await callback.answer()


@router.callback_query(ServiceSearchStates.radius, F.data.startswith("radius:"))
async def select_radius(callback: CallbackQuery, state: FSMContext):
    radius = int(callback.data.split(":")[1])
    await state.update_data(radius=radius)

    await callback.message.edit_text(
        "📍 Отправьте свою геолокацию для поиска СТО:",
    )
    await callback.message.answer(
        "Нажмите кнопку ниже, чтобы отправить координаты:",
        reply_markup=get_location_reply_kb(),
    )

    await state.set_state(ServiceSearchStates.location)
    await callback.answer()


@router.message(ServiceSearchStates.location, F.location)
async def search_services_by_geo(message: Message, state: FSMContext):
    """
    Основная логика поиска сервисов по радиусу.
    Добавлен fallback — если внутри радиуса никого нет, предлагаем показать всех.
    """
    loc = message.location
    user_lat = loc.latitude
    user_lon = loc.longitude

    # ✅ Убираем клавиатуру с гео
    await message.answer(
        "✅ Геолокация получена, ищу подходящие сервисы...",
        reply_markup=ReplyKeyboardRemove(),
    )

    data = await state.get_data()
    radius = data.get("radius", 10)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.owner_user_id.isnot(None))
        )
        all_services = result.scalars().all()

    # ===== Фильтруем по радиусу =====
    nearby = []
    far_services = []
    no_geo = []

    for sc in all_services:
        if sc.location_lat is None or sc.location_lon is None:
            no_geo.append(sc)
            continue

        dist = _haversine_km(user_lat, user_lon, sc.location_lat, sc.location_lon)
        if dist <= radius:
            nearby.append((sc, dist))
        else:
            far_services.append((sc, dist))

    # ===== Если внутри радиуса НИКОГО =====
    if not nearby:
        builder = InlineKeyboardBuilder()

        builder.row(
            InlineKeyboardButton(
                text="🔍 Показать всех доступных СТО",
                callback_data="show_all_services"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="service_centers_search"
            )
        )

        await message.answer(
            "❗ В выбранном радиусе СТО не найдено.\n"
            "Хотите посмотреть ВСЕ доступные сервисы (с гео и без гео)?",
            reply_markup=builder.as_markup()
        )
        await state.clear()
        return

    # ===== Вывод СТО по радиусу =====
    nearby.sort(key=lambda x: x[1])

    lines = ["🏭 <b>Сервисы рядом с вами</b>\n"]
    kb = InlineKeyboardBuilder()

    for sc, dist in nearby:
        dist_txt = f"{dist:.1f} км"
        kb.row(
            InlineKeyboardButton(
                text=f"{sc.name} — {dist_txt}",
                callback_data=f"select_sc_for_request:{sc.id}"
            )
        )
        lines.append(f"• <b>{sc.name}</b> — {dist_txt}")

    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="service_centers_search"))

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await state.clear()


@router.callback_query(F.data == "show_all_services")
async def show_all_services(callback: CallbackQuery, state: FSMContext):
    """
    Показывает все СТО: с геолокацией и без неё.
    Используется как fallback.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceCenter).where(ServiceCenter.owner_user_id.isnot(None))
        )
        services = result.scalars().all()

    if not services:
        await callback.message.edit_text(
            "❗ В системе пока нет автосервисов.",
            reply_markup=get_main_kb()
        )
        await callback.answer()
        return

    lines = ["🏭 <b>Все доступные СТО</b>\n"]
    kb = InlineKeyboardBuilder()

    for sc in services:
        kb.row(
            InlineKeyboardButton(
                text=sc.name,
                callback_data=f"select_sc_for_request:{sc.id}"
            )
        )
        lines.append(f"• <b>{sc.name}</b>")

    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="service_centers_search"))

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await callback.answer()
    await state.clear()


@router.message(ServiceSearchStates.location)
async def service_search_location(message: Message, state: FSMContext):
    """
    Шаг 1 поиска: получаем геолокацию пользователя.
    """
    if message.location:
        loc = message.location
        await state.update_data(
            search_lat=loc.latitude,
            search_lon=loc.longitude,
        )
        # ✅ убираем клавиатуру
        await message.answer(
            "✅ Геолокация получена.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "Выберите радиус поиска автосервисов:",
            reply_markup=get_search_radius_kb(),
        )
        await state.set_state(ServiceSearchStates.radius)
        return

    text = (message.text or "").strip().lower()
    if "пропустить" in text or "отмена" in text:
        await state.clear()
        await message.answer(
            "Поиск по локации отменён.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "Главное меню:",
            reply_markup=get_main_kb(),
        )
        return

    await message.answer(
        "Пожалуйста, отправьте именно геолокацию через кнопку "
        "«📍 Отправить геолокацию» внизу экрана."
    )


@router.callback_query(ServiceSearchStates.radius, F.data.startswith("search_radius:"))
async def service_search_radius(callback: CallbackQuery, state: FSMContext):
    """
    Шаг 2 поиска: выбран радиус, считаем расстояние до всех СТО с координатами.
    Показываем только "живые" сервисы (у которых есть владелец).
    """
    try:
        radius_km = float(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Не удалось понять радиус 😕", show_alert=True)
        return

    data = await state.get_data()
    lat = data.get("search_lat")
    lon = data.get("search_lon")

    if lat is None or lon is None:
        await state.clear()
        await callback.message.edit_text(
            "❌ Не удалось получить вашу геолокацию. Попробуйте начать поиск заново.",
            reply_markup=get_main_kb(),
        )
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        # 🔹 здесь добавили фильтр по owner_user_id, как в списке "Автосервисы"
        result = await session.execute(
            select(ServiceCenter).where(
                ServiceCenter.owner_user_id.isnot(None),
                ServiceCenter.location_lat.is_not(None),
                ServiceCenter.location_lon.is_not(None),
            )
        )
        services = result.scalars().all()

    nearby: list[tuple[ServiceCenter, float]] = []
    for sc in services:
        dist = _haversine_km(lat, lon, sc.location_lat, sc.location_lon)
        if dist <= radius_km:
            nearby.append((sc, dist))

    nearby.sort(key=lambda x: x[1])

    if not nearby:
        await callback.message.edit_text(
            f"😔 В радиусе {radius_km:.0f} км пока нет автосервисов "
            f"с указанной геолокацией.",
            reply_markup=get_main_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    lines: list[str] = [
        f"🔍 <b>Найдено автосервисов рядом с вами (до {radius_km:.0f} км)</b>\n"
    ]
    for sc, dist in nearby:
        rating_text = ""
        if getattr(sc, "ratings_count", None) and sc.ratings_count > 0:
            rating_text = f"⭐ {sc.rating:.1f} ({sc.ratings_count} оценок)"

        maps_url = (
            f"https://yandex.ru/maps/?ll={sc.location_lon:.6f}%2C{sc.location_lat:.6f}&z=16"
            if sc.location_lat is not None and sc.location_lon is not None
            else ""
        )

        block = (
            f"• <b>{sc.name}</b> — {dist:.1f} км\n"
            f"  📍 {sc.address or 'Адрес не указан'}\n"
            f"  ☎️ {sc.phone or 'Телефон не указан'}\n"
        )
        if maps_url:
            block += f"  🗺 <a href=\"{maps_url}\">Открыть на карте</a>\n"
        if rating_text:
            block += f"  {rating_text}\n"

        lines.append(block)

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_main_kb(),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(ServiceSearchStates.radius, F.data.startswith("search_radius_"))
async def service_search_radius_result(callback: CallbackQuery, state: FSMContext):
    """
    Шаг 3 поиска: пользователь выбрал радиус, показываем найденные СТО.
    """
    data = await state.get_data()
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        await callback.message.edit_text(
            "Не удалось определить геолокацию. Попробуйте начать поиск заново.",
            reply_markup=get_main_kb(),
        )
        await callback.answer()
        return

    try:
        radius_str = callback.data.split("_")[-1]
        radius_km = float(radius_str)
    except Exception:
        await callback.message.edit_text(
            "Некорректный радиус поиска. Попробуйте начать поиск заново.",
            reply_markup=get_main_kb(),
        )
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        # 🔹 здесь добавили фильтр по owner_user_id, как в списке "Автосервисы"
        result = await session.execute(
            select(ServiceCenter).where(
                ServiceCenter.owner_user_id.isnot(None),
                ServiceCenter.location_lat.is_not(None),
                ServiceCenter.location_lon.is_not(None),
            )
        )
        services = result.scalars().all()

    nearby: list[tuple[ServiceCenter, float]] = []
    for sc in services:
        dist = _haversine_km(lat, lon, sc.location_lat, sc.location_lon)
        if dist <= radius_km:
            nearby.append((sc, dist))

    nearby.sort(key=lambda x: x[1])

    if not nearby:
        await callback.message.edit_text(
            f"😔 В радиусе {radius_km:.0f} км пока нет автосервисов "
            f"с указанной геолокацией.",
            reply_markup=get_main_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    lines: list[str] = [
        f"🔍 <b>Найдено автосервисов рядом с вами (до {radius_km:.0f} км)</b>\n"
    ]
    for sc, dist in nearby:
        rating_text = ""
        if getattr(sc, "ratings_count", None) and sc.ratings_count > 0:
            rating_text = f"⭐ {sc.rating:.1f} ({sc.ratings_count} оценок)"

        maps_url = (
            f"https://yandex.ru/maps/?ll={sc.location_lon:.6f}%2C{sc.location_lat:.6f}&z=16"
            if sc.location_lat is not None and sc.location_lon is not None
            else ""
        )

        block = (
            f"• <b>{sc.name}</b> — {dist:.1f} км\n"
            f"  📍 {sc.address or 'Адрес не указан'}\n"
            f"  ☎️ {sc.phone or 'Телефон не указан'}\n"
        )
        if maps_url:
            block += f"  🗺 <a href=\"{maps_url}\">Открыть на карте</a>\n"
        if rating_text:
            block += f"  {rating_text}\n"

        lines.append(block)

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_main_kb(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_service_search")
async def cancel_service_search(callback: CallbackQuery, state: FSMContext):
    """
    Отмена сценария поиска СТО.
    """
    await state.clear()
    await callback.message.edit_text(
        "Поиск автосервисов отменён.\n\nГлавное меню:",
        reply_markup=get_main_kb(),
    )
    await callback.answer()
