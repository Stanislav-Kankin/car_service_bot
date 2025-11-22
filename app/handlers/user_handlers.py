from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from datetime import datetime
import logging

from app.services.notification_service import notify_manager_about_new_request
from app.services.bonus_service import add_bonus, get_user_balance
from app.database.models import User, Car, Request, ServiceCenter
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
    get_manager_main_kb, get_service_notifications_kb
)
from app.config import config


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
    # Основной тип услуги (группа работ)
    service_type = State()
    # Подтип услуги
    service_subtype = State()
    description = State()
    photo = State()
    can_drive = State()
    location = State()
    preferred_date = State()
    confirm = State()


class Registration(StatesGroup):
    role = State()
    name = State()
    service_name = State()
    service_address = State()
    phone = State()
    notifications = State()
    group_chat = State()


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    logging.info(f"🔄 Обработка /start для пользователя {message.from_user.id}")

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()

            # Пользователь уже есть в БД
            if user:
                if user.role == "service":
                    logging.info(
                        f"✅ Пользователь {message.from_user.id} уже зарегистрирован как автосервис"
                    )
                    await message.answer(
                        "🛠 Вы уже зарегистрированы как автосервис.\n"
                        "Используйте панель ниже или команду /manager для работы с заявками.",
                        reply_markup=get_manager_main_kb(),
                    )
                else:
                    logging.info(
                        f"✅ Пользователь {message.from_user.id} уже зарегистрирован как клиент"
                    )
                    await message.answer(
                        "🏠 Вы уже зарегистрированы. Главное меню:",
                        reply_markup=get_main_kb(),
                    )
                return

            # Пользователя нет — новая регистрация
            logging.info(f"🆕 Новый пользователь {message.from_user.id}")
            await message.answer(
                "👋 Добро пожаловать в CAR SERVICE BOT!\n\n"
                "Я помогу вам с обслуживанием вашего автомобиля: "
                "запись на сервис, шиномонтаж, эвакуатор и многое другое.\n\n"
                "Для начала работы нужно пройти простую регистрацию:",
                reply_markup=get_registration_kb(),
            )

        except Exception as e:
            logging.error(f"❌ Ошибка при обработке /start: {e}")
            await message.answer(
                "❌ Произошла ошибка при запуске. Попробуйте позже."
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

    # И теперь уже просим телефон, как и у клиента
    await message.answer(
        "Отлично! Теперь нажмите на кнопку ниже, чтобы отправить номер телефона:",
        reply_markup=get_phone_reply_kb(),
    )
    await state.set_state(Registration.phone)


@router.message(Registration.phone)
async def process_phone_registration(message: Message, state: FSMContext):
    if not message.contact:
        await message.answer(
            "📱 Пожалуйста, используйте кнопку для отправки номера телефона:",
            reply_markup=get_phone_reply_kb(),
        )
        return

    phone_number = message.contact.phone_number
    data = await state.get_data()
    name = data.get("name") or (message.from_user.full_name or "").strip() or "Без имени"
    role = data.get("role") or "client"
    service_name = data.get("service_name")
    service_address = data.get("service_address")

    async with AsyncSessionLocal() as session:
        try:
            # Ищем пользователя по telegram_id
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()

            if user:
                # Обновляем существующего
                user.full_name = name
                user.phone_number = phone_number
                user.role = role

                if role == "service":
                    user.service_name = service_name
                    user.service_address = service_address
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

            await session.commit()
            await session.refresh(user)

            # 🔗 Если это автосервис — создаём (или находим) ServiceCenter
            service_center_id: int | None = None
            if role == "service":
                sc_result = await session.execute(
                    select(ServiceCenter).where(ServiceCenter.owner_user_id == user.id)
                )
                service_center = sc_result.scalar_one_or_none()

                if not service_center:
                    service_center = ServiceCenter(
                        name=user.service_name or user.full_name,
                        address=user.service_address,
                        phone=user.phone_number,
                        owner_user_id=user.id,
                        # По умолчанию пока просто ЛС, далее настроим
                        send_to_owner=True,
                        send_to_group=False,
                        manager_chat_id=None,
                    )
                    session.add(service_center)
                    await session.commit()
                    await session.refresh(service_center)

                service_center_id = service_center.id

                logging.info(
                    f"✅ Зарегистрирован/обновлён автосервис для пользователя {message.from_user.id} "
                    f"(ServiceCenter id={service_center.id})"
                )
            else:
                logging.info(
                    f"🔄 Обновлена регистрация пользователя {message.from_user.id} (role={role})"
                )

        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении регистрации: {e}")
            await message.answer(
                "❌ Произошла ошибка при сохранении данных. Попробуйте позже.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

    # ✅ Клиент: сразу завершаем регистрацию
    if role != "service":
        await state.clear()

        await message.answer(
            "✅ Регистрация завершена!\n\n"
            "Теперь вы можете работать с ботом.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "🏠 Главное меню:",
            reply_markup=get_main_kb(),
        )

        # Бонус за регистрацию
        try:
            await add_bonus(
                message.from_user.id,
                "register",
                description="Регистрация в боте",
            )
        except Exception as bonus_err:
            logging.error(f"❌ Ошибка начисления бонуса за регистрацию: {bonus_err}")

        return

    # 🛠 Автосервис: идём на шаг выбора, куда слать заявки
    if not service_center_id:
        # На всякий случай, если что-то пошло не так
        await state.clear()
        await message.answer(
            "❌ Не удалось создать профиль автосервиса. Попробуйте /start ещё раз.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.update_data(service_center_id=service_center_id)

    await message.answer(
        "✅ Основные данные автосервиса сохранены.\n\n"
        "Теперь выберите, куда вы хотите получать новые заявки:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Куда слать заявки от клиентов?",
        reply_markup=get_service_notifications_kb(),
    )
    await state.set_state(Registration.notifications)


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
    F.data.in_(["sc_notif_owner", "sc_notif_group", "sc_notif_both"]),
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
        from app.database.models import ServiceCenter  # на случай локального импорта

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

        # Ветвление по варианту
        choice = callback.data

        if choice == "sc_notif_owner":
            service_center.send_to_owner = True
            service_center.send_to_group = False
            service_center.manager_chat_id = None

            await session.commit()
            await state.clear()

            await callback.message.edit_text(
                "✅ Заявки будут приходить вам в личные сообщения этого аккаунта.\n\n"
                "Регистрация завершена!",
            )
            await callback.message.answer(
                "🛠 Вы зарегистрированы как <b>автосервис</b>.\n\n"
                "Новые заявки будут приходить вам в этот бот.\n"
                "Позже вы сможете настроить получение заявок в отдельную группу.",
                parse_mode="HTML",
                reply_markup=get_manager_main_kb(),
            )

            # Бонус за регистрацию
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

        # Если нужна группа (с ЛС или без) — идём на шаг привязки группы
        send_to_owner = choice == "sc_notif_both"
        service_center.send_to_owner = send_to_owner
        service_center.send_to_group = True
        # manager_chat_id пока не знаем
        await session.commit()

    # Запоминаем, нужно ли слать ещё и в ЛС
    await state.update_data(send_to_owner_also=send_to_owner)
    await state.set_state(Registration.group_chat)

    await callback.message.edit_text(
        "👥 Отлично! Теперь нужно привязать группу Telegram для получения заявок.\n\n"
        "1️⃣ Добавьте этого бота в вашу группу и назначьте его администратором.\n"
        "2️⃣ Перешлите сюда <b>любое</b> сообщение из этой группы.\n\n"
        "После этого все новые заявки будут отправляться в указанную группу.",
        parse_mode="HTML",
    )
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
        + (" и вам в личные сообщения." if send_to_owner_also else "."),
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


#  Обработчик геолокации
@router.message(RequestForm.location, F.location)
async def process_location_geo(message: Message, state: FSMContext):
    loc = message.location
    await state.update_data(
        location_lat=loc.latitude,
        location_lon=loc.longitude,
        location_description=None,
    )

    await message.answer(
        "✅ Местоположение получено.\n\n"
        "⏰ Теперь укажите, когда вам удобно выполнить работу.\n"
        "Напишите удобное время в свободной форме (например, «Сегодня после 18:00»).",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RequestForm.preferred_date)


@router.message(RequestForm.location)
async def process_location_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    # Пропуск локации
    if text.lower().startswith("⏭️".lower()) or "пропустить" in text.lower():
        await state.update_data(
            location_lat=None,
            location_lon=None,
            location_description=None,
        )
    else:
        # Сохраняем текстовый адрес
        await state.update_data(
            location_lat=None,
            location_lon=None,
            location_description=text,
        )

    await message.answer(
        "⏰ Когда вам удобно выполнить работу?\n\n"
        "Напишите удобное время в свободной форме (например, «Сегодня после 18:00»).",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RequestForm.preferred_date)

#  Учитываем может ли ехать + гео
@router.message(RequestForm.preferred_date)
async def process_preferred_date(message: Message, state: FSMContext):
    preferred = (message.text or "").strip()
    if len(preferred) < 3:
        await message.answer(
            "❌ Слишком короткий ответ. Пожалуйста, укажите, когда вам удобно:",
            reply_markup=get_car_cancel_kb(),
        )
        return

    await state.update_data(preferred_date=preferred)
    data = await state.get_data()

    service_type = data.get("service_type", "Не указано")
    description = data.get("description", "Не указано")
    photo_id = data.get("photo")
    photos_text = "есть" if photo_id else "нет"

    can_drive = data.get("can_drive")
    if can_drive is True:
        can_drive_text = "Да, может ехать сам"
    elif can_drive is False:
        can_drive_text = "Нет, нужен эвакуатор/прицеп"
    else:
        can_drive_text = "Не указано"

    loc_lat = data.get("location_lat")
    loc_lon = data.get("location_lon")
    loc_desc = data.get("location_description")

    if loc_lat and loc_lon:
        location_text = f"Геолокация (координаты: {loc_lat:.5f}, {loc_lon:.5f})"
    elif loc_desc:
        location_text = f"Адрес/место: {loc_desc}"
    else:
        location_text = "Не указано"

    await message.answer(
        "📄 Заявка на услугу\n\n"
        f"🔧 Услуга: {service_type}\n"
        f"📝 Описание: {description}\n"
        f"📷 Фото: {photos_text}\n"
        f"🚚 Может ехать сам: {can_drive_text}\n"
        f"📍 Местоположение: {location_text}\n"
        f"⏰ Когда удобно: {preferred}\n\n"
        "Подтвердите создание заявки:",
        reply_markup=get_request_confirm_kb(),
    )
    await state.set_state(RequestForm.confirm)


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
            user_result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user_result.scalar_one_or_none()
            
            if not user:
                await callback.message.edit_text("❌ Пользователь не найден. Начните с /start")
                await callback.answer()
                return
            
            # Получаем автомобили
            cars_result = await session.execute(select(Car).where(Car.user_id == user.id))
            cars = cars_result.scalars().all()
            
            if not cars:
                await callback.message.edit_text(
                    "🚗 В вашем гараже пока нет автомобилей.\n\n"
                    "Сначала добавьте автомобиль:",
                    reply_markup=get_garage_kb()
                )
                await callback.answer()
                return
            
            # Показываем выбор автомобиля
            builder = InlineKeyboardBuilder()
            for car in cars:
                builder.row(
                    InlineKeyboardButton(
                        text=f"🚗 {car.brand} {car.model}",
                        callback_data=f"select_car_for_request:{car.id}"
                    )
                )
            builder.row(
                InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request")
            )
            
            await callback.message.edit_text(
                "📝 Создание заявки\n\n"
                "Выберите автомобиль для которого создается заявка:",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.error(f"❌ Ошибка при создании заявки: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при создании заявки. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
    await callback.answer()


@router.callback_query(F.data.startswith("create_request_for_car:"))
async def create_request_for_car(callback: CallbackQuery, state: FSMContext):
    """
    Создание заявки напрямую из карточки конкретного авто.
    По сути то же самое, что select_car_for_request, только без выбора авто.
    """
    await state.clear()
    car_id = int(callback.data.split(":")[1])

    # Сохраняем ID автомобиля в состоянии
    await state.update_data(car_id=car_id)

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


@router.callback_query(F.data.startswith("select_car_for_request:"))
async def select_car_for_request(callback: CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])

    # Сохраняем ID автомобиля в состоянии
    await state.update_data(car_id=car_id)

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
    await callback.answer()


@router.callback_query(RequestForm.service_type)
async def process_service_type(callback: CallbackQuery, state: FSMContext):
    service_data = callback.data

    if service_data == "service_back_to_groups":
        await callback.message.edit_text(
            "🛠️ Выберите вид работ:",
            reply_markup=get_service_types_kb()
        )
        await state.set_state(RequestForm.service_type)
        await callback.answer()
        return

    direct_groups = {
        "service_group_wash": "Автомойки",
        "service_group_mechanic": "Слесарные работы",
        "service_group_paint": "Малярные работы",
        "service_group_maint": "Техобслуживание",
    }

    if service_data == "service_group_tire":
        await callback.message.edit_text(
            "🛞 Шиномонтаж\n\n"
            "Выберите формат работы:",
            reply_markup=get_tire_subtypes_kb()
        )
        await state.set_state(RequestForm.service_subtype)
        await callback.answer()
        return

    if service_data == "service_group_electric":
        await callback.message.edit_text(
            "⚡ Автоэлектрик\n\n"
            "Выберите формат работы:",
            reply_markup=get_electric_subtypes_kb()
        )
        await state.set_state(RequestForm.service_subtype)
        await callback.answer()
        return

    if service_data == "service_group_aggregates":
        await callback.message.edit_text(
            "⚙️ Ремонт агрегатов\n\n"
            "Что именно требуется отремонтировать?",
            reply_markup=get_aggregates_subtypes_kb()
        )
        await state.set_state(RequestForm.service_subtype)
        await callback.answer()
        return

    if service_data not in direct_groups:
        await callback.answer("❌ Неверный тип услуги")
        return

    service_name = direct_groups[service_data]
    await state.update_data(service_type=service_name)

    await callback.message.edit_text(
        f"📝 Услуга: <b>{service_name}</b>\n\n"
        "Теперь опишите проблему или услугу подробно:\n\n"
        "<i>Примеры:</i>\n"
        "• 'Нужна комплексная мойка кузова и салона'\n"
        "• 'Стук в подвеске на кочках, нужна диагностика'\n"
        "• 'Требуется замена масла и фильтров'\n"
        "• 'Кузовной ремонт после небольшого ДТП'",
        parse_mode="HTML",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(RequestForm.description)
    await callback.answer()


@router.callback_query(RequestForm.service_subtype)
async def process_service_subtype(callback: CallbackQuery, state: FSMContext):
    service_data = callback.data

    subtype_map = {
        "service_tire_stationary": "Шиномонтаж (на СТО)",
        "service_tire_mobile": "Шиномонтаж / Выездной шиномонтаж",

        "service_electric_stationary": "Автоэлектрик (на СТО)",
        "service_electric_mobile": "Автоэлектрик / Выездной мастер",

        "service_agg_turbo": "Ремонт агрегатов / Турбина",
        "service_agg_starter": "Ремонт агрегатов / Стартер",
        "service_agg_generator": "Ремонт агрегатов / Генератор",
        "service_agg_steering": "Ремонт агрегатов / Рулевая рейка",
    }

    if service_data not in subtype_map:
        await callback.answer("❌ Неверный подтип услуги")
        return

    service_name = subtype_map[service_data]
    await state.update_data(service_type=service_name)

    await callback.message.edit_text(
        f"📝 Услуга: <b>{service_name}</b>\n\n"
        "Теперь опишите проблему или услугу подробно:\n\n"
        "<i>Примеры:</i>\n"
        "• 'Пробило колесо, нужен выездной шиномонтаж'\n"
        "• 'Авто не заводится, подозрение на стартер'\n"
        "• 'Снижение тяги, подозрение на турбину'\n"
        "• 'Люфт руля, подозрение на рулевую рейку'",
        parse_mode="HTML",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(RequestForm.description)
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
    can_drive = callback.data == "can_drive_yes"
    await state.update_data(can_drive=can_drive)

    text = (
        "📍 Теперь укажем текущее местоположение автомобиля.\n\n"
        "Вы можете:\n"
        "• отправить геолокацию кнопкой ниже;\n"
        "• или написать адрес/ориентиры вручную.\n\n"
        "Если не хотите указывать местоположение, нажмите «⏭️ Пропустить локацию»."
    )

    await callback.message.edit_text(text)
    await callback.message.answer(
        "Отправьте геолокацию или введите адрес:",
        reply_markup=get_location_reply_kb(),
    )
    await state.set_state(RequestForm.location)
    await callback.answer()


@router.message(RequestForm.preferred_date)
async def process_preferred_date(message: Message, state: FSMContext):
    preferred = (message.text or "").strip()
    if len(preferred) < 3:
        await message.answer(
            "❌ Слишком короткий ответ. Пожалуйста, укажите, когда вам удобно:",
            reply_markup=get_car_cancel_kb(),
        )
        return

    await state.update_data(preferred_date=preferred)
    data = await state.get_data()

    service_type = data.get("service_type", "Не указано")
    description = data.get("description", "Не указано")
    photo_id = data.get("photo")
    photos_text = "есть" if photo_id else "нет"

    await message.answer(
        "📄 Заявка на услугу\n\n"
        f"🚗 Авто: будет показано менеджеру по данным из гаража\n"
        f"🔧 Услуга: {service_type}\n"
        f"📝 Описание: {description}\n"
        f"📷 Фото: {photos_text}\n"
        f"⏰ Когда удобно: {preferred}\n\n"
        "Подтвердите создание заявки:",
        reply_markup=get_request_confirm_kb(),
    )
    await state.set_state(RequestForm.confirm)


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

    async with AsyncSessionLocal() as session:
        try:
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

            new_request = Request(
                user_id=user.id,
                car_id=car.id,
                service_type=service_type,
                description=description,
                photo_file_id=photo_id,
                status="new",
                preferred_date=preferred_date,
                can_drive=can_drive,
                location_lat=loc_lat,
                location_lon=loc_lon,
                location_description=loc_desc,
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
    await callback.message.edit_text(
        "✏️ Редактирование заявки пока не реализовано.\n\n"
        "Создайте заявку заново.",
        reply_markup=get_main_kb()
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "my_requests")
async def my_requests(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 Ваши заявки.\n\n"
        "Выберите, что показать:",
        reply_markup=get_history_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "history_active")
async def history_active(callback: CallbackQuery, state: FSMContext):
    await show_requests_list(callback, filter_status="active")


@router.callback_query(F.data == "history_archived")
async def history_archived(callback: CallbackQuery, state: FSMContext):
    await show_requests_list(callback, filter_status="archived")


async def show_requests_list(callback: CallbackQuery, filter_status: str = None):
    async with AsyncSessionLocal() as session:
        try:
            user_id = callback.from_user.id
            
            user_result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user_result.scalar_one_or_none()
            
            if not user:
                await callback.message.edit_text("❌ Пользователь не найден. Начните с /start")
                return
            
            query = select(Request).where(Request.user_id == user.id)
            
            if filter_status == "active":
                query = query.where(Request.status.in_(["new", "in_progress", "scheduled", "in_work", "to_pay"]))
            elif filter_status == "archived":
                query = query.where(Request.status.in_(["paid", "archived", "rejected"]))
            
            result = await session.execute(query)
            requests = result.scalars().all()
            
            if not requests:
                if filter_status == "active":
                    text = "📋 У вас нет активных заявок."
                elif filter_status == "archived":
                    text = "📁 У вас нет архивных заявок."
                else:
                    text = "📋 У вас пока нет заявок."
                
                await callback.message.edit_text(
                    text,
                    reply_markup=get_history_kb()
                )
                return
            
            lines = []
            for req in requests:
                status_emoji = {
                    "new": "🆕",
                    "in_progress": "🔄",
                    "scheduled": "📅",
                    "in_work": "🔧",
                    "to_pay": "💰",
                    "paid": "✅",
                    "archived": "📁",
                    "rejected": "❌"
                }.get(req.status, "❔")
                
                lines.append(
                    f"{status_emoji} Заявка #{req.id}: {req.service_type}\n"
                    f"   Статус: {req.status}\n"
                    f"   Описание: {req.description[:50]}{'...' if len(req.description) > 50 else ''}"
                )
            
            await callback.message.edit_text(
                "📋 Ваши заявки:\n\n" + "\n\n".join(lines),
                reply_markup=get_history_kb()
            )
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке списка заявок: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при загрузке заявок. Попробуйте позже.",
                reply_markup=get_main_kb()
            )


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
