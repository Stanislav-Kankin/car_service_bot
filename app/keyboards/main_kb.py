from aiogram.types import (
    InlineKeyboardButton,
    KeyboardButton
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


# Клавиатура для менеджера (под каждой заявкой)
def get_manager_request_kb(request_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=f"manager_accept:{request_id}"),
        InlineKeyboardButton(text="✏️ Уточнить", callback_data=f"manager_clarify:{request_id}")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"manager_reject:{request_id}"),
        InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request_id}")
    )
    return builder.as_markup()


# Клавиатура для отмены действия менеджером
def get_manager_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data="manager_cancel")
    )
    return builder.as_markup()


# Клавиатура для истории заявок
def get_history_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🆕 Новые", callback_data="filter_new"),
        InlineKeyboardButton(text="✅ Принятые", callback_data="filter_accepted"),
        InlineKeyboardButton(text="⏳ В работе", callback_data="filter_in_progress")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Все заявки", callback_data="filter_all"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    return builder.as_markup()


# Клавиатура для детального просмотра заявки
def get_request_detail_kb(request_id: int, back_to: str = "history"):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=back_to),
        InlineKeyboardButton(text="📋 К списку", callback_data="request_history")
    )
    return builder.as_markup()


# Клавиатура для навигации по заявкам
def get_requests_navigation_kb(requests_ids: list, current_index: int, back_to: str = "history"):
    builder = InlineKeyboardBuilder()
    
    if current_index > 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"view_request:{requests_ids[current_index - 1]}")
        )
    
    builder.row(
        InlineKeyboardButton(text="📋 К списку", callback_data="request_history")
    )
    
    if current_index < len(requests_ids) - 1:
        builder.row(
            InlineKeyboardButton(text="Следующая ➡️", callback_data=f"view_request:{requests_ids[current_index + 1]}")
        )
    
    return builder.as_markup()


# Клавиатура для отмены редактирования авто
def get_edit_cancel_kb(car_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отменить редактирование", callback_data=f"cancel_edit:{car_id}")
    )
    return builder.as_markup()

# Клавиатура панели менеджера
def get_manager_panel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все заявки", callback_data="manager_all_requests"),
        InlineKeyboardButton(text="🆕 Новые", callback_data="manager_new_requests")
    )
    builder.row(
        InlineKeyboardButton(text="⏳ В работе", callback_data="manager_in_progress"),
        InlineKeyboardButton(text="✅ Завершенные", callback_data="manager_completed")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="manager_stats"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data="manager_search")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_main_menu")
    )
    return builder.as_markup()

# Клавиатура для заявки в панели менеджера
def get_manager_request_detail_kb(request_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏳ В работу", callback_data=f"manager_set_in_progress:{request_id}"),
        InlineKeyboardButton(text="✅ Завершить", callback_data=f"manager_set_completed:{request_id}")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Комментарий", callback_data=f"manager_add_comment:{request_id}"),
        InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_all_requests")
    )
    return builder.as_markup()

# Клавиатура навигации по заявкам для менеджера
def get_manager_requests_navigation_kb(requests_ids: list, current_index: int):
    builder = InlineKeyboardBuilder()
    
    if current_index > 0:
        builder.row(
            InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"manager_view_request:{requests_ids[current_index - 1]}")
        )
    
    builder.row(
        InlineKeyboardButton(text="📋 К списку", callback_data="manager_all_requests")
    )
    
    if current_index < len(requests_ids) - 1:
        builder.row(
            InlineKeyboardButton(text="Следующая ➡️", callback_data=f"manager_view_request:{requests_ids[current_index + 1]}")
        )
    
    return builder.as_markup()
