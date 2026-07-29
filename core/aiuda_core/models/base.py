import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenantMixin:
    """Toda tabla de negocio lleva tenant_id. Ninguna query sin filtrar por él."""

    tenant_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # updated_at se actualiza en cada cambio. Necesario para auditoría temporal y
    # para sync incremental con los sistemas fuente (Odoo, tienda, etc.).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
