from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database.models import User, Car, Request
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import get_manager_request_kb, get_manager_cancel_kb
from app.config import config

router = Router()


class ManagerForm(StatesGroup):
    waiting_for_price = State()
    waiting_for_deadline = State()
    waiting_for_clarification = State()
    waiting_for_reject_reason = State()


# Функция для отправки уведомления о новой заявке менеджеру
async def notify_manager_about_new_request(bot: Bot, request_id: int):
    if not config.MANAGER_CHAT_ID:
        logging.warning("MANAGER_CHAT_ID не установлен - уведомление не отправлено")
        return
    
    session = SessionLocal()
    
    try:
        # Получаем данные заявки
        request_result = session.execute(
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
    finally:
        session.close()


# Обработчик принятия заявки менеджером
@router.callback_query(F.data.startswith("manager_accept:"))
async def manager_accept_request(callback: CallbackQuery, state: FSMContext):
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    await callback.message.edit_text(
        f"✅ Принятие заявки #{request_id}\n\n"
        "Введите ориентировочную стоимость услуги:\n\n"
        "<i>Пример: 5000 руб, 15000 руб, бесплатно по гарантии</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_price)
    await callback.answer()


# Обработчик ввода цены
@router.message(ManagerForm.waiting_for_price)
async def process_manager_price(message: Message, state: FSMContext, bot: Bot):
    price = message.text.strip()
    
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


# Обработчик ввода сроков
@router.message(ManagerForm.waiting_for_deadline)
async def process_manager_deadline(message: Message, state: FSMContext, bot: Bot):
    deadline = message.text.strip()
    
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
                
                await bot.send_message(
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
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    await callback.message.edit_text(
        f"❌ Отклонение заявки #{request_id}\n\n"
        "Укажите причину отклонения:\n\n"
        "<i>Пример: Нет запчастей, не обслуживаем эту марку, несоответствие требованиям</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_reject_reason)
    await callback.answer()


# Обработчик ввода причины отклонения
@router.message(ManagerForm.waiting_for_reject_reason)
async def process_reject_reason(message: Message, state: FSMContext, bot: Bot):
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
                
                await bot.send_message(
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
    request_id = int(callback.data.split(":")[1])
    
    await state.update_data(request_id=request_id)
    
    await callback.message.edit_text(
        f"✏️ Уточнение заявки #{request_id}\n\n"
        "Что нужно уточнить у клиента?\n\n"
        "<i>Пример: Уточните VIN код, В какое время вам удобно, Какой именно звук издает двигатель?</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_clarification)
    await callback.answer()


# Обработчик ввода уточнения
@router.message(ManagerForm.waiting_for_clarification)
async def process_clarification(message: Message, state: FSMContext, bot: Bot):
    clarification = message.text.strip()
    
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
            
            await bot.send_message(
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
