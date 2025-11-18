from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.database.models import User
from app.database.db import SessionLocal
from app.keyboards.main_kb import (
    get_main_kb, get_registration_kb,
    get_phone_reply_kb
    )

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
