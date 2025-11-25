from sqlalchemy import (
    Column,
    Integer,
    String,
    BigInteger,
    Text,
    DateTime,
    ForeignKey,
    Float,
    Boolean,
)
from sqlalchemy.sql import func

from app.database.base import Base


class ServiceCenter(Base):
    __tablename__ = "service_centers"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    address = Column(String(255))
    phone = Column(String(20))

    # новые важные поля
    specializations = Column(Text)
    category_code = Column(String(50))

    owner_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    location_lat = Column(Float)   # широта сервиса
    location_lon = Column(Float)   # долгота сервиса

    send_to_owner = Column(Boolean, default=True)
    manager_chat_id = Column(BigInteger, nullable=True)
    send_to_group = Column(Boolean, default=False)

    rating = Column(Float, default=0.0)
    ratings_count = Column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    phone_number = Column(String(20))
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
    points = Column(Integer, nullable=False, default=0)
    role = Column(String(20), nullable=False, default="client")

    # ✅ Дополнительные поля для автосервиса
    service_name = Column(String(200))   # Название сервиса
    service_address = Column(String(255))  # Адрес сервиса


class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    brand = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer)
    license_plate = Column(String(20))
    # ✅ VIN — часть карточки автомобиля
    vin = Column(String(50))


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    car_id = Column(
        Integer, ForeignKey("cars.id", ondelete="CASCADE"), nullable=False
    )

    # 🔗 Привязка к автосервису (СТО)
    service_center_id = Column(
        Integer,
        ForeignKey("service_centers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Человекочитаемый тип работ (то, что видит пользователь/менеджер)
    service_type = Column(String(50), nullable=False)
    category_code = Column(String(50))

    description = Column(Text)
    photo_file_id = Column(String(255))

    # ✅ Текущее местоположение
    location_lat = Column(Float)
    location_lon = Column(Float)
    location_description = Column(Text)

    # ✅ Может ли авто ехать своим ходом
    can_drive = Column(Boolean, default=True)

    # Желаемые сроки выполнения (как и было)
    preferred_date = Column(String(100))

    status = Column(String(50), default="new")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    manager_comment = Column(Text)
    chat_message_id = Column(Integer)
    accepted_at = Column(DateTime(timezone=True))
    in_progress_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    rejected_at = Column(DateTime(timezone=True))
