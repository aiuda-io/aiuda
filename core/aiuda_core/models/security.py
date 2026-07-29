"""Credenciales cifradas y auditoría del runtime local.

- Credenciales de conectores CIFRADAS en reposo (IntegrationCredential): la
  llave de cifrado vive en el keychain del sistema, no junto a los datos.
- Bitácora append-only (AuditLog) para demostrar quién aprobó qué (soberanía
  humana y trazabilidad).

No incluye identidad ni monetización. Un modo remoto futuro tendrá su propio
diseño.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiuda_core.models.base import Base, TenantMixin, TimestampMixin, new_id


# --------------------------------------------------------------------------- #
# Credenciales de conectores, CIFRADAS en reposo                               #
# --------------------------------------------------------------------------- #
class IntegrationCredential(Base, TenantMixin, TimestampMixin):
    """Credenciales de un conector, cifradas. El motor (sync_fuentes) debe leer
    de aquí, nunca de settings.* globales. Nada se guarda en claro y nada se
    devuelve por la API."""

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_intcred_tenant_provider"),
        CheckConstraint(
            "status in ('configured','connected','error','disabled')",
            name="ck_intcred_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # odoo | shopify | woocommerce | belvo | stripe | hubspot | facturama | ...
    provider: Mapped[str] = mapped_column(String(32))
    # Secreto cifrado (envelope encryption, ver aiuda_core.security.crypto).
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    # Versión de la clave de cifrado, para rotación sin re-cifrar todo de golpe.
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    # Config NO secreta (url base, instancia, opciones). Puede devolverse a la UI.
    public_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # configured | connected | error | disabled — "Conectado" verificable.
    status: Mapped[str] = mapped_column(String(16), default="configured")
    last_test_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------- #
# Auditoría append-only: quién hizo qué (soberanía humana demostrable)         #
# --------------------------------------------------------------------------- #
class AuditLog(Base, TenantMixin, TimestampMixin):
    """Bitácora inmutable. Se escribe una fila en cada aprobación, rechazo,
    edición y write-back. Sin esto no se puede demostrar quién autorizó un cobro,
    que es el principio fundacional del producto."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Nulo si el actor fue el sistema (un job automático). En local no hay tabla
    # de usuarios; se conserva la columna para el modo multi-usuario futuro.
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )
    # reminder.approve | payment.reconcile | writeback.send | integration.update | ...
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))  # reminder | payment | ...
    entity_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
