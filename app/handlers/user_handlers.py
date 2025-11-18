from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from datetime import datetime
import logging

from app.database.models import User, Car
from app.database.db import SessionLocal
from app.keyboards.main_kb import (
    get_main_kb, get_registration_kb,
    get_phone_reply_kb, get_garage_kb,
    get_car_management_kb, get_car_cancel_kb
)


class CarForm(StatesGroup):
    brand = State()
    model = State()
    year = State()
    license_plate = State()


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Очищаем состояние
    await state.clear()

    # Создаем сессию БД
    session = SessionLocal()

    try:
        # Проверяем, есть ли пользователь в БД (синхронно!)
        user_id = message.from_user.id
        result = session.execute(select(User).where(
            User.telegram_id == user_id))
        user = result.scalar_one_or_none()

        if user:
            # Пользователь уже зарегистрирован - показываем главное меню
            await message.answer(
                f"🚗 Добро пожаловать в автосервис, {user.full_name}!\n"
                "Выберите действие:",
                reply_markup=get_main_kb()
            )
        else:
            # Новый пользователь - предлагаем регистрацию
            await message.answer(
                "🚗 Добро пожаловать в сервис автомобильных услуг!\n\n"
                "Для использования бота необходимо пройти быструю регистрацию.\n"
                "Это займет меньше минуты!",
                reply_markup=get_registration_kb()
            )
    except Exception as e:
        await message.answer(
            "❌ Ошибка при загрузке данных. Попробуйте снова: /start"
            )
    finally:
        session.close()


# Обработчик нажатия на кнопку "Зарегистрироваться"
@router.callback_query(F.data == "start_registration")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 Отлично! Давайте начнем регистрацию.\n\n"
        "Введите ваше полное имя (как в паспорте):"
    )
    await state.set_state("waiting_for_name")
    await callback.answer()


# Обработчик ввода имени
@router.message(F.text, StateFilter("waiting_for_name"))
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()

    # Простая валидация имени
    if len(name) < 2:
        await message.answer(
            "❌ Имя слишком короткое. Введите ваше настоящее имя:"
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
    print(f"🔧 DEBUG: Получено сообщение в состоянии waiting_for_phone")
    print(f"🔧 DEBUG: Тип контента: {message.content_type}")
    print(f"🔧 DEBUG: Текст: {message.text}")
    print(f"🔧 DEBUG: Контакт: {message.contact}")

    # Если это контакт
    if message.contact:
        await process_contact(message, state)
    # Если это текст "❌ Отменить"
    elif message.text == "❌ Отменить":
        await cancel_phone_reply(message, state)
    # Любое другое сообщение
    else:
        await wrong_input_in_phone_state(message)


# Обработчик получения контакта
async def process_contact(message: Message, state: FSMContext):
    print("🔧 DEBUG: Обработка контакта начата")

    contact = message.contact
    user_data = await state.get_data()

    print(f"🔧 DEBUG: Данные пользователя: {user_data}")
    print(f"🔧 DEBUG: Контакт: {contact.phone_number}")

    # Создаем сессию БД
    session = SessionLocal()

    try:
        # Сохраняем пользователя в БД
        new_user = User(
            telegram_id=message.from_user.id,
            full_name=user_data['user_name'],
            phone_number=contact.phone_number
        )

        session.add(new_user)
        session.commit()

        print("🔧 DEBUG: Пользователь сохранен в БД")

        await message.answer(
            f"✅ Регистрация завершена!\n\n"
            f"👤 <b>Ваши данные:</b>\n"
            f"• Имя: {user_data['user_name']}\n"
            f"• Телефон: {contact.phone_number}\n\n"
            "Теперь вы можете пользоваться всеми возможностями бота!",
            parse_mode="HTML",
            reply_markup=get_main_kb()
        )
        await state.clear()

    except Exception as e:
        session.rollback()
        print(f"❌ Ошибка при сохранении пользователя: {e}")
        await message.answer(
            "❌ Ошибка при сохранении данных. Попробуйте снова: /start",
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        session.close()


# Обработчик кнопки "Отменить" в Reply-клавиатуре
async def cancel_phone_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Регистрация отменена.\n\n"
        "Если передумаете - просто отправьте /start",
        reply_markup=ReplyKeyboardRemove()
    )


# Обработчик отмены регистрации (инлайн)
@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Регистрация отменена.\n\n"
        "Если передумаете - просто отправьте /start"
    )
    await callback.answer()


# Общий обработчик отмены (инлайн)
@router.callback_query(F.data == "cancel_action")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.\n\n"
        "Возврат в главное меню: /start"
    )
    await callback.answer()


# Обработчик для неправильного ввода
async def wrong_input_in_phone_state(message: Message):
    await message.answer(
        "❌ Пожалуйста, нажмите на кнопку ниже чтобы отправить номер телефона:",
        reply_markup=get_phone_reply_kb()
    )

# Обработчик кнопки "🚗 Мой гараж"
@router.callback_query(F.data == "my_garage")
async def show_garage(callback: CallbackQuery):
    session = SessionLocal()
    
    try:
        # Получаем пользователя и его автомобили
        user_id = callback.from_user.id
        result = session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            await callback.message.edit_text(
                "❌ Пользователь не найден. Начните с /start"
            )
            return
        
        # Получаем автомобили пользователя
        cars_result = session.execute(select(Car).where(Car.user_id == user.id))
        cars = cars_result.scalars().all()
        
        if not cars:
            # Нет автомобилей - предлагаем добавить
            await callback.message.edit_text(
                "🚗 Ваш гараж пуст\n\n"
                "Добавьте свой первый автомобиль чтобы начать пользоваться услугами",
                reply_markup=get_garage_kb()
            )
        else:
            # Показываем список автомобилей
            cars_text = "🚗 Ваш гараж:\n\n"
            for i, car in enumerate(cars, 1):
                cars_text += (
                    f"{i}. {car.brand} {car.model}\n"
                    f"   🗓️ Год: {car.year or 'Не указан'}\n"
                    f"   🚙 Номер: {car.license_plate or 'Не указан'}\n\n"
                )
            
            # Создаем клавиатуру с кнопками для каждого авто
            builder = InlineKeyboardBuilder()
            for car in cars:
                builder.row(
                    InlineKeyboardButton(
                        text=f"🚗 {car.brand} {car.model}",
                        callback_data=f"select_car:{car.id}"
                    )
                )
            builder.row(
                InlineKeyboardButton(text="➕ Добавить авто", callback_data="add_car"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
            )
            
            await callback.message.edit_text(
                cars_text,
                reply_markup=builder.as_markup()
            )
            
    except Exception as e:
        logging.error(f"Ошибка при показе гаража: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при загрузке гаража. Попробуйте снова."
        )
    finally:
        session.close()
    await callback.answer()


# Обработчик кнопки "➕ Добавить авто"
@router.callback_query(F.data == "add_car")
async def start_add_car(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🚗 Добавление нового автомобиля\n\n"
        "Введите марку автомобиля (например: Toyota):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.brand)
    await callback.answer()


# Обработчик ввода марки авто
@router.message(CarForm.brand)
async def process_car_brand(message: Message, state: FSMContext):
    brand = message.text.strip()
    if len(brand) < 2:
        await message.answer(
            "❌ Марка слишком короткая. Введите корректную марку:",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    await state.update_data(brand=brand)
    await message.answer(
        "Теперь введите модель автомобиля (например: Camry):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.model)


# Обработчик ввода модели авто
@router.message(CarForm.model)
async def process_car_model(message: Message, state: FSMContext):
    model = message.text.strip()
    if len(model) < 1:
        await message.answer(
            "❌ Модель не может быть пустой. Введите корректную модель:",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    await state.update_data(model=model)
    await message.answer(
        "Введите год выпуска автомобиля (например: 2020):",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.year)


# Обработчик ввода года выпуска
@router.message(CarForm.year)
async def process_car_year(message: Message, state: FSMContext):
    year_text = message.text.strip()
    
    # Валидация года
    if not year_text.isdigit():
        await message.answer(
            "❌ Год должен быть числом. Введите корректный год:",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    year = int(year_text)
    current_year = datetime.now().year
    if year < 1900 or year > current_year + 1:
        await message.answer(
            f"❌ Год должен быть между 1900 и {current_year + 1}. Введите корректный год:",
            reply_markup=get_car_cancel_kb()
        )
        return
    
    await state.update_data(year=year)
    await message.answer(
        "Введите госномер автомобиля (например: A123BC777):\n"
        "Или отправьте /skip чтобы пропустить",
        reply_markup=get_car_cancel_kb()
    )
    await state.set_state(CarForm.license_plate)


# Обработчик ввода госномера или пропуска
@router.message(CarForm.license_plate)
async def process_car_license_plate(message: Message, state: FSMContext):
    license_plate = None
    
    if message.text != "/skip":
        license_plate = message.text.strip().upper()
        # Простая валидация госномера (можно улучшить)
        if len(license_plate) < 4:
            await message.answer(
                "❌ Госномер слишком короткий. Введите корректный номер или /skip:",
                reply_markup=get_car_cancel_kb()
            )
            return
    
    user_data = await state.get_data()
    session = SessionLocal()
    
    try:
        # Получаем ID пользователя
        user_result = session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            await message.answer(
                "❌ Пользователь не найден. Начните с /start",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.clear()
            return
        
        # Создаем запись автомобиля
        new_car = Car(
            user_id=user.id,
            brand=user_data['brand'],
            model=user_data['model'],
            year=user_data['year'],
            license_plate=license_plate
        )
        
        session.add(new_car)
        session.commit()
        
        # Формируем сообщение об успехе
        success_text = (
            "✅ Автомобиль успешно добавлен!\n\n"
            f"🚗 <b>Данные автомобиля:</b>\n"
            f"• Марка: {user_data['brand']}\n"
            f"• Модель: {user_data['model']}\n"
            f"• Год: {user_data['year']}\n"
        )
        
        if license_plate:
            success_text += f"• Госномер: {license_plate}\n"
        
        success_text += "\nТеперь вы можете создавать заявки для этого автомобиля!"
        
        await message.answer(
            success_text,
            parse_mode="HTML",
            reply_markup=get_main_kb()
        )
        await state.clear()
        
    except Exception as e:
        session.rollback()
        logging.error(f"Ошибка при добавлении автомобиля: {e}")
        await message.answer(
            "❌ Ошибка при сохранении автомобиля. Попробуйте снова.",
            reply_markup=get_main_kb()
        )
    finally:
        session.close()
        await state.clear()


# Обработчик выбора конкретного автомобиля
@router.callback_query(F.data.startswith("select_car:"))
async def select_car(callback: CallbackQuery):
    car_id = int(callback.data.split(":")[1])
    session = SessionLocal()
    
    try:
        # Получаем данные автомобиля
        car_result = session.execute(select(Car).where(Car.id == car_id))
        car = car_result.scalar_one_or_none()
        
        if not car:
            await callback.message.edit_text(
                "❌ Автомобиль не найден",
                reply_markup=get_garage_kb()
            )
            return
        
        car_info = (
            f"🚗 <b>Выбран автомобиль:</b>\n\n"
            f"• Марка: {car.brand}\n"
            f"• Модель: {car.model}\n"
            f"• Год: {car.year or 'Не указан'}\n"
            f"• Госномер: {car.license_plate or 'Не указан'}\n\n"
            f"Выберите действие:"
        )
        
        await callback.message.edit_text(
            car_info,
            parse_mode="HTML",
            reply_markup=get_car_management_kb(car.id)
        )
        
    except Exception as e:
        logging.error(f"Ошибка при выборе автомобиля: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при загрузке данных автомобиля",
            reply_markup=get_garage_kb()
        )
    finally:
        session.close()
    await callback.answer()


# Обработчик отмены добавления авто
@router.callback_query(F.data == "cancel_car_add")
async def cancel_car_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Добавление автомобиля отменено",
        reply_markup=get_garage_kb()
    )
    await callback.answer()


# Обработчик кнопки "⬅️ Назад" в главное меню
@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    session = SessionLocal()
    
    try:
        user_result = session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        
        if user:
            await callback.message.edit_text(
                f"🚗 Добро пожаловать в автосервис, {user.full_name}!\n"
                "Выберите действие:",
                reply_markup=get_main_kb()
            )
        else:
            await callback.message.edit_text(
                "❌ Пользователь не найден. Начните с /start"
            )
    except Exception as e:
        await callback.message.edit_text(
            "❌ Ошибка. Попробуйте снова: /start"
        )
    finally:
        session.close()
    await callback.answer()


# Обработчик кнопки "⬅️ Назад в гараж"
@router.callback_query(F.data == "my_garage")
async def back_to_garage(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_garage(callback)

