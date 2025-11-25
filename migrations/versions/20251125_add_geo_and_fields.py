"""add geo/spec fields for service centers and requests

Revision ID: 20251125_add_geo_and_fields
Revises: 7d2306a70e6a
Create Date: 2025-11-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# Идентификаторы миграции
revision = "20251125_add_geo_and_fields"
down_revision = "7d2306a70e6a"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table_name: str, column: sa.Column) -> None:
    """
    Универсальный помощник: добавляет колонку, только если её ещё нет.
    Работает и для SQLite, и для Postgres.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table_name)]

    if column.name not in cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    # ---- SERVICE CENTERS ----
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("specializations", sa.Text(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("category_code", sa.String(length=50), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("location_lat", sa.Float(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("location_lon", sa.Float(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("send_to_owner", sa.Boolean(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("manager_chat_id", sa.BigInteger(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("send_to_group", sa.Boolean(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("rating", sa.Float(), nullable=True),
    )
    _add_column_if_not_exists(
        "service_centers",
        sa.Column("ratings_count", sa.Integer(), nullable=True),
    )

    # ---- REQUESTS ----
    _add_column_if_not_exists(
        "requests",
        sa.Column("category_code", sa.String(length=50), nullable=True),
    )
    _add_column_if_not_exists(
        "requests",
        sa.Column("location_lat", sa.Float(), nullable=True),
    )
    _add_column_if_not_exists(
        "requests",
        sa.Column("location_lon", sa.Float(), nullable=True),
    )
    _add_column_if_not_exists(
        "requests",
        sa.Column("location_description", sa.Text(), nullable=True),
    )
    _add_column_if_not_exists(
        "requests",
        sa.Column("can_drive", sa.Boolean(), nullable=True),
    )
    _add_column_if_not_exists(
        "requests",
        sa.Column("preferred_date", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    # Здесь можно оставить как есть (drop_column),
    # т.к. downgrade ты почти точно делать не будешь.
    op.drop_column("requests", "preferred_date")
    op.drop_column("requests", "can_drive")
    op.drop_column("requests", "location_description")
    op.drop_column("requests", "location_lon")
    op.drop_column("requests", "location_lat")
    op.drop_column("requests", "category_code")

    op.drop_column("service_centers", "ratings_count")
    op.drop_column("service_centers", "rating")
    op.drop_column("service_centers", "send_to_group")
    op.drop_column("service_centers", "manager_chat_id")
    op.drop_column("service_centers", "send_to_owner")
    op.drop_column("service_centers", "location_lon")
    op.drop_column("service_centers", "location_lat")
    op.drop_column("service_centers", "owner_user_id")
    op.drop_column("service_centers", "category_code")
    op.drop_column("service_centers", "specializations")
