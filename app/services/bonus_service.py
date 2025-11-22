import logging
from typing import Optional, Tuple, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.database.db import AsyncSessionLocal
from app.database.models import User
from app.database.bonus_models import BonusTransaction


# Карта действий → сколько баллов начислять
BONUS_ACTION_MAP: dict[str, int] = {
    "register": config.BONUS_REGISTER,
    "new_request": config.BONUS_NEW_REQUEST,
    "accept_offer": config.BONUS_ACCEPT_OFFER,
    "complete_request": config.BONUS_COMPLETE_REQUEST,
    "rate_service": config.BONUS_RATE_SERVICE,
}


async def _get_user_by_telegram(session: AsyncSession, telegram_id: int) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def add_bonus(telegram_id: int, action: str, description: Optional[str] = None) -> bool:
    """
    Начисляет бонусы пользователю по его telegram_id за определённое действие.

    :param telegram_id: Telegram ID пользователя
    :param action: ключ действия (register / new_request / accept_offer / complete_request)
    :param description: произвольное пояснение для истории
    :return: True, если начисление прошло успешно
    """
    amount = BONUS_ACTION_MAP.get(action)

    # Если для действия не задано количество баллов – ничего не делаем
    if not amount or amount <= 0:
        logging.info(f"[bonus] Для действия {action!r} не настроено начисление, пропускаю")
        return False

    async with AsyncSessionLocal() as session:
        try:
            user = await _get_user_by_telegram(session, telegram_id)
            if not user:
                logging.warning(f"[bonus] Пользователь с telegram_id={telegram_id} не найден, бонус не начислён")
                return False

            # Обновляем баланс
            current_points = user.points or 0
            user.points = current_points + amount

            # Пишем в историю
            tx = BonusTransaction(
                user_id=user.id,
                action=action,
                amount=amount,
                description=description,
            )
            session.add(tx)

            await session.commit()
            logging.info(
                f"[bonus] Начислено {amount} баллов пользователю {telegram_id} (action={action}), "
                f"новый баланс={user.points}"
            )
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"❌ Ошибка начисления бонусов (telegram_id={telegram_id}, action={action}): {e}")
            return False


async def get_user_balance(
    telegram_id: int,
    limit_history: int = 10,
) -> Tuple[Optional[int], List[BonusTransaction]]:
    """
    Возвращает текущий баланс и последние операции по бонусам.

    :param telegram_id: Telegram ID пользователя
    :param limit_history: сколько последних операций отдавать
    :return: (баланс или None, список операций)
    """
    async with AsyncSessionLocal() as session:
        try:
            user = await _get_user_by_telegram(session, telegram_id)
            if not user:
                return None, []

            balance = user.points or 0

            result = await session.execute(
                select(BonusTransaction)
                .where(BonusTransaction.user_id == user.id)
                .order_by(BonusTransaction.created_at.desc())
                .limit(limit_history)
            )
            history = result.scalars().all()
            return balance, history
        except Exception as e:
            logging.error(f"❌ Ошибка получения баланса бонусов (telegram_id={telegram_id}): {e}")
            return None, []
