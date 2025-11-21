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
            text="📋 Мои заявки", callback_data="my_requests"),
        InlineKeyboardButton(
            text="ℹ️ Помощь", callback_data="help")
    )
    # ✅ Новая кнопка бонусов
    builder.row(
        InlineKeyboardButton(
            text="🎁 Мои бонусы", callback_data="my_points")
    )
    return builder.as_markup()


# Клавиатура регистрации
def get_registration_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📝 Зарегистрироваться", callback_data="start_registration"))
    builder.row(InlineKeyboardButton(
        text="🚫 Не сейчас", callback_data="skip_registration"))
    return builder.as_markup()


# Клавиатура запроса телефона (реплай)
def get_phone_reply_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(
        text="📱 Отправить номер телефона", request_contact=True))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# Клавиатура "Мой гараж"
def get_garage_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить автомобиль", callback_data="add_car")
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ В меню", callback_data="back_to_main")
    )
    return builder.as_markup()


# Клавиатура управления конкретным авто
def get_car_management_kb(car_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📝 Создать заявку", callback_data=f"create_request_for_car:{car_id}")
    )
    builder.row(
        InlineKeyboardButton(
            text="✏️ Редактировать авто", callback_data=f"edit_car:{car_id}"),
        InlineKeyboardButton(
            text="🗑 Удалить авто", callback_data=f"delete_car:{car_id}")
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад к списку", callback_data="my_garage")
    )
    return builder.as_markup()


# Клавиатура отмены при создании/редактировании авто
def get_car_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить", callback_data="cancel_car_action")
    )
    return builder.as_markup()


def get_service_types_kb():
    """
    Главное меню выбора вида работ для заявки.
    Список согласован с заказчиком (Автомойки, Шиномонтаж, Автоэлектрик и т.д.).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🧼 Автомойки", callback_data="service_group_wash"),
        InlineKeyboardButton(text="🛞 Шиномонтаж", callback_data="service_group_tire"),
    )
    builder.row(
        InlineKeyboardButton(text="⚡ Автоэлектрик", callback_data="service_group_electric"),
        InlineKeyboardButton(text="🔧 Слесарные работы", callback_data="service_group_mechanic"),
    )
    builder.row(
        InlineKeyboardButton(text="🎨 Малярные работы", callback_data="service_group_paint"),
        InlineKeyboardButton(text="🛠️ Техобслуживание", callback_data="service_group_maint"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Ремонт агрегатов", callback_data="service_group_aggregates"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request"),
    )
    return builder.as_markup()


def get_tire_subtypes_kb():
    """
    Подтипы для шиномонтажа: стационарный сервис и выездной.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🏁 Шиномонтаж (на СТО)",
            callback_data="service_tire_stationary",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🚐 Выездной шиномонтаж",
            callback_data="service_tire_mobile",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="service_back_to_groups"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request"),
    )
    return builder.as_markup()


def get_electric_subtypes_kb():
    """
    Подтипы для автоэлектрика: на сервисе и выездной мастер.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⚡ Автоэлектрик (на СТО)",
            callback_data="service_electric_stationary",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🚐 Выездной автоэлектрик",
            callback_data="service_electric_mobile",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="service_back_to_groups"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request"),
    )
    return builder.as_markup()


def get_aggregates_subtypes_kb():
    """
    Подтипы для ремонта агрегатов: турбина, стартер, генератор, рулевая рейка.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌀 Турбина", callback_data="service_agg_turbo"),
        InlineKeyboardButton(text="🔋 Стартер", callback_data="service_agg_starter"),
    )
    builder.row(
        InlineKeyboardButton(text="⚡ Генератор", callback_data="service_agg_generator"),
        InlineKeyboardButton(text="🛞 Рулевая рейка", callback_data="service_agg_steering"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="service_back_to_groups"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_request"),
    )
    return builder.as_markup()


# Клавиатура для фото (прикрепить / пропустить)
def get_photo_skip_kb():
    """
    Выбор: отправить одно фото или пропустить этап.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📷 Отправить фото", callback_data="attach_photo"),
        InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_photo"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_request")
    )
    return builder.as_markup()


# Клавиатура для подтверждения заявки
def get_request_confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_request"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_request")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_request")
    )
    return builder.as_markup()


# Клавиатура подтверждения удаления авто
def get_delete_confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, удалить", callback_data="confirm_delete_car"),
        InlineKeyboardButton(
            text="❌ Отменить", callback_data="cancel_delete_car")
    )
    return builder.as_markup()


# Клавиатура истории заявок
def get_history_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Активные", callback_data="history_active"),
        InlineKeyboardButton(text="📁 Архив", callback_data="history_archived")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()


# Клавиатура отмены редактирования
def get_edit_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить", callback_data="cancel_edit")
    )
    return builder.as_markup()


# ==============================
# Панель менеджера (инлайн)
# ==============================

def get_manager_main_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📥 Новые заявки", callback_data="manager_new_requests"),
        InlineKeyboardButton(
            text="🔄 В обработке", callback_data="manager_in_progress")
    )
    builder.row(
        InlineKeyboardButton(
            text="📅 Записи", callback_data="manager_scheduled"),
        InlineKeyboardButton(
            text="📁 Архив", callback_data="manager_archive")
    )
    builder.row(
        InlineKeyboardButton(
            text="⚙️ Настройки", callback_data="manager_settings")
    )
    return builder.as_markup()


# Обратная совместимость со старым кодом
def get_manager_panel_kb():
    """
    Старое имя функции, оставлено для совместимости.
    Сейчас просто проксируем на get_manager_main_kb().
    """
    return get_manager_main_kb()



# Клавиатура управления конкретной заявкой для менеджера
def get_manager_request_kb(request_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="👀 Подробнее", callback_data=f"manager_view_request:{request_id}")
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Взять в работу", callback_data=f"manager_take_request:{request_id}"),
        InlineKeyboardButton(
            text="❌ Отклонить", callback_data=f"manager_reject_request:{request_id}")
    )
    return builder.as_markup()


# Клавиатура смены статуса заявки для менеджера
def get_manager_status_kb(request_id: int, current_status: str):
    builder = InlineKeyboardBuilder()
    
    if current_status == "new":
        builder.row(
            InlineKeyboardButton(
                text="🔄 В обработке", callback_data=f"manager_set_status:{request_id}:in_progress"),
            InlineKeyboardButton(
                text="❌ Отклонить", callback_data=f"manager_set_status:{request_id}:rejected")
        )
    elif current_status == "in_progress":
        builder.row(
            InlineKeyboardButton(
                text="📅 Записать", callback_data=f"manager_set_status:{request_id}:scheduled"),
            InlineKeyboardButton(
                text="❌ Отклонить", callback_data=f"manager_set_status:{request_id}:rejected")
        )
        builder.row(
            InlineKeyboardButton(
                text="🔧 В работе", callback_data=f"manager_set_status:{request_id}:in_work")
        )
    elif current_status == "in_work":
        builder.row(
            InlineKeyboardButton(
                text="💰 К оплате", callback_data=f"manager_set_status:{request_id}:to_pay")
        )
    elif current_status == "to_pay":
        builder.row(
            InlineKeyboardButton(
                text="✅ Оплачено", callback_data=f"manager_set_status:{request_id}:paid")
        )
    elif current_status in ["paid", "rejected"]:
        builder.row(
            InlineKeyboardButton(
                text="📁 В архив", callback_data=f"manager_set_status:{request_id}:archived")
        )
    
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад", callback_data=f"manager_view_request:{request_id}")
    )
    
    return builder.as_markup()


# Клавиатура списка заявок для менеджера (пагинация)
def get_manager_requests_list_kb(requests_ids, current_index: int):
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
