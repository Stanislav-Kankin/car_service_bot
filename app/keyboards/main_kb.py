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


# Клавиатура для раздела "Мой гараж"
def get_garage_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить авто", callback_data="add_car"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    return builder.as_markup()


# Клавиатура для управления конкретным авто
def get_car_management_kb(car_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Создать заявку", callback_data=f"create_request:{car_id}"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_car:{car_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_car:{car_id}"),
        InlineKeyboardButton(text="⬅️ Назад в гараж", callback_data="my_garage")
    )
    return builder.as_markup()


# Клавиатура для подтверждения удаления
def get_delete_confirm_kb(car_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete:{car_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_delete:{car_id}")
    )
    return builder.as_markup()


# Клавиатура для отмены в процессе добавления авто
def get_car_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_car_add")
    )
    return builder.as_markup()


# Клавиатура для выбора типа услуги
def get_service_types_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⛽ Топливо", callback_data="service_fuel"),
        InlineKeyboardButton(text="🧼 Автомойка", callback_data="service_wash")
    )
    builder.row(
        InlineKeyboardButton(text="🛞 Помощь в дороге", callback_data="service_roadside"),
        InlineKeyboardButton(text="🔧 СТО", callback_data="service_sto")
    )
    builder.row(
        InlineKeyboardButton(text="🛞 Запчасти", callback_data="service_parts"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request")
    )
    return builder.as_markup()


# Клавиатура для пропуска фото
def get_photo_skip_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📷 Прикрепить фото", callback_data="attach_photo"),
        InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_photo")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_request")
    )
    return builder.as_markup()


# Клавиатура для подтверждения заявки
def get_request_confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить заявку", callback_data="confirm_request"),
        InlineKeyboardButton(text="✏️ Исправить", callback_data="edit_request")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request")
    )
    return builder.as_markup()