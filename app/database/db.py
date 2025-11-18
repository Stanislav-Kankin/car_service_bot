from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from app.config import config

# Для SQLite используем синхронный движок
engine = create_engine(config.DB_URL, echo=True)
SessionLocal = sessionmaker(bind=engine)


def create_tables():
    """Синхронное создание таблиц"""
    Base.metadata.create_all(bind=engine)
