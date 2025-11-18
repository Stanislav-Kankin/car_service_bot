from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
    )
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# Главное меню (инлайн)
def get_main_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🚗 Мой гараж", callback_data="my_garage"),
        InlineKeyboardButton(
            text="📝 Создать заявку", callback_data="create_request")
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 История заявок", callback_data="request_history")
    )
    return builder.as_markup()


# Клавиатура для регистрации
def get_registration_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Зарегистрироваться", callback_data="start_registration")
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить", callback_data="cancel_registration")
    )
    return builder.as_markup()


# Красивая Reply-клавиатура для номера телефона
def get_phone_reply_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(
            text="📱 Отправить мой номер", request_contact=True)
    )
    builder.row(
        KeyboardButton(
            text="❌ Отменить")
    )
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# Клавиатура для отмены действий (инлайн)
def get_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_action")
    )
    return builder.as_markup()
