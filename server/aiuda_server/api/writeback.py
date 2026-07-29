"""Write-back: estado de las inyecciones a la fuente y reintento manual.

La ficha (factura / cliente) muestra aquí si lo confirmado en aiuda ya quedó
escrito de regreso en el sistema de origen — pendiente / inyectada / falló —
con su evidencia (qué se escribió, qué respondió la fuente, cuándo), y permite
reintentar una fallida.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import Principal, get_db, get_principal, get_tenant
from aiuda_core.engine.writeback import reset_for_retry
from aiuda_core.models import OutboxEntry, Tenant

router = APIRouter()

# Estados de la cola (pending/done/failed) con el nombre que ve el dueño.
ESTADO = {"pending": "pendiente", "done": "inyectada", "failed": "falló"}


def _entry_json(e: OutboxEntry) -> dict:
    payload = e.payload or {}
    # El destino con el nombre que ve el dueño: una conexión a la medida se llama
    # como él la nombró (payload.conexion.pkey), no "custom".
    target_label = ((payload.get("conexion") or {}).get("pkey")) if e.target == "custom" else None
    return {
        "id": e.id,
        "target": e.target,
        "target_label": target_label or e.target,
        "action": e.action,
        "estado": ESTADO.get(e.status, e.status),
        "attempts": e.attempts,
        "last_error": e.last_error,
        "folio": payload.get("folio"),
        "amount": payload.get("amount"),
        "changes": payload.get("changes"),
        "evidencia": payload.get("evidencia"),
        "reintento_en": payload.get("reintento_en"),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "done_at": e.done_at.isoformat() if e.done_at else None,
    }


@router.get("/v1/writeback")
def list_writeback(
    invoice_id: str | None = None,
    customer_id: str | None = None,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Inyecciones del tenant, filtrables por el registro donde vive el dato
    (la ficha de factura pide por invoice_id; la de cliente, por customer_id)."""
    entries = db.scalars(
        select(OutboxEntry)
        .where(OutboxEntry.tenant_id == tenant.id)
        .order_by(OutboxEntry.created_at.desc())
        .limit(200)
    ).all()
    # invoice_id/customer_id viven en el payload JSON; el filtro va en Python
    # para no casarse con operadores JSON que cambian por dialecto (SQLite/PG).
    if invoice_id is not None:
        entries = [e for e in entries if (e.payload or {}).get("invoice_id") == invoice_id]
    if customer_id is not None:
        entries = [e for e in entries if (e.payload or {}).get("customer_id") == customer_id]
    return {"entries": [_entry_json(e) for e in entries]}


@router.post("/v1/writeback/{entry_id}/retry")
def retry_writeback(
    entry_id: str,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Reintento manual de una inyección fallida: vuelve a `pending` con el
    presupuesto de intentos completo y dispara el procesado en segundo plano
    (el conector habla con el sistema fuente y puede tardar)."""
    entry = db.scalar(
        select(OutboxEntry).where(
            OutboxEntry.tenant_id == tenant.id, OutboxEntry.id == entry_id
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Inyección no encontrada.")
    if entry.status != "failed":
        raise HTTPException(status_code=409, detail="Solo se reintenta una inyección fallida.")
    reset_for_retry(entry)
    audit.record(
        db,
        tenant_id=tenant.id,
        action="writeback.retry",
        entity_type="outbox",
        entity_id=entry.id,
        principal=principal,
        after={"target": entry.target, "action": entry.action},
    )
    # Commit explícito ANTES de agendar: las BackgroundTasks corren dentro del
    # envío de la respuesta, ANTES del commit del teardown de get_db (verificado
    # en vivo con FastAPI 0.136). Sin esto, el procesado abre su propia sesión,
    # ve la entrada todavía en `failed` y no reintenta nada.
    db.commit()
    from aiuda_server.worker.main import process_writebacks_blocking

    background.add_task(process_writebacks_blocking, tenant.id)
    return _entry_json(entry)
