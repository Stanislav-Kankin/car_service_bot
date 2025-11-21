import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from app.config import config


router = Router()


def is_manager(user_id: int) -> bool:
    return user_id == config.ADMIN_USER_ID


# ───────────────────────────────────────────────
# 📌 MANAGER: Открытие заявки в ЛС (кнопка "Назад" из просмотра заявки)
# ───────────────────────────────────────────────
@router.callback_query(F.data.startswith("manager_view_request"))
async def manager_view_request(callback: CallbackQuery):
    """
    Открывает детальный просмотр заявки в личке менеджера.
    Логика простая — показывает информационное сообщение.
    """
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, raw_id = callback.data.split(":")
        request_id = int(raw_id)
    except:
        await callback.answer("Ошибка ID", show_alert=True)
        return

    logging.info(f"🔧 Manager callback: manager_view_request:{request_id}")

    # Отправляем подсказку
    await callback.message.answer(
        f"📋 Заявка #{request_id}\n"
        f"Чтобы оставить комментарий, перейдите в группу менеджеров и ответьте реплаем.",
    )

    await callback.answer()


# # ───────────────────────────────────────────────
# # 📌 MANAGER: КОММЕНТАРИЙ (в группе через reply)
# # ───────────────────────────────────────────────
# @router.message()
# async def manager_reply_handler(message: Message):
#     """
#     Только для reply в группе — передаём в comment_service.
#     """
#     if message.chat.id != config.MANAGER_CHAT_ID:
#         return

#     if not is_manager(message.from_user.id):
#         return

#     if not message.reply_to_message:
#         return

#     # Обрабатываем как менеджерский комментарий / предложение
#     await handle_manager_comment_reply(message)


# ───────────────────────────────────────────────
# 📌 MANAGER: После подтверждения клиентом включить кнопки
# ───────────────────────────────────────────────
@router.callback_query(F.data.startswith("manager_enable_after_accept"))
async def manager_enable_after_accept(callback: CallbackQuery):
    """
    Активирует кнопки статусов после того, как клиент подтвердил условия.
    Фактически менеджеру ничего жать НЕ надо — система сама вызовет
    update_chat_keyboard().
    """
    if not is_manager(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        _, raw_id = callback.data.split(":")
        request_id = int(raw_id)
    except:
        await callback.answer("Ошибка ID", show_alert=True)
        return

    logging.info(f"🔧 manager_enable_after_accept для заявки #{request_id}")

    try:
        await reopen_manager_actions_after_user_accept(callback.bot, request_id)
        await callback.answer("Кнопки включены ✔")
    except Exception as e:
        logging.error(f"❌ Ошибка включения кнопок #{request_id}: {e}")
        await callback.answer("Ошибка", show_alert=True)
