"""Bitácora append-only: quién hizo qué. El AuditLog existía pero NUNCA se escribía
—justo el diferenciador fundacional ("demostrar quién autorizó un cobro"). Aquí se
escribe una fila en cada acción soberana (aprobar, conciliar, revocar, recapturar
credenciales) y se expone para leerla.

`record` falla SILENCIOSO si algo sale mal: la bitácora no debe tumbar la acción de
negocio (mejor perder una fila de auditoría que rechazar una aprobación legítima).
"""

from __future__ import annotations

from sqlalchemy import desc, select

from aiuda_core.models import AuditLog


def record(
    db,
    *,
    tenant_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    principal=None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    """Escribe una fila de auditoría. El actor sale del Principal; el email y el
    aparato se conservan en ``after`` porque local-first no tiene tabla de usuarios."""
    actor_user_id = getattr(getattr(principal, "user", None), "id", None)
    payload_after = dict(after or {})
    email = getattr(principal, "email", None)
    if email and "actor_email" not in payload_after:
        payload_after["actor_email"] = email
    # De qué aparato salió. Sin esto, lo que aprueba el teléfono de alguien del
    # equipo queda firmado como si lo hubiera hecho el dueño en su computadora, y
    # esta bitácora existe precisamente para poder demostrar quién autorizó qué.
    aparato_id = getattr(principal, "dispositivo_id", None)
    if aparato_id:
        payload_after.setdefault("actor_aparato_id", aparato_id)
        payload_after.setdefault("actor_aparato", getattr(principal, "quien", None))
    try:
        # SAVEPOINT: si la fila de auditoría falla (p.ej. FK), se revierte SOLO el
        # savepoint y la transacción de negocio sigue intacta.
        with db.begin_nested():
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    before=before,
                    after=payload_after or None,
                    ip=ip,
                )
            )
    except Exception:
        pass  # la bitácora nunca tumba la acción de negocio


def recent(db, tenant_id: str, limit: int = 100) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        ).all()
    )
