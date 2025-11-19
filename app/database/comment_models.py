from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database.base import Base


class Comment(Base):
    __tablename__ = 'comments'

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('requests.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    message = Column(Text, nullable=False)
    is_manager = Column(Boolean, default=False)  # True - менеджер, False - клиент
    created_at = Column(DateTime(timezone=True), server_default=func.now())