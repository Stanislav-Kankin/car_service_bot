from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select, desc
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

import logging

from app.database.models import User, Car, Request
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import get_manager_panel_kb
from app.config import config

router = Router()


class ManagerStates(StatesGroup):
    waiting_manager_comment = State()


@router.message(Command("manager"))
async def cmd_manager(message: Message):
    """Команда для доступа к панели менеджера"""
    logging.info(f"🔧 Обработка команды /manager от пользователя {message.from_user.id}")
    
    if not await is_manager(message.from_user.id):
        await message.answer("❌ Доступ запрещен. У вас нет прав менеджера.")
        return
    
    await message.answer(
        "👨‍💼 <b>Панель менеджера</b>\n\n"
        "Выберите раздел для управления заявками:",
        parse_mode="HTML",
        reply_markup=get_manager_panel_kb()
    )


# Проверка на менеджера
async def is_manager(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь менеджером"""
    admin_id = getattr(config, "ADMIN_USER_ID", None)
    logging.info(f"[is_manager] telegram_id={telegram_id}, ADMIN_USER_ID={admin_id!r}")
    try:
        return int(telegram_id) == int(admin_id)
    except (TypeError, ValueError):
        return False



# Обработчики фильтров для менеджера
@router.callback_query(F.data.startswith("manager_"))
async def manager_filter_requests(callback: CallbackQuery, state: FSMContext):
    """Обработчик всех callback от менеджера"""
    logging.info(f"🔧 Manager callback: {callback.data}")
    
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    try:
        # Обрабатываем разные типы callback
        if callback.data.startswith("manager_view_request:"):
            await handle_view_request(callback)
        elif callback.data.startswith("manager_page:"):
            await handle_pagination(callback)
        elif callback.data.startswith("manager_call:"):
            await manager_call_client(callback)
        elif callback.data.startswith("manager_comment:"):
            await manager_add_comment(callback, state)
        elif callback.data in ["manager_all_requests", "manager_new_requests", "manager_in_progress", 
                              "manager_completed", "manager_rejected", "manager_main_menu"]:
            await handle_filter_requests(callback)
        else:
            logging.warning(f"⚠️ Неизвестный callback: {callback.data}")
            await callback.answer("⚠️ Неизвестная команда")
            
    except Exception as e:
        logging.error(f"❌ Ошибка обработки callback: {e}")
        await callback.answer("❌ Ошибка")


async def handle_view_request(callback: CallbackQuery):
    """Обработчик просмотра заявки"""
    try:
        request_id = int(callback.data.split(":")[1])
        logging.info(f"🔧 Открытие заявки #{request_id}")
        await show_manager_request_detail(callback, request_id)
    except Exception as e:
        logging.error(f"❌ Ошибка открытия заявки: {e}")
        await callback.answer("❌ Ошибка при открытии заявки")

async def handle_pagination(callback: CallbackQuery):
    """Обработчик пагинации"""
    try:
        data_parts = callback.data.split(":")
        if len(data_parts) != 3:
            logging.error(f"❌ Неверный формат пагинации: {callback.data}")
            await callback.answer("❌ Ошибка пагинации")
            return
            
        filter_type = data_parts[1]
        page = int(data_parts[2])
        
        logging.info(f"🔧 Пагинация: filter={filter_type}, page={page}")
        
        status_map = {
            "all": None,
            "new": "new",
            "in_progress": "in_progress",
            "completed": "completed", 
            "rejected": "rejected"
        }
        
        status = status_map.get(filter_type)
        await show_manager_requests_list(callback, filter_status=status, page=page)
        
    except Exception as e:
        logging.error(f"❌ Ошибка пагинации: {e}")
        await callback.answer("❌ Ошибка пагинации")

async def handle_filter_requests(callback: CallbackQuery):
    """Обработчик фильтров"""
    filter_type = callback.data.replace("manager_", "")
    
    if filter_type == "main_menu":
        await manager_main_menu(callback)
        return
        
    status_map = {
        "all_requests": None,
        "new_requests": "new",
        "in_progress": "in_progress", 
        "completed": "completed",
        "rejected": "rejected"
    }
    
    status = status_map.get(filter_type)
    await show_manager_requests_list(callback, filter_status=status, page=0)

# Функция показа списка заявок с пагинацией
async def show_manager_requests_list(callback: CallbackQuery, filter_status: str = None, page: int = 0):
    """Показывает список заявок с пагинацией"""
    LIMIT = 5
    
    async with AsyncSessionLocal() as session:
        try:
            logging.info(f"🔧 Загрузка заявок: status={filter_status}, page={page}")
            
            # Строим запрос БЕЗ кэширования
            query = (
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
            )
            
            if filter_status:
                query = query.where(Request.status == filter_status)
            
            # Получаем общее количество для пагинации
            count_query = query.with_only_columns(Request.id)
            total_count_result = await session.execute(count_query)
            total_count = len(total_count_result.all())
            logging.info(f"🔧 Всего заявок: {total_count}")
            
            # Получаем заявки для текущей страницы
            query = query.order_by(desc(Request.created_at)).offset(page * LIMIT).limit(LIMIT)
            requests_result = await session.execute(query)
            results = requests_result.all()
            
            logging.info(f"🔧 Найдено заявок на странице: {len(results)}")
            
            if not results:
                no_requests_text = {
                    None: "📋 Нет заявок в системе",
                    "new": "🆕 Нет новых заявок",
                    "in_progress": "⏳ Нет заявок в работе", 
                    "completed": "✅ Нет завершенных заявок",
                    "rejected": "❌ Нет отклоненных заявок"
                }
                
                await callback.message.edit_text(
                    no_requests_text.get(filter_status, "📋 Нет заявок"),
                    reply_markup=get_manager_panel_kb()
                )
                return
            
            # Формируем список заявок
            requests_text = "📋 <b>Список заявок</b>\n\n"
            
            status_emojis = {
                "new": "🆕",
                "accepted": "✅", 
                "in_progress": "⏳",
                "rejected": "❌",
                "completed": "🏁"
            }
            
            status_texts = {
                "new": "Новая",
                "accepted": "Принята",
                "in_progress": "В работе",
                "rejected": "Отклонена", 
                "completed": "Завершена"
            }

            for i, (request, user, car) in enumerate(results, page * LIMIT + 1):
                emoji = status_emojis.get(request.status, "📋")
                status_text = status_texts.get(request.status, request.status)
                created_date = request.created_at.strftime("%d.%m.%Y %H:%M")
                
                requests_text += (
                    f"{emoji} <b>Заявка #{request.id}</b>\n"
                    f"   👤 {user.full_name}\n"
                    f"   🚗 {car.brand} {car.model}\n"
                    f"   🛠️ {request.service_type}\n"
                    f"   📅 {created_date}\n"
                    f"   📊 {status_text}\n\n"
                )
            
            # Добавляем информацию о пагинации
            total_pages = (total_count + LIMIT - 1) // LIMIT if total_count > 0 else 1
            requests_text += f"<i>Страница {page + 1} из {total_pages}</i>\n\n"
            
            # Добавляем информацию о фильтре
            filter_info = {
                None: "📋 Показаны все заявки",
                "new": "🆕 Показаны новые заявки",
                "in_progress": "⏳ Показаны заявки в работе",
                "completed": "✅ Показаны завершенные заявки",
                "rejected": "❌ Показаны отклоненные заявки"
            }
            
            requests_text += f"<i>{filter_info.get(filter_status, '')}</i>"
            
            # Создаем клавиатуру с пагинацией
            builder = InlineKeyboardBuilder()
            
            # Кнопки для заявок
            for request, user, car in results:
                status_emoji = status_emojis.get(request.status, "📋")
                builder.row(
                    InlineKeyboardButton(
                        text=f"{status_emoji} #{request.id} - {user.full_name}",
                        callback_data=f"manager_view_request:{request.id}"
                    )
                )
            
            # Кнопки пагинации
            pagination_buttons = []
            if page > 0:
                pagination_buttons.append(
                    InlineKeyboardButton(
                        text="⬅️ Назад", 
                        callback_data=f"manager_page:{filter_status or 'all'}:{page - 1}"
                    )
                )
            
            if (page + 1) * LIMIT < total_count:
                pagination_buttons.append(
                    InlineKeyboardButton(
                        text="Вперед ➡️", 
                        callback_data=f"manager_page:{filter_status or 'all'}:{page + 1}"
                    )
                )
            
            if pagination_buttons:
                builder.row(*pagination_buttons)
            
            # Кнопки фильтров
            builder.row(
                InlineKeyboardButton(text="🆕 Новые", callback_data="manager_new_requests"),
                InlineKeyboardButton(text="⏳ В работе", callback_data="manager_in_progress")
            )
            builder.row(
                InlineKeyboardButton(text="✅ Завершенные", callback_data="manager_completed"),
                InlineKeyboardButton(text="❌ Отклоненные", callback_data="manager_rejected")
            )
            builder.row(
                InlineKeyboardButton(text="📋 Все", callback_data="manager_all_requests"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_main_menu")
            )
            
            # Обновляем сообщение
            await callback.message.edit_text(
                requests_text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
            
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке заявок для менеджера: {e}")
            await callback.message.edit_text(
                "❌ Ошибка при загрузке заявок.",
                reply_markup=get_manager_panel_kb()
            )

async def show_manager_request_detail(callback: CallbackQuery, request_id: int):
    """Показывает детальную информацию о заявке"""
    async with AsyncSessionLocal() as session:
        try:
            logging.info(f"🔧 Загрузка деталей заявки #{request_id}")
            
            # Получаем заявку с связанными данными
            request_result = await session.execute(
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
                .where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user, car = result
            
            # Формируем детальную информацию
            status_texts = {
                "new": "🆕 Новая",
                "accepted": "✅ Принята",
                "in_progress": "⏳ В работе", 
                "rejected": "❌ Отклонена",
                "completed": "🏁 Завершена"
            }
            
            detail_text = (
                f"📋 <b>Заявка #{request.id}</b>\n\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n"
                f"📞 <b>Телефон:</b> {user.phone_number or 'Не указан'}\n"
                f"🆔 <b>ID пользователя:</b> {user.telegram_id}\n\n"
                f"🚗 <b>Автомобиль:</b>\n"
                f"   • Марка: {car.brand}\n"
                f"   • Модель: {car.model}\n"
                f"   • Год: {car.year or 'Не указан'}\n"
                f"   • Госномер: {car.license_plate or 'Не указан'}\n\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"📝 <b>Описание:</b>\n{request.description}\n\n"
            )
            
            if request.preferred_date:
                detail_text += f"🗓️ <b>Желаемая дата:</b> {request.preferred_date}\n\n"
            
            # Добавляем временные метки
            detail_text += f"⏰ <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            detail_text += f"📊 <b>Статус:</b> {status_texts.get(request.status, request.status)}\n"
            
            # Добавляем время изменения статусов
            if request.accepted_at:
                detail_text += f"✅ <b>Принята:</b> {request.accepted_at.strftime('%d.%m.%Y %H:%M')}\n"
            if request.in_progress_at:
                detail_text += f"⏳ <b>В работе:</b> {request.in_progress_at.strftime('%d.%m.%Y %H:%M')}\n"
            if request.completed_at:
                detail_text += f"🏁 <b>Завершена:</b> {request.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
            if request.rejected_at:
                detail_text += f"❌ <b>Отклонена:</b> {request.rejected_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            # Если есть комментарий менеджера
            if request.manager_comment:
                detail_text += f"\n💬 <b>Комментарий менеджера:</b>\n{request.manager_comment}\n"
            
            # Создаем клавиатуру с действиями
            builder = InlineKeyboardBuilder()
            
            # Кнопки действий в зависимости от статуса
            if request.status == 'new':
                builder.row(
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"chat_accept:{request.id}"),
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request.id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request.id}")
                )
            elif request.status == 'accepted':
                builder.row(
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"chat_in_progress:{request.id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"chat_reject:{request.id}")
                )
            elif request.status == 'in_progress':
                builder.row(
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"chat_complete:{request.id}"),
                )
            
            # ИСПРАВЛЕННЫЕ КНОПКИ - используем manager_ префикс
            builder.row(
                InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request.id}"),
                InlineKeyboardButton(text="💬 Комментарий", callback_data=f"manager_comment:{request.id}")
            )
            builder.row(
                InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="manager_all_requests")
            )
            
            # Редактируем текущее сообщение
            await callback.message.edit_text(
                detail_text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
            
            await callback.answer()
            
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке деталей заявки: {e}")
            await callback.answer("❌ Ошибка при загрузке заявки")

# Обработчик кнопки "⬅️ Назад" в панели менеджера
@router.callback_query(F.data == "manager_main_menu")
async def manager_main_menu(callback: CallbackQuery):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await callback.message.edit_text(
        "👨‍💼 <b>Панель менеджера</b>\n\n"
        "Выберите раздел для управления заявками:",
        parse_mode="HTML",
        reply_markup=get_manager_panel_kb()
    )
    await callback.answer()

@router.message(Command("debug_request"))
async def cmd_debug_request(message: Message):
    """Отладочная команда для проверки конкретной заявки"""
    if not await is_manager(message.from_user.id):
        return
    
    try:
        # Получаем ID заявки из команды
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Использование: /debug_request <ID_заявки>")
            return
            
        request_id = int(parts[1])
        
        async with AsyncSessionLocal() as session:
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()
            
            if request:
                debug_text = (
                    f"📋 Заявка #{request.id}\n"
                    f"Статус: {request.status}\n"
                    f"Создана: {request.created_at}\n"
                    f"Принята: {request.accepted_at}\n"
                    f"В работе: {request.in_progress_at}\n"
                    f"Завершена: {request.completed_at}\n"
                    f"Отклонена: {request.rejected_at}\n"
                )
                await message.answer(f"<pre>{debug_text}</pre>", parse_mode="HTML")
            else:
                await message.answer("❌ Заявка не найдена")
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("debug_all_requests"))
async def cmd_debug_all_requests(message: Message):
    """Отладочная команда для проверки всех заявок"""
    if not await is_manager(message.from_user.id):
        return
    
    async with AsyncSessionLocal() as session:
        try:
            requests_result = await session.execute(
                select(Request.id, Request.status, User.full_name, Request.created_at)
                .join(User, Request.user_id == User.id)
                .order_by(desc(Request.created_at))
            )
            requests = requests_result.all()
            
            if not requests:
                await message.answer("📋 В БД нет заявок")
                return
            
            debug_text = "📋 <b>Все заявки в БД:</b>\n\n"
            for request_id, status, user_name, created_at in requests:
                debug_text += f"#{request_id} - {user_name} - {status} - {created_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            await message.answer(debug_text, parse_mode="HTML")
            
        except Exception as e:
            logging.error(f"❌ Ошибка проверки БД: {e}")
            await message.answer("❌ Ошибка при проверке БД")


# Добавление комментария
@router.callback_query(F.data.startswith("manager_comment:"))
async def manager_add_comment(callback: CallbackQuery, state: FSMContext):
    """Добавить комментарий к заявке"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    try:
        request_id = int(callback.data.split(":")[1])
        
        # Сохраняем данные в состоянии
        await state.set_state(ManagerStates.waiting_manager_comment)
        await state.update_data(request_id=request_id)
        
        await callback.message.answer(
            f"💬 Введите комментарий для заявки #{request_id}:",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"manager_view_request:{request_id}")
            ).as_markup()
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"❌ Ошибка добавления комментария: {e}")
        await callback.answer("❌ Ошибка")

# Обработчик текста комментария
@router.message(ManagerStates.waiting_manager_comment, F.text)
async def process_manager_comment(message: Message, state: FSMContext):
    """Обработка комментария менеджера (как предложение условий для клиента)"""
    try:
        user_data = await state.get_data()
        request_id = user_data["request_id"]
        comment_text = message.text.strip()

        if not comment_text:
            await message.answer("❌ Комментарий не может быть пустым. Попробуйте еще раз:")
            return

        logging.info(f"🔧 Сохранение комментария для заявки #{request_id}: {comment_text}")

        async with AsyncSessionLocal() as session:
            try:
                # Получаем заявку и пользователя
                request_result = await session.execute(
                    select(Request, User)
                    .join(User, Request.user_id == User.id)
                    .where(Request.id == request_id)
                )
                row = request_result.first()

                if not row:
                    await message.answer("❌ Заявка не найдена")
                    await state.clear()
                    return

                request, user = row

                # Сохраняем комментарий менеджера
                request.manager_comment = comment_text
                await session.commit()

                logging.info(f"✅ Комментарий сохранен для заявки #{request_id}")

                # Ответ менеджеру
                await message.answer(
                    f"✅ Комментарий добавлен к заявке #{request_id}",
                    reply_markup=InlineKeyboardBuilder()
                    .row(
                        InlineKeyboardButton(
                            text="⬅️ Назад к заявке",
                            callback_data=f"manager_view_request:{request_id}",
                        )
                    )
                    .as_markup(),
                )

                # Отправляем клиенту предложение с кнопками
                try:
                    from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

                    kb = InlineKeyboardBuilder()
                    kb.row(
                        InlineKeyboardButton(
                            text="✅ Подтвердить условия",
                            callback_data=f"client_accept_offer:{request.id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отказаться",
                            callback_data=f"client_reject_offer:{request.id}",
                        ),
                    )

                    offer_text = (
                        f"💬 <b>Комментарий от менеджера по вашей заявке #{request.id}</b>\n\n"
                        f"{comment_text}\n\n"
                        "Подтвердите, если вас устраивают условия."
                    )

                    await message.bot.send_message(
                        chat_id=user.telegram_id,
                        text=offer_text,
                        parse_mode="HTML",
                        reply_markup=kb.as_markup(),
                    )
                except Exception as send_err:
                    logging.error(
                        f"❌ Не удалось отправить комментарий клиенту по заявке #{request_id}: {send_err}"
                    )

            except Exception as db_err:
                await session.rollback()
                logging.error(f"❌ Ошибка сохранения комментария в БД: {db_err}")
                await message.answer("❌ Ошибка при сохранении комментария")

        await state.clear()

    except Exception as e:
        logging.error(f"❌ Ошибка обработки комментария менеджера: {e}")
        await message.answer("❌ Ошибка при обработке комментария")



@router.callback_query(F.data.startswith("manager_view_request:"), ManagerStates.waiting_manager_comment)
async def cancel_comment(callback: CallbackQuery, state: FSMContext):
    """Отмена добавления комментария"""
    await state.clear()
    request_id = int(callback.data.split(":")[1])
    await show_manager_request_detail(callback, request_id)


@router.callback_query(F.data.startswith("manager_call:"))
async def manager_call_client(callback: CallbackQuery):
    """Показать контакты клиента"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    try:
        request_id = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            # Получаем данные заявки и пользователя
            request_result = await session.execute(
                select(Request, User)
                .join(User, Request.user_id == User.id)
                .where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                await callback.answer("❌ Заявка не найдена")
                return
            
            request, user = result
            
            if not user.phone_number:
                await callback.answer("❌ У клиента не указан номер телефона")
                return
            
            # Показываем номер телефона
            call_message = (
                f"📞 <b>Контакт клиента</b>\n\n"
                f"📋 <b>Заявка:</b> #{request.id}\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n"
                f"📱 <b>Телефон:</b> {user.phone_number}\n\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n"
                f"🚗 <b>Автомобиль:</b> {await get_car_info(session, request.car_id)}"
            )
            
            await callback.message.answer(
                call_message,
                parse_mode="HTML"
            )
            await callback.answer()
            
    except Exception as e:
        logging.error(f"❌ Ошибка при получении контакта: {e}")
        await callback.answer("❌ Ошибка при получении контакта")

async def get_car_info(session, car_id: int) -> str:
    """Получить информацию об автомобиле"""
    try:
        car_result = await session.execute(
            select(Car).where(Car.id == car_id)
        )
        car = car_result.scalar_one_or_none()
        if car:
            return f"{car.brand} {car.model} ({car.year or 'год не указан'})"
        return "не указан"
    except:
        return "не указан"


@router.message(Command("check_comment"))
async def cmd_check_comment(message: Message):
    """Проверить комментарий заявки"""
    if not await is_manager(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Использование: /check_comment <ID_заявки>")
            return
            
        request_id = int(parts[1])
        
        async with AsyncSessionLocal() as session:
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()
            
            if request:
                comment_info = (
                    f"📋 Заявка #{request.id}\n"
                    f"Комментарий: {request.manager_comment or '❌ Нет комментария'}\n"
                    f"Длина комментария: {len(request.manager_comment) if request.manager_comment else 0}"
                )
                await message.answer(f"<pre>{comment_info}</pre>", parse_mode="HTML")
            else:
                await message.answer("❌ Заявка не найдена")
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")