from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
import logging

from app.database.db import AsyncSessionLocal
from app.database.models import Request, User
from app.keyboards.main_kb import get_manager_cancel_kb
from app.handlers.manager_handlers import is_manager, ManagerForm

router = Router()

# Обработчик callback'ов из групп
@router.callback_query(F.data.startswith("manager_"))
async def handle_group_callbacks(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback'ов из групп"""
    try:
        logging.info(f"🔔 Callback из группы получен!")
        logging.info(f"🔔 Данные: {callback.data}")
        logging.info(f"🔔 Пользователь: {callback.from_user.id}")
        logging.info(f"🔔 Чат: {callback.message.chat.id}")
        
        # Проверяем права пользователя
        is_manager_user = await is_manager(callback.from_user.id)
        logging.info(f"🔔 Результат проверки прав: {is_manager_user}")
        
        if not is_manager_user:
            await callback.answer("❌ У вас нет прав для управления заявками", show_alert=True)
            return
        
        # Обрабатываем разные типы callback'ов
        if callback.data.startswith("manager_accept:"):
            request_id = int(callback.data.split(":")[1])
            logging.info(f"🔔 Обработка принятия заявки #{request_id}")
            await process_manager_accept(callback, state, request_id)
            
        elif callback.data.startswith("manager_clarify:"):
            request_id = int(callback.data.split(":")[1])
            logging.info(f"🔔 Обработка уточнения заявки #{request_id}")
            await process_manager_clarify(callback, state, request_id)
            
        elif callback.data.startswith("manager_reject:"):
            request_id = int(callback.data.split(":")[1])
            logging.info(f"🔔 Обработка отклонения заявки #{request_id}")
            await process_manager_reject(callback, state, request_id)
            
        elif callback.data.startswith("manager_call:"):
            request_id = int(callback.data.split(":")[1])
            logging.info(f"🔔 Обработка звонка заявки #{request_id}")
            await process_manager_call(callback, request_id)
            
        else:
            logging.warning(f"🔔 Неизвестный callback: {callback.data}")
            await callback.answer("⚠️ Действие не распознано")
            
    except Exception as e:
        logging.error(f"❌ Ошибка обработки callback из группы: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

async def process_manager_accept(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Обработка принятия заявки из группы"""
    try:
        logging.info(f"🔔 Начало process_manager_accept для заявки #{request_id}")
        
        await state.update_data(request_id=request_id)
        
        logging.info(f"🔔 Состояние установлено, отправка сообщения...")
        
        await callback.message.answer(
            f"✅ Принятие заявки #{request_id}\n\n"
            "Введите ориентировочную стоимость услуги:\n\n"
            "<i>Пример: 5000 руб, 15000 руб, бесплатно по гарантии</i>",
            parse_mode="HTML",
            reply_markup=get_manager_cancel_kb()
        )
        await state.set_state(ManagerForm.waiting_for_price)
        await callback.answer("✅ Введите стоимость")
        
        logging.info(f"🔔 Сообщение отправлено, состояние: {await state.get_state()}")
        
    except Exception as e:
        logging.error(f"❌ Ошибка в process_manager_accept: {e}")
        await callback.answer("❌ Ошибка при обработке")

async def process_manager_clarify(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Обработка уточнения заявки из группы"""
    await state.update_data(request_id=request_id)
    
    await callback.message.answer(
        f"✏️ Уточнение заявки #{request_id}\n\n"
        "Что нужно уточнить у клиента?\n\n"
        "<i>Пример: Уточните VIN код, В какое время вам удобно, Какой именно звук издает двигатель?</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_clarification)
    await callback.answer()

async def process_manager_reject(callback: CallbackQuery, state: FSMContext, request_id: int):
    """Обработка отклонения заявки из группы"""
    await state.update_data(request_id=request_id)
    
    await callback.message.answer(
        f"❌ Отклонение заявки #{request_id}\n\n"
        "Укажите причину отклонения:\n\n"
        "<i>Пример: Нет запчастей, не обслуживаем эту марку, несоответствие требованиям</i>",
        parse_mode="HTML",
        reply_markup=get_manager_cancel_kb()
    )
    await state.set_state(ManagerForm.waiting_for_reject_reason)
    await callback.answer()

async def process_manager_call(callback: CallbackQuery, request_id: int):
    """Обработка кнопки звонка из группы"""
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