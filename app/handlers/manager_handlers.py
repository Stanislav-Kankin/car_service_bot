from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select, desc
from datetime import datetime
import logging

from app.database.models import User, Car, Request
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import get_manager_panel_kb
from app.config import config

router = Router()


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


async def is_manager(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь менеджером"""
    return str(telegram_id) == config.ADMIN_USER_ID


# Обработчики фильтров для менеджера
@router.callback_query(F.data.startswith("manager_"))
async def manager_filter_requests(callback: CallbackQuery):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    filter_type = callback.data.replace("manager_", "")
    
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
    LIMIT = 5  # Заявок на страницу
    
    async with AsyncSessionLocal() as session:
        try:
            # Строим запрос
            query = (
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
            )
            
            if filter_status:
                query = query.where(Request.status == filter_status)
            
            # Получаем общее количество для пагинации
            total_count_result = await session.execute(
                query.with_only_columns(Request.id)
            )
            total_count = len(total_count_result.all())
            
            # Получаем заявки для текущей страницы
            query = query.order_by(desc(Request.created_at)).offset(page * LIMIT).limit(LIMIT)
            requests_result = await session.execute(query)
            results = requests_result.all()
            
            if not results:
                no_requests_text = {
                    None: "📋 Нет заявок в системе",
                    "new": "🆕 Нет новых заявок",
                    "in_progress": "⏳ Нет заявок в работе", 
                    "completed": "✅ Нет завершенных заявок",
                    "rejected": "❌ Нет отклоненных заявок"
                }
                
                # Используем answer вместо edit_text для нового сообщения
                await callback.message.answer(
                    no_requests_text.get(filter_status, "📋 Нет заявок"),
                    reply_markup=get_manager_panel_kb()
                )
                # Удаляем старое сообщение чтобы избежать дублирования
                try:
                    await callback.message.delete()
                except:
                    pass
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
            total_pages = (total_count + LIMIT - 1) // LIMIT  # Округление вверх
            requests_text += f"<i>Страница {page + 1} из {total_pages if total_pages > 0 else 1}</i>\n\n"
            
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
            
            # Используем answer для нового сообщения вместо edit_text
            await callback.message.answer(
                requests_text,
                parse_mode="HTML",
                reply_markup=builder.as_markup()
            )
            # Удаляем старое сообщение чтобы избежать дублирования
            try:
                await callback.message.delete()
            except:
                pass
            
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке заявок для менеджера: {e}")
            # Используем answer вместо edit_text при ошибке
            await callback.message.answer(
                "❌ Ошибка при загрузке заявок.",
                reply_markup=get_manager_panel_kb()
            )


# Обработчик пагинации
# Обработчик пагинации
@router.callback_query(F.data.startswith("manager_page:"))
async def manager_pagination(callback: CallbackQuery):
    """Обрабатывает переключение страниц"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    try:
        _, filter_type, page_str = callback.data.split(":")
        page = int(page_str)
        
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
        await callback.answer("❌ Ошибка")


# Обработчик просмотра деталей заявки
@router.callback_query(F.data.startswith("manager_view_request:"))
async def manager_view_request_detail(callback: CallbackQuery):
    """Детальный просмотр заявки"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    request_id = int(callback.data.split(":")[1])
    await show_manager_request_detail(callback, request_id)


async def show_manager_request_detail(callback: CallbackQuery, request_id: int):
    """Показывает детальную информацию о заявке"""
    async with AsyncSessionLocal() as session:
        try:
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
            
            # Если есть комментарий менеджера
            if request.manager_comment:
                detail_text += f"\n💬 <b>Комментарий менеджера:</b>\n{request.manager_comment}\n"
            
            # Создаем клавиатуру
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="manager_all_requests"),
                InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request.id}")
            )
            
            # Используем answer для нового сообщения
            if request.photo_file_id:
                await callback.message.answer_photo(
                    photo=request.photo_file_id,
                    caption=detail_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            else:
                await callback.message.answer(
                    detail_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            # Удаляем старое сообщение
            try:
                await callback.message.delete()
            except:
                pass
            
        except Exception as e:
            logging.error(f"❌ Ошибка при загрузке деталей заявки: {e}")
            await callback.answer("❌ Ошибка при загрузке заявки")

# Обработчик кнопки "Позвонить"
@router.callback_query(F.data.startswith("manager_call:"))
async def manager_call_client(callback: CallbackQuery):
    request_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        try:
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
                f"🛠️ <b>Услуга:</b> {request.service_type}"
            )
            
            await callback.message.answer(
                call_message,
                parse_mode="HTML"
            )
            await callback.answer()
            
        except Exception as e:
            logging.error(f"Ошибка при получении контакта: {e}")
            await callback.answer("❌ Ошибка при получении контакта")


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