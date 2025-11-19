import logging
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Request, User, Car
from app.database.db import AsyncSessionLocal
from app.keyboards.main_kb import get_manager_request_kb
from app.config import config


async def notify_manager_about_new_request(bot: Bot, request_id: int):
    """Создает чат для новой заявки"""
    from app.services.chat_service import create_request_chat
    await create_request_chat(bot, request_id)