from sqlalchemy import (
    Column, Integer, String,
    BigInteger, Text, DateTime, ForeignKey
)
from sqlalchemy.sql import func
from app.database.base import Base  # ← Импортируем из base.py


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    phone_number = Column(String(20))
    registered_at = Column(DateTime(timezone=True), server_default=func.now())


class Car(Base):
    __tablename__ = 'cars'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer)
    license_plate = Column(String(20))


class Request(Base):
    __tablename__ = 'requests'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    car_id = Column(Integer, ForeignKey('cars.id', ondelete='CASCADE'), nullable=False)
    service_type = Column(String(50), nullable=False)
    description = Column(Text)
    photo_file_id = Column(String(255))
    preferred_date = Column(String(100))
    status = Column(String(50), default='new')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    manager_comment = Column(Text)
    chat_message_id = Column(Integer)
    accepted_at = Column(DateTime(timezone=True))
    in_progress_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    rejected_at = Column(DateTime(timezone=True))