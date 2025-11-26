from aiogram.types import (
    InlineKeyboardButton,
    KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder, InlineKeyboardMarkup


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
    # 🔹 Автосервисы + бонусы
    builder.row(
        InlineKeyboardButton(
            text="🏭 Автосервисы", callback_data="service_centers_list"),
        InlineKeyboardButton(
            text="🎁 Мои бонусы", callback_data="my_points")
    )
    # 🔍 Отдельная кнопка поиска по геолокации
    builder.row(
        InlineKeyboardButton(
            text="🔍 Найти СТО рядом", callback_data="service_centers_search")
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
# Клавиатура панель менеджера
# ==============================
def get_manager_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Основные разделы
    builder.button(text="📥 Новые заявки", callback_data="manager_new_requests")
    builder.button(text="🔄 В обработке", callback_data="manager_in_progress")
    builder.button(text="📅 Записи", callback_data="manager_scheduled")
    builder.button(text="📁 Архив", callback_data="manager_archive")
    # Поиск
    builder.button(text="🔍 Поиск заявки", callback_data="manager_search")
    # Настройки
    builder.button(text="⚙️ Настройки", callback_data="manager_settings")
    builder.adjust(2, 2, 1, 1)
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
            InlineKeyboardButton(text="⬅️ Предыдущая",
                                 callback_data=f"manager_view_request:{requests_ids[current_index - 1]}")
        )

    builder.row(
        InlineKeyboardButton(text="📋 К списку", callback_data="manager_all_requests")
    )

    if current_index < len(requests_ids) - 1:
        builder.row(
            InlineKeyboardButton(text="Следующая ➡️",
                                 callback_data=f"manager_view_request:{requests_ids[current_index + 1]}")
        )

    return builder.as_markup()


def get_can_drive_kb():
    """
    Клавиатура для вопроса:
    Может ли автомобиль передвигаться своим ходом?
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, может ехать сам",
            callback_data="can_drive_yes",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🚚 Нет, нужен эвакуатор/прицеп",
            callback_data="can_drive_no",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить заявку",
            callback_data="cancel_request",
        )
    )
    return builder.as_markup()


def get_location_reply_kb():
    """
    Reply-клавиатура для отправки геолокации или текстового адреса.
    """
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(
            text="📍 Отправить геолокацию",
            request_location=True,
        )
    )
    builder.row(
        KeyboardButton(
            text="⏭️ Пропустить локацию",
        )
    )
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_role_kb():
    """
    Выбор роли при регистрации: клиент или автосервис.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🚗 Я клиент",
            callback_data="reg_role_client",
        ),
        InlineKeyboardButton(
            text="🏭 Я автосервис",
            callback_data="reg_role_service",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_registration",
        )
    )
    return builder.as_markup()


# Опции специализаций для автосервисов
# код, человекочитаемое название
SERVICE_SPECIALIZATION_OPTIONS: list[tuple[str, str]] = [
    ("wash", "🧼 Автомойка"),
    ("tire", "🛞 Шиномонтаж"),
    ("electric", "⚡ Автоэлектрик"),
    ("mechanic", "🔧 Слесарные работы"),
    ("paint", "🎨 Малярные работы"),
    ("maint", "🛠️ Техобслуживание"),
    ("agg_turbo", "🌀 Турбины"),
    ("agg_starter", "🔋 Стартеры"),
    ("agg_generator", "⚡ Генераторы"),
    ("agg_steering", "🛞 Рулевые рейки"),
]


def get_service_specializations_kb(
    selected: set[str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Мультивыбор специализаций автосервиса при регистрации.

    selected — множество выбранных кодов ('wash', 'tire', ...).
    """
    if selected is None:
        selected = set()

    builder = InlineKeyboardBuilder()

    for code, label in SERVICE_SPECIALIZATION_OPTIONS:
        prefix = "✅ " if code in selected else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{prefix}{label}",
                callback_data=f"spec_toggle:{code}",
            )
        )

    # Кнопки управления
    builder.row(
        InlineKeyboardButton(
            text="✅ Готово",
            callback_data="spec_done",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⏭️ Пропустить (принимать любые заявки)",
            callback_data="spec_skip",
        )
    )

    return builder.as_markup()


def get_service_notifications_kb():
    """
    Куда отдавать заявки автосервису при регистрации.

    На данный момент поддерживаем ОДИН вариант:
    - только в ЛС владельцу
    - только в группу
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📩 В личные сообщения",
            callback_data="sc_notif_owner",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="👥 В группу Telegram",
            callback_data="sc_notif_group",
        )
    )
    return builder.as_markup()


def get_rating_kb(request_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для оценки сервиса по заявке.
    """
    builder = InlineKeyboardBuilder()
    for score in range(1, 6):
        builder.button(
            text=f"{score}⭐",
            callback_data=f"rate_request:{request_id}:{score}",
        )
    builder.adjust(5)
    return builder.as_markup()


# Клавиатура для сброса профиля
def get_reset_profile_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Полный сброс профиля",
                    callback_data="reset_profile_full",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📱 Сменить номер телефона",
                    callback_data="reset_profile_phone",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_reset_registration",
                )
            ],
        ]
    )
    return kb


def get_search_radius_kb() -> InlineKeyboardMarkup:
    """
    Радиус поиска СТО + кнопка 'Показать всех'.
    """
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 км", callback_data="radius:5"),
                InlineKeyboardButton(text="10 км", callback_data="radius:10"),
            ],
            [
                InlineKeyboardButton(text="30 км", callback_data="radius:30"),
                InlineKeyboardButton(text="100 км", callback_data="radius:100"),
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Показать всех",
                    callback_data="show_all_services"
                )
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"),
            ],
        ]
    )
    return kb


def get_time_slot_kb():
    """
    Инлайн-клавиатура для выбора удобного времени:
    до 12, 12–18, после 18.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="До 12:00",
            callback_data="time_slot:morning",
        ),
        InlineKeyboardButton(
            text="12:00–18:00",
            callback_data="time_slot:day",
        ),
        InlineKeyboardButton(
            text="После 18:00",
            callback_data="time_slot:evening",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔁 Изменить дату",
            callback_data="time_slot:change_date",
        ),
        InlineKeyboardButton(
            text="❌ Отменить заявку",
            callback_data="cancel_request",
        ),
    )
    return builder.as_markup()
