from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database.models import User, Car, Request
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import (
    get_manager_request_kb, get_manager_cancel_kb,
    get_manager_panel_kb, get_manager_request_detail_kb,
    get_manager_requests_navigation_kb
)
from app.config import config

router = Router()

router.callback_query.filter()
router.message.filter()


class ManagerForm(StatesGroup):
    waiting_for_price = State()
    waiting_for_deadline = State()
    waiting_for_clarification = State()
    waiting_for_reject_reason = State()

    waiting_for_comment = State()
    waiting_for_search = State()


# Функция для отправки уведомления о новой заявке менеджеру
async def notify_manager_about_new_request(bot: Bot, request_id: int):
    if not config.MANAGER_CHAT_ID:
        logging.warning("MANAGER_CHAT_ID не установлен - уведомление не отправлено")
        return
    
    async with AsyncSessionLocal() as session:  # ← ИСПРАВИТЬ НА АСИНХРОННУЮ СЕССИЮ
        try:
            # Получаем данные заявки
            request_result = await session.execute(
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
                .where(Request.id == request_id)
            )
            result = request_result.first()
            
            if not result:
                logging.error(f"Заявка #{request_id} не найдена")
                return
            
            request, user, car = result
            
            # Формируем сообщение для менеджера
            message_text = (
                "🆕 <b>НОВАЯ ЗАЯВКА</b>\n\n"
                f"📋 <b>№{request.id}</b>\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n"
                f"📞 <b>Телефон:</b> {user.phone_number or 'Не указан'}\n"
                f"🚗 <b>Автомобиль:</b> {car.brand} {car.model}\n"
                f"🗓️ <b>Год:</b> {car.year or 'Не указан'}\n"
                f"🚙 <b>Номер:</b> {car.license_plate or 'Не указан'}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n"
                f"📝 <b>Описание:</b> {request.description}\n"
                f"🗓️ <b>Желаемая дата:</b> {request.preferred_date}\n"
                f"⏰ <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            )
            
            # Отправляем сообщение менеджеру
            if request.photo_file_id:
                await bot.send_photo(
                    chat_id=config.MANAGER_CHAT_ID,
                    photo=request.photo_file_id,
                    caption=message_text,
                    parse_mode="HTML",
                    reply_markup=get_manager_request_kb(request.id)
                )
            else:
                await bot.send_message(
                    chat_id=config.MANAGER_CHAT_ID,
                    text=message_text,
                    parse_mode="HTML",
                    reply_markup=get_manager_request_kb(request.id)
                )
                
            logging.info(f"Уведомление о заявке #{request_id} отправлено менеджеру")
            
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления менеджеру: {e}")


# Обработчик принятия заявки менеджером
@router.callback_query(F.data.startswith("manager_accept:"))
async def manager_accept_request(callback: CallbackQuery, state: FSMContext):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
        
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    # Используем безопасную функцию
    await safe_manager_reply(
        callback,
        f"✅ Принятие заявки #{request_id}\n\n"
        "Введите ориентировочную стоимость услуги:\n\n"
        "<i>Пример: 5000 руб, 15000 руб, бесплатно по гарантии</i>",
        get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_price)


# Обработчик ввода цены
@router.message(ManagerForm.waiting_for_price, ~F.text.startswith('/'))
async def process_manager_price(message: Message, state: FSMContext):
    price = message.text.strip()
    
    # Если это команда - игнорируем
    if price.startswith('/'):
        await message.answer("❌ Пожалуйста, введите стоимость, а не команду")
        return
    
    if len(price) < 2:
        await message.answer(
            "❌ Слишком короткая стоимость. Введите корректную стоимость:",
            reply_markup=get_manager_cancel_kb()
        )
        return
    
    await state.update_data(price=price)
    
    user_data = await state.get_data()
    request_id = user_data['request_id']
    
    await message.answer(
        f"💰 Стоимость: {price}\n\n"
        "Теперь введите ориентировочные сроки выполнения:\n\n"
        "<i>Пример: 2-3 дня, завтра к вечеру, 1 неделя</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_deadline)


# Обработчик ввода сроков - УБЕРИТЕ bot: Bot из параметров
@router.message(ManagerForm.waiting_for_deadline, ~F.text.startswith('/'))
async def process_manager_deadline(message: Message, state: FSMContext):
    deadline = message.text.strip()
    
    # Если это команда - игнорируем
    if deadline.startswith('/'):
        await message.answer("❌ Пожалуйста, введите сроки, а не команду")
        return
    
    if len(deadline) < 2:
        await message.answer(
            "❌ Слишком короткий срок. Введите корректные сроки:",
            reply_markup=get_manager_cancel_kb()
        )
        return
    
    user_data = await state.get_data()
    request_id = user_data['request_id']
    price = user_data['price']
    
    async with AsyncSessionLocal() as session:
        try:
            # Обновляем статус заявки
            request_result = await session.execute(select(Request).where(Request.id == request_id))
            request = request_result.scalar_one_or_none()
            
            if not request:
                await message.answer("❌ Заявка не найдена")
                await state.clear()
                return
            
            # Обновляем статус
            request.status = 'accepted'
            await session.commit()
            
            # Получаем данные пользователя для уведомления
            user_result = await session.execute(select(User).where(User.id == request.user_id))
            user = user_result.scalar_one_or_none()
            
            # Отправляем уведомление пользователю
            if user:
                user_message = (
                    "✅ <b>Ваша заявка принята!</b>\n\n"
                    f"📋 <b>Номер заявки:</b> #{request.id}\n"
                    f"💰 <b>Ориентировочная стоимость:</b> {price}\n"
                    f"⏰ <b>Ориентировочные сроки:</b> {deadline}\n\n"
                    f"📞 <b>Менеджер свяжется с вами для уточнения деталей.</b>"
                )
                
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=user_message,
                    parse_mode="HTML"
                )
            
            # Обновляем сообщение у менеджера
            await message.answer(
                f"✅ Заявка #{request_id} принята!\n\n"
                f"💰 <b>Стоимость:</b> {price}\n"
                f"⏰ <b>Сроки:</b> {deadline}\n\n"
                f"📞 Уведомление отправлено клиенту.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при принятии заявки: {e}")
            await message.answer("❌ Ошибка при принятии заявки")
        finally:
            await state.clear()


# Обработчик отклонения заявки
@router.callback_query(F.data.startswith("manager_reject:"))
async def manager_reject_request(callback: CallbackQuery, state: FSMContext):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
        
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    # Используем безопасную функцию
    await safe_manager_reply(
        callback,
        f"❌ Отклонение заявки #{request_id}\n\n"
        "Укажите причину отклонения:\n\n"
        "<i>Пример: Нет запчастей, не обслуживаем эту марку, несоответствие требованиям</i>",
        get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_reject_reason)


# Обработчик ввода причины отклонения
@router.message(ManagerForm.waiting_for_reject_reason)
async def process_reject_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    
    if len(reason) < 5:
        await message.answer(
            "❌ Слишком короткая причина. Опишите подробнее:",
            reply_markup=get_manager_cancel_kb()
        )
        return
    
    user_data = await state.get_data()
    request_id = user_data['request_id']
    
    async with AsyncSessionLocal() as session:
        try:
            # Обновляем статус заявки
            request_result = await session.execute(select(Request).where(Request.id == request_id))
            request = request_result.scalar_one_or_none()
            
            if not request:
                await message.answer("❌ Заявка не найдена")
                await state.clear()
                return
            
            # Обновляем статус
            request.status = 'rejected'
            await session.commit()
            
            # Получаем данные пользователя для уведомления
            user_result = await session.execute(select(User).where(User.id == request.user_id))
            user = user_result.scalar_one_or_none()
            
            # Отправляем уведомление пользователю
            if user:
                user_message = (
                    "❌ <b>Ваша заявка отклонена</b>\n\n"
                    f"📋 <b>Номер заявки:</b> #{request.id}\n"
                    f"📝 <b>Причина:</b> {reason}\n\n"
                    f"ℹ️ <b>Вы можете создать новую заявку с учетом замечаний.</b>"
                )
                
                await message.bot.send_message(
                    chat_id=user.telegram_id,
                    text=user_message,
                    parse_mode="HTML"
                )
            
            # Обновляем сообщение у менеджера
            await message.answer(
                f"❌ Заявка #{request_id} отклонена!\n\n"
                f"📝 <b>Причина:</b> {reason}\n\n"
                f"ℹ️ Уведомление отправлено клиенту.",
                parse_mode="HTML"
            )
            
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при отклонении заявки: {e}")
            await message.answer("❌ Ошибка при отклонении заявки")
        finally:
            await state.clear()


# Обработчик уточнения заявки
@router.callback_query(F.data.startswith("manager_clarify:"))
async def manager_clarify_request(callback: CallbackQuery, state: FSMContext):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
        
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    # Используем безопасную функцию
    await safe_manager_reply(
        callback,
        f"✏️ Уточнение заявки #{request_id}\n\n"
        "Что нужно уточнить у клиента?\n\n"
        "<i>Пример: Уточните VIN код, В какое время вам удобно, Какой именно звук издает двигатель?</i>",
        get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_clarification)


# Обработчик ввода уточнения - УБЕРИТЕ bot: Bot из параметров
@router.message(ManagerForm.waiting_for_clarification, ~F.text.startswith('/'))
async def process_clarification(message: Message, state: FSMContext):
    clarification = message.text.strip()
    
    # Если это команда - игнорируем
    if clarification.startswith('/'):
        await message.answer("❌ Пожалуйста, введите вопрос для уточнения, а не команду")
        return
    
    if len(clarification) < 5:
        await message.answer(
            "❌ Слишком короткое уточнение. Опишите подробнее:",
            reply_markup=get_manager_cancel_kb()
        )
        return
    
    user_data = await state.get_data()
    request_id = user_data['request_id']
    
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
                await message.answer("❌ Заявка не найдена")
                await state.clear()
                return
            
            request, user = result
            
            # Отправляем уведомление пользователю
            user_message = (
                "✏️ <b>Уточнение по вашей заявке</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"❓ <b>Менеджер уточняет:</b>\n{clarification}\n\n"
                f"💬 <b>Пожалуйста, ответьте на этот вопрос.</b>"
            )
            
            await message.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )
            
            # Обновляем сообщение у менеджера
            await message.answer(
                f"✏️ Запрос на уточнение отправлен клиенту!\n\n"
                f"📋 <b>Заявка:</b> #{request_id}\n"
                f"👤 <b>Клиент:</b> {user.full_name}\n\n"
                f"❓ <b>Ваш вопрос:</b>\n{clarification}",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logging.error(f"Ошибка при отправке уточнения: {e}")
            await message.answer("❌ Ошибка при отправке уточнения")
        finally:
            await state.clear()


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


# Обработчик отмены действия менеджером
@router.callback_query(F.data == "manager_cancel")
async def manager_cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Действие отменено")
    await callback.answer()


# Команда /manager для доступа к панели
@router.message(Command("manager"))
async def cmd_manager(message: Message):
    # Проверяем, является ли пользователь менеджером/админом
    if not await is_manager(message.from_user.id):
        await message.answer("❌ Доступ запрещен. У вас нет прав менеджера.")
        return
    
    await message.answer(
        "👨‍💼 <b>Панель менеджера</b>\n\n"
        "Выберите раздел для управления заявками:",
        parse_mode="HTML",
        reply_markup=get_manager_panel_kb()
    )


# Функция проверки прав менеджера
async def is_manager(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь менеджером"""
    logging.info(f"🔧 Проверка прав для пользователя {telegram_id}")
    
    # Проверяем по ID из конфига
    if str(telegram_id) == config.ADMIN_USER_ID:
        logging.info(f"✅ Пользователь {telegram_id} является администратором")
        return True
    
    # Дополнительная проверка по БД
    async with AsyncSessionLocal() as session:
        try:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            
            # Можно добавить поле is_manager в модель User
            result = user is not None
            logging.info(f"🔧 Результат проверки БД для {telegram_id}: {result}")
            return result
            
        except Exception as e:
            logging.error(f"❌ Ошибка проверки прав в БД: {e}")
            return False


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


# Обработчик просмотра всех заявок
@router.callback_query(F.data == "manager_all_requests")
async def manager_all_requests(callback: CallbackQuery):
    """Показать все заявки"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await show_manager_requests_list(callback, filter_status=None)

@router.callback_query(F.data == "manager_new_requests")
async def manager_new_requests(callback: CallbackQuery):
    """Показать новые заявки"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await show_manager_requests_list(callback, filter_status="new")


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
        "completed": "completed"
    }
    
    status = status_map.get(filter_type)
    await show_manager_requests_list(callback, filter_status=status)


# Функция показа списка заявок для менеджера
async def show_manager_requests_list(callback: CallbackQuery, filter_status: str = None):
    async with AsyncSessionLocal() as session:
        try:
            # Строим запрос с JOIN для подгрузки пользователя и автомобиля
            query = (
                select(Request, User, Car)
                .join(User, Request.user_id == User.id)
                .join(Car, Request.car_id == Car.id)
            )
            
            if filter_status:
                query = query.where(Request.status == filter_status)
            
            query = query.order_by(Request.created_at.desc())
            
            requests_result = await session.execute(query)
            results = requests_result.all()
            
            if not results:
                no_requests_text = {
                    None: "📋 Нет заявок в системе",
                    "new": "🆕 Нет новых заявок",
                    "in_progress": "⏳ Нет заявок в работе", 
                    "completed": "✅ Нет завершенных заявок"
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
            requests_text = "📋 <b>Все заявки</b>\n\n"
            
            status_emojis = {
                "new": "🆕",
                "accepted": "✅", 
                "in_progress": "⏳",
                "rejected": "❌",
                "completed": "🏁"
            }
            
            for i, (request, user, car) in enumerate(results[:10], 1):  # Ограничиваем 10 заявками
                emoji = status_emojis.get(request.status, "📋")
                created_date = request.created_at.strftime("%d.%m.%Y")
                
                requests_text += (
                    f"{emoji} <b>Заявка #{request.id}</b>\n"
                    f"   👤 {user.full_name}\n"
                    f"   📞 {user.phone_number or 'Нет телефона'}\n"
                    f"   🚗 {car.brand} {car.model}\n"
                    f"   🛠️ {request.service_type}\n"
                    f"   📅 {created_date}\n\n"
                )
            
            if len(results) > 10:
                requests_text += f"<i>Показано 10 из {len(results)} заявок</i>\n\n"
            
            # Добавляем информацию о фильтре
            filter_info = {
                None: "📋 Показаны все заявки",
                "new": "🆕 Показаны новые заявки",
                "in_progress": "⏳ Показаны заявки в работе",
                "completed": "✅ Показаны завершенные заявки"
            }
            
            requests_text += f"<i>{filter_info.get(filter_status, '')}</i>"
            
            # Создаем клавиатуру с кнопками для заявок
            builder = InlineKeyboardBuilder()
            for request, user, car in results[:5]:  # Ограничиваем 5 кнопками
                status_emoji = status_emojis.get(request.status, "📋")
                builder.row(
                    InlineKeyboardButton(
                        text=f"{status_emoji} #{request.id} - {user.full_name} - {car.brand}",
                        callback_data=f"manager_view_request:{request.id}"
                    )
                )
            
            builder.row(
                InlineKeyboardButton(text="🆕 Новые", callback_data="manager_new_requests"),
                InlineKeyboardButton(text="⏳ В работе", callback_data="manager_in_progress")
            )
            builder.row(
                InlineKeyboardButton(text="✅ Завершенные", callback_data="manager_completed"),
                InlineKeyboardButton(text="📋 Все", callback_data="manager_all_requests")
            )
            builder.row(
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
            logging.error(f"Ошибка при загрузке заявок для менеджера: {e}")
            await callback.message.answer(
                "❌ Ошибка при загрузке заявок.",
                reply_markup=get_manager_panel_kb()
            )
    
    await callback.answer()


# Обработчик детального просмотра заявки менеджером
@router.callback_query(F.data.startswith("manager_view_request:"))
async def manager_view_request_detail(callback: CallbackQuery):
    """Детальный просмотр заявки с возможностью управления"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    request_id = int(callback.data.split(":")[1])
    await show_manager_request_with_actions(callback, request_id)


async def show_manager_request_with_actions(callback: CallbackQuery, request_id: int):
    """Показ заявки с кнопками управления"""
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
            
            # Добавляем статус
            status_texts = {
                "new": "🆕 Новая",
                "accepted": "✅ Принята",
                "in_progress": "⏳ В работе", 
                "rejected": "❌ Отклонена",
                "completed": "🏁 Завершена"
            }
            
            detail_text += f"📊 <b>Статус:</b> {status_texts.get(request.status, request.status)}\n"
            detail_text += f"⏰ <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            # Если есть фото
            if request.photo_file_id:
                detail_text += f"📷 <b>Фото:</b> Прикреплено\n"
            
            # Создаем клавиатуру управления
            from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
            
            builder = InlineKeyboardBuilder()
            
            if request.status == 'new':
                builder.row(
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"manager_accept:{request.id}"),
                    InlineKeyboardButton(text="✏️ Уточнить", callback_data=f"manager_clarify:{request.id}")
                )
                builder.row(
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"manager_reject:{request.id}"),
                    InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request.id}")
                )
            elif request.status == 'accepted':
                builder.row(
                    InlineKeyboardButton(text="⏳ В работу", callback_data=f"manager_set_in_progress:{request.id}"),
                    InlineKeyboardButton(text="✏️ Комментарий", callback_data=f"manager_add_comment:{request.id}")
                )
            elif request.status == 'in_progress':
                builder.row(
                    InlineKeyboardButton(text="✅ Завершить", callback_data=f"manager_set_completed:{request.id}"),
                    InlineKeyboardButton(text="✏️ Комментарий", callback_data=f"manager_add_comment:{request.id}")
                )
            
            # Общие кнопки
            builder.row(
                InlineKeyboardButton(text="📞 Позвонить", callback_data=f"manager_call:{request.id}"),
                InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="manager_all_requests")
            )
            
            # Отправляем сообщение
            if request.photo_file_id:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=request.photo_file_id,
                    caption=detail_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            else:
                await callback.message.delete()
                await callback.message.answer(
                    detail_text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup()
                )
            
        except Exception as e:
            logging.error(f"Ошибка при загрузке деталей заявки: {e}")
            await callback.answer("❌ Ошибка при загрузке заявки")
    
    await callback.answer()


# Функция показа деталей заявки для менеджера
async def show_manager_request_detail(callback: CallbackQuery, request_id: int):
    async with AsyncSessionLocal() as session:
        try:
            # Получаем все ID заявок для навигации
            requests_ids_result = await session.execute(
                select(Request.id).order_by(Request.created_at.desc())
            )
            requests_ids = [row[0] for row in requests_ids_result.all()]
            
            if not requests_ids:
                await callback.answer("❌ Заявки не найдены")
                return
            
            # Находим текущий индекс
            current_index = requests_ids.index(request_id) if request_id in requests_ids else 0
            
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
            detail_text = (
                f"📋 <b>Заявка #{request.id}</b> ({current_index + 1}/{len(requests_ids)})\n\n"
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
            
            # Добавляем статус с историей
            status_texts = {
                "new": "🆕 Новая",
                "accepted": "✅ Принята",
                "in_progress": "⏳ В работе", 
                "rejected": "❌ Отклонена",
                "completed": "🏁 Завершена"
            }
            
            detail_text += f"📊 <b>Статус:</b> {status_texts.get(request.status, request.status)}\n"
            detail_text += f"⏰ <b>Создана:</b> {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            # Если есть фото
            if request.photo_file_id:
                detail_text += f"📷 <b>Фото:</b> Прикреплено\n"
            
            # Отправляем новое сообщение вместо редактирования
            if request.photo_file_id:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=request.photo_file_id,
                    caption=detail_text,
                    parse_mode="HTML",
                    reply_markup=get_manager_requests_navigation_kb(requests_ids, current_index)
                )
            else:
                await callback.message.delete()
                await callback.message.answer(
                    detail_text,
                    parse_mode="HTML",
                    reply_markup=get_manager_requests_navigation_kb(requests_ids, current_index)
                )
            
        except Exception as e:
            logging.error(f"Ошибка при загрузке деталей заявки для менеджера: {e}")
            await callback.answer("❌ Ошибка при загрузке заявки")
    
    await callback.answer()


# Обработчик установки статуса "В работе"
@router.callback_query(F.data.startswith("manager_set_in_progress:"))
async def manager_set_in_progress(callback: CallbackQuery):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    request_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        try:
            # Обновляем статус заявки
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
            
            # Обновляем статус
            request.status = 'in_progress'
            await session.commit()
            
            # Уведомляем пользователя
            user_message = (
                "⏳ <b>Ваша заявка переведена в работу!</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"🔧 <b>Мастер приступил к работе над вашей заявкой.</b>\n"
                f"Мы свяжемся с вами для уточнения деталей."
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )
            
            # Обновляем сообщение у менеджера
            await callback.message.edit_text(
                f"⏳ Заявка #{request_id} переведена в работу!\n\n"
                f"📞 Уведомление отправлено клиенту.",
                reply_markup=get_manager_request_detail_kb(request_id)
            )
            
            await callback.answer("✅ Заявка переведена в работу")
            
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при изменении статуса заявки: {e}")
            await callback.answer("❌ Ошибка при изменении статуса")


# Обработчик установки статуса "Завершена"
@router.callback_query(F.data.startswith("manager_set_completed:"))
async def manager_set_completed(callback: CallbackQuery):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    request_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        try:
            # Обновляем статус заявки
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
            
            # Обновляем статус
            request.status = 'completed'
            await session.commit()
            
            # Уведомляем пользователя
            user_message = (
                "🏁 <b>Ваша заявка завершена!</b>\n\n"
                f"📋 <b>Номер заявки:</b> #{request.id}\n"
                f"🛠️ <b>Услуга:</b> {request.service_type}\n\n"
                f"✅ <b>Работа по вашей заявке успешно завершена.</b>\n"
                f"Благодарим за обращение!"
            )
            
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=user_message,
                parse_mode="HTML"
            )
            
            # Отправляем новое сообщение вместо редактирования
            await callback.message.answer(
                f"🏁 Заявка #{request_id} завершена!\n\n"
                f"✅ Уведомление отправлено клиенту."
            )
            
            await callback.answer("✅ Заявка завершена")
            
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при завершении заявки: {e}")
            await callback.answer("❌ Ошибка при завершении заявки")


# Обработчик добавления комментария
@router.callback_query(F.data.startswith("manager_add_comment:"))
async def manager_add_comment(callback: CallbackQuery, state: FSMContext):
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    # Используем безопасную функцию
    await safe_manager_reply(
        callback,
        f"✏️ <b>Добавление комментария к заявке #{request_id}</b>\n\n"
        "Введите комментарий для внутреннего использования:\n\n"
        "<i>Этот комментарий виден только менеджерам и не отправляется клиенту.</i>",
        get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_comment)


# Обработчик ввода комментария
@router.message(ManagerForm.waiting_for_comment)
async def process_manager_comment(message: Message, state: FSMContext):
    comment = message.text.strip()
    
    if len(comment) < 5:
        await message.answer(
            "❌ Комментарий слишком короткий. Введите комментарий подробнее:",
            reply_markup=get_manager_cancel_kb()
        )
        return
    
    user_data = await state.get_data()
    request_id = user_data['request_id']
    
    async with AsyncSessionLocal() as session:
        try:
            # Получаем заявку
            request_result = await session.execute(
                select(Request).where(Request.id == request_id)
            )
            request = request_result.scalar_one_or_none()
            
            if not request:
                await message.answer("❌ Заявка не найдена")
                await state.clear()
                return
            
            # Сохраняем комментарий
            request.manager_comment = comment
            await session.commit()
            
            await message.answer(
                f"✅ Комментарий к заявке #{request_id} сохранен!\n\n"
                f"📝 <b>Комментарий:</b>\n{comment}",
                parse_mode="HTML",
                reply_markup=get_manager_panel_kb()
            )
            
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при сохранении комментария: {e}")
            await message.answer("❌ Ошибка при сохранении комментария")
        finally:
            await state.clear()


# Обработчик для случаев когда заявка не найдена
@router.callback_query(F.data.startswith("manager_"))
async def handle_manager_actions(callback: CallbackQuery):
    """Общий обработчик для действий менеджера"""
    try:
        # Проверяем права
        if not await is_manager(callback.from_user.id):
            await callback.answer("❌ Доступ запрещен")
            return
            
        # Если callback содержит ID заявки, проверяем её существование
        if ":" in callback.data:
            request_id = int(callback.data.split(":")[1])
            async with AsyncSessionLocal() as session:
                request_result = await session.execute(
                    select(Request).where(Request.id == request_id)
                )
                request = request_result.scalar_one_or_none()
                
                if not request:
                    await callback.answer("❌ Заявка не найдена")
                    await callback.message.edit_text(
                        f"❌ Заявка #{request_id} не найдена",
                        reply_markup=get_manager_panel_kb()
                    )
                    return
                    
    except Exception as e:
        logging.error(f"Ошибка в обработчике менеджера: {e}")
        await callback.answer("❌ Произошла ошибка")


# Обработчик callback'ов из групп
@router.callback_query(F.data.startswith("manager_"))
async def handle_group_callbacks(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback'ов из групп"""
    try:
        logging.info(f"🔔 Callback из группы: {callback.data} от пользователя {callback.from_user.id}")
        
        # Проверяем права пользователя
        if not await is_manager(callback.from_user.id):
            await callback.answer("❌ У вас нет прав для управления заявками", show_alert=True)
            return
        
        # Обрабатываем разные типы callback'ов
        if callback.data.startswith("manager_accept:"):
            await manager_accept_request(callback, state)
            
        elif callback.data.startswith("manager_clarify:"):
            await manager_clarify_request(callback, state)
            
        elif callback.data.startswith("manager_reject:"):
            await manager_reject_request(callback, state)
            
        elif callback.data.startswith("manager_call:"):
            request_id = int(callback.data.split(":")[1])
            await manager_call_client(callback)
            
        elif callback.data.startswith("manager_set_in_progress:"):
            request_id = int(callback.data.split(":")[1])
            await manager_set_in_progress(callback)
            
        elif callback.data.startswith("manager_set_completed:"):
            request_id = int(callback.data.split(":")[1])
            await manager_set_completed(callback)
            
        else:
            await callback.answer("⚠️ Действие не распознано")
            
    except Exception as e:
        logging.error(f"❌ Ошибка обработки callback из группы: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

#  Команда проверки прав
@router.message(Command("check_rights"))
async def cmd_check_rights(message: Message):
    """Проверка прав пользователя"""
    user_id = message.from_user.id
    is_manager_user = await is_manager(user_id)
    
    if is_manager_user:
        await message.answer(f"✅ Вы менеджер! ID: {user_id}")
    else:
        await message.answer(f"❌ Вы не менеджер. ID: {user_id}")


async def safe_manager_reply(callback: CallbackQuery, text: str, reply_markup=None):
    """Безопасный ответ менеджеру (работает и в группах и в личных сообщениях)"""
    try:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка при ответе менеджеру: {e}")
        # Пробуем отправить в личные сообщения как запасной вариант
        try:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            await callback.answer()
        except Exception as pm_error:
            logging.error(f"Не удалось отправить даже в личные сообщения: {pm_error}")

@router.callback_query(F.data == "manager_in_progress")
async def manager_in_progress_requests(callback: CallbackQuery):
    """Показать заявки в работе"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await show_manager_requests_list(callback, filter_status="in_progress")

@router.callback_query(F.data == "manager_completed")
async def manager_completed_requests(callback: CallbackQuery):
    """Показать завершенные заявки"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await show_manager_requests_list(callback, filter_status="completed")

# Обработчик команд во время состояний FSM
@router.message(StateFilter(ManagerForm.waiting_for_price, ManagerForm.waiting_for_deadline, 
                           ManagerForm.waiting_for_clarification, ManagerForm.waiting_for_reject_reason))
async def handle_commands_during_fsm(message: Message, state: FSMContext):
    """Обрабатывает команды во время FSM состояний"""
    if message.text.startswith('/'):
        await message.answer(
            "⚠️ <b>Сначала завершите текущее действие!</b>\n\n"
            "Завершите ввод данных или нажмите кнопку 'Отменить'",
            parse_mode="HTML"
        )

@router.callback_query(F.data == "manager_rejected")
async def manager_rejected_requests(callback: CallbackQuery):
    """Показать отклоненные заявки"""
    if not await is_manager(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return
    
    await show_manager_requests_list(callback, filter_status="rejected")