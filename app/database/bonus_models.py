from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database.base import Base


class BonusTransaction(Base):
    """
    История бонусных начислений пользователю.
    """
    __tablename__ = "bonus_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Тип действия: register / new_request / accept_offer / complete_request / ...
    action = Column(String(50), nullable=False)

    # Сколько баллов начислено
    amount = Column(Integer, nullable=False)

    # Человекочитаемое пояснение (опционально)
    description = Column(Text)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
