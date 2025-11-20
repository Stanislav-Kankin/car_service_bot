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
from app.database.models import User, Car, Request
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import (
    get_main_kb, get_registration_kb,
    get_phone_reply_kb, get_garage_kb,
    get_car_management_kb, get_car_cancel_kb,
    get_service_types_kb, get_tire_subtypes_kb,
    get_electric_subtypes_kb, get_aggregates_subtypes_kb,
    get_photo_skip_kb, get_request_confirm_kb,
    get_delete_confirm_kb, get_history_kb, get_edit_cancel_kb
)
from app.config import config


class CarForm(StatesGroup):
    brand = State()
    model = State()
    year = State()
    license_plate = State()
    # состояния для редактирования
    edit_brand = State()
    edit_model = State()
    edit_year = State()
    edit_license_plate = State()


class RequestForm(StatesGroup):
    # Основной тип услуги (группа работ: автомойка, шиномонтаж и т.п.)
    service_type = State()
    # Подтип услуги (выездной/стационарный, конкретный агрегат и т.п.)
    service_subtype = State()
    description = State()
    photo = State()
    preferred_date = State()
    confirm = State()


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
            
            if user:
                logging.info(f"✅ Пользователь {message.from_user.id} уже зарегистрирован")
                await message.answer(
                    "👋 С возвращением в CAR SERVICE BOT!\n\n"
                    "Выберите действие:",
                    reply_markup=get_main_kb()
                )
            else:
                logging.info(f"🆕 Новый пользователь {message.from_user.id}")
                await message.answer(
                    "👋 Добро пожаловать в CAR SERVICE BOT!\n\n"
                    "Я помогу вам с обслуживанием вашего автомобиля: "
                    "запись на сервис, шиномонтаж, эвакуатор и многое другое.\n\n"
                    "Для начала работы нужно пройти простую регистрацию:",
                    reply_markup=get_registration_kb()
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
    await callback.message.edit_text(
        "📝 Отлично! Давайте начнем регистрацию.\n\n"
        "Введите ваше полное имя (как в профиле или как удобно к вам обращаться):",
        reply_markup=None
    )
    await state.set_state("waiting_for_name")
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


# Обработчик имени при регистрации
@router.message(StateFilter("waiting_for_name"))
async def process_name_registration(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer(
            "❌ Имя слишком короткое. Пожалуйста, введите полное имя:",
            reply_markup=None
        )
        return

    await state.update_data(user_name=name)

    await message.answer(
        f"✅ Приятно познакомиться, {name}!\n\n"
        "Теперь нажмите на кнопку ниже чтобы отправить номер телефона:",
        reply_markup=get_phone_reply_kb()
    )
    await state.set_state("waiting_for_phone")


# Обработчик ВСЕХ сообщений в состоянии waiting_for_phone (для отладки)
@router.message(StateFilter("waiting_for_phone"))
async def handle_all_in_phone_state(message: Message, state: FSMContext):
    # Если пользователь зачем-то отправил текст вместо контакта
    if not message.contact:
        await message.answer(
            "📱 Пожалуйста, используйте кнопку для отправки номера телефона:",
            reply_markup=get_phone_reply_kb()
        )
        return


# Обработчик контакта при регистрации
@router.message(StateFilter("waiting_for_phone"))
async def process_phone_registration(message: Message, state: FSMContext):
    if not message.contact:
        await message.answer(
            "📱 Пожалуйста, используйте кнопку для отправки номера телефона:",
            reply_markup=get_phone_reply_kb()
        )
        return

    phone_number = message.contact.phone_number
    data = await state.get_data()
    name = data.get("user_name") or message.from_user.full_name

    async with AsyncSessionLocal() as session:
        try:
            # Проверяем, нет ли уже пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Обновляем данные
                user.full_name = name
                user.phone_number = phone_number
                await session.commit()
                logging.info(f"🔄 Обновлена регистрация пользователя {message.from_user.id}")
            else:
                # Создаем нового пользователя
                new_user = User(
                    telegram_id=message.from_user.id,
                    full_name=name,
                    phone_number=phone_number
                )
                session.add(new_user)
                await session.commit()
                logging.info(f"✅ Зарегистрирован новый пользователь {message.from_user.id}")
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка при сохранении регистрации: {e}")
            await message.answer(
                "❌ Произошла ошибка при сохранении данных. Попробуйте позже."
            )
            return

    await state.clear()

    await message.answer(
        "✅ Регистрация завершена!\n\n"
        "Теперь вы можете управлять своими автомобилями и создавать заявки на услуги.",
        reply_markup=ReplyKeyboardRemove()
    )

    await message.answer(
        "🏠 Главное меню:",
        reply_markup=get_main_kb()
    )


# Обработчик нажатия на "Мой гараж"
@router.callback_query(F.data == "my_garage")
async def my_garage(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        try:
            # Получаем пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                await callback.message.edit_text(
                    "❌ Вы еще не зарегистрированы. Нажмите /start для регистрации.",
                    reply_markup=None
                )
                await callback.answer()
                return
            
            # Получаем автомобили
            result = await session.execute(
                select(Car).where(Car.user_id == user.id)
            )
            cars = result.scalars().all()
            
            if not cars:
                await callback.message.edit_text(
                    "🚗 В вашем гараже пока нет автомобилей.\n\n"
                    "Нажмите кнопку ниже, чтобы добавить первый автомобиль:",
                    reply_markup=get_garage_kb()
                )
            else:
                builder = InlineKeyboardBuilder()
                for car in cars:
                    builder.row(
                        InlineKeyboardButton(
                            text=f"🚗 {car.brand} {car.model}",
                            callback_data=f"select_car:{car.id}"
                        )
                    )
                builder.row(
                    InlineKeyboardButton(
                        text="➕ Добавить автомобиль", callback_data="add_car")
                )
                builder.row(
                    InlineKeyboardButton(
                        text="⬅️ В меню", callback_data="back_to_main")
                )
                
                await callback.message.edit_text(
                    "🚗 Ваш гараж:\n\nВыберите автомобиль для управления или добавьте новый:",
                    reply_markup=builder.as_markup()
                )
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке гаража: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при загрузке гаража. Попробуйте позже.",
                reply_markup=get_main_kb()
            )
    await callback.answer()


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
                license_plate=license_plate
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


# Обработчики выбора поля для редактирования
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


# Обработчик отмены редактирования
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


# Обработчики ввода новых значений при редактировании
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


# Обработчик удаления авто
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


# Подтверждение удаления авто
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


# Отмена удаления авто
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


# Обработчик "Создать заявку" (из главного меню)
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



# Отмена создания заявки
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
    """
    Обработка выбора основного вида работ (группа услуг).
    На этом шаге либо сразу фиксируем тип услуги, либо
    уходим на выбор подтипа (выездной/стационарный, агрегаты).
    """
    service_data = callback.data

    # Возврат к списку групп услуг из подтипов
    if service_data == "service_back_to_groups":
        await callback.message.edit_text(
            "🛠️ Выберите вид работ:",
            reply_markup=get_service_types_kb()
        )
        await state.set_state(RequestForm.service_type)
        await callback.answer()
        return

    # Группы, которые НЕ требуют дополнительного выбора подтипа
    direct_groups = {
        "service_group_wash": "Автомойки",
        "service_group_mechanic": "Слесарные работы",
        "service_group_paint": "Малярные работы",
        "service_group_maint": "Техобслуживание",
    }

    # Группы, которые ведут на выбор подтипа
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
    """
    Обработка выбора подтипа услуги (выездной/стационарный, конкретный агрегат и т.п.).
    В БД сохраняем уже человекочитаемое название в поле service_type.
    """
    service_data = callback.data

    subtype_map = {
        # Шиномонтаж
        "service_tire_stationary": "Шиномонтаж (на СТО)",
        "service_tire_mobile": "Шиномонтаж / Выездной шиномонтаж",

        # Автоэлектрик
        "service_electric_stationary": "Автоэлектрик (на СТО)",
        "service_electric_mobile": "Автоэлектрик / Выездной мастер",

        # Ремонт агрегатов
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


# Обработчик ввода описания
@router.message(RequestForm.description)
async def process_description(message: Message, state: FSMContext):
    description = message.text.strip()
    
    if len(description) < 10:
        await message.answer(
            "❌ Описание слишком короткое. Пожалуйста, опишите проблему подробнее "
            "(минимум 10 символов):",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    await state.update_data(description=description)
    
    await message.answer(
        "📷 Прикрепите фото проблемы (если есть) или нажмите 'Пропустить':",
        reply_markup=get_photo_skip_kb()
    )
    await state.set_state(RequestForm.photo)


# Обработчик фото
@router.callback_query(RequestForm.photo, F.data == "attach_photo")
async def attach_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📷 Отправьте одно или несколько фото.\n\n"
        "Когда закончите, нажмите 'Пропустить'.",
        reply_markup=get_photo_skip_kb()
    )
    await callback.answer()


# Обработка входящих фото
@router.message(RequestForm.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    
    file_id = message.photo[-1].file_id
    photos.append(file_id)
    
    await state.update_data(photos=photos)
    
    await message.answer(
        f"✅ Фото добавлено ({len(photos)} шт.).\n"
        "Можете отправить ещё или нажмите 'Пропустить', чтобы продолжить.",
        reply_markup=get_photo_skip_kb()
    )


# Пропуск прикрепления фото
@router.callback_query(RequestForm.photo, F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext):
    """
    После этапа с фото спрашиваем, когда удобно клиенту (дата/время).
    """
    await callback.message.edit_text(
        "⏰ Когда вам удобно выполнить работу?\n\n"
        "Напишите удобное время в свободной форме, например:\n"
        "• «Сегодня после 18:00»\n"
        "• «Завтра утром»\n"
        "• «В выходные, любой день»\n"
        "• или конкретную дату и время.",
        reply_markup=get_car_cancel_kb(),
    )
    await state.set_state(RequestForm.preferred_date)
    await callback.answer()


@router.message(RequestForm.preferred_date)
async def process_preferred_date(message: Message, state: FSMContext):
    """
    Сохраняем пожелания по времени и показываем итоговую сводку заявки.
    """
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
    photos = data.get("photos", [])
    photos_text = f"{len(photos)} шт." if photos else "нет"

    await message.answer(
        "📄 Заявка на услугу\n\n"
        f"🚗 Авто: будет показано менеджеру по ID\n"
        f"🔧 Услуга: {service_type}\n"
        f"📝 Описание: {description}\n"
        f"📷 Фото: {photos_text}\n"
        f"⏰ Когда удобно: {preferred}\n\n"
        "Подтвердите создание заявки:",
        reply_markup=get_request_confirm_kb(),
    )
    await state.set_state(RequestForm.confirm)


# Подтверждение заявки
@router.callback_query(RequestForm.confirm, F.data == "confirm_request")
async def confirm_request(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    car_id = data.get("car_id")
    service_type = data.get("service_type")
    description = data.get("description")
    photos = data.get("photos", [])
    preferred_date = data.get("preferred_date")
    
    async with AsyncSessionLocal() as session:
        try:
            # Получаем пользователя и автомобиль
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
            
            # Создаем заявку
            new_request = Request(
                user_id=user.id,
                car_id=car.id,
                service_type=service_type,
                description=description,
                photo_file_id=",".join(photos) if photos else None,
                status="new"
            )

            session.add(new_request)
            await session.commit()
            
            # Уведомляем менеджера
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


# Изменение заявки перед подтверждением (пока просто отмена и пересоздание)
@router.callback_query(RequestForm.confirm, F.data == "edit_request")
async def edit_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ Редактирование заявки пока не реализовано.\n\n"
        "Создайте заявку заново.",
        reply_markup=get_main_kb()
    )
    await state.clear()
    await callback.answer()


# Просмотр заявок пользователя
@router.callback_query(F.data == "my_requests")
async def my_requests(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 Ваши заявки.\n\n"
        "Выберите, что показать:",
        reply_markup=get_history_kb()
    )
    await callback.answer()


# История активных заявок
@router.callback_query(F.data == "history_active")
async def history_active(callback: CallbackQuery, state: FSMContext):
    await show_requests_list(callback, filter_status="active")


# История архивных заявок
@router.callback_query(F.data == "history_archived")
async def history_archived(callback: CallbackQuery, state: FSMContext):
    await show_requests_list(callback, filter_status="archived")


# Функция показа списка заявок
async def show_requests_list(callback: CallbackQuery, filter_status: str = None):
    async with AsyncSessionLocal() as session:
        try:
            user_id = callback.from_user.id
            
            # Получаем пользователя
            user_result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user_result.scalar_one_or_none()
            
            if not user:
                await callback.message.edit_text("❌ Пользователь не найден. Начните с /start")
                return
            
            # Получаем заявки
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
            
            # Формируем список
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
            # Ищем пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("❌ Пользователь не найден. Нажмите /start", show_alert=True)
                return

            # Ищем заявку этого пользователя
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

            # Обновляем статус
            request.status = "accepted"
            await session.commit()

        # Меняем текст у клиента
        await callback.message.edit_text(
            f"✅ Вы подтвердили условия по заявке #{request_id}.\n"
            f"Менеджер свяжется с вами для записи и выполнения работ."
        )

        # Уведомляем менеджерскую группу
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

        # Обновляем клавиатуру в чате заявки (теперь появятся кнопки статусов)
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
            # Ищем пользователя
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await callback.answer("❌ Пользователь не найден. Нажмите /start", show_alert=True)
                return

            # Ищем заявку этого пользователя
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

            # Помечаем как отклонённую
            request.status = "rejected"
            await session.commit()

        await callback.message.edit_text(
            f"❌ Вы отклонили условия по заявке #{request_id}.\n"
            f"Если хотите, вы можете создать новую заявку."
        )

        # Уведомляем менеджеров
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

        # Чистим кнопки в чате заявки
        try:
            from app.handlers.chat_handlers import update_chat_keyboard
            await update_chat_keyboard(callback.bot, request_id)
        except Exception as e:
            logging.error(f"❌ Не удалось обновить клавиатуру в чате заявки: {e}")

        await callback.answer()

    except Exception as e:
        logging.error(f"❌ Ошибка при отказе от условий клиентом: {e}")
        await callback.answer("❌ Ошибка, попробуйте позже", show_alert=True)
