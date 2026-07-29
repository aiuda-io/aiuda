"""Progreso de activación local, derivado del estado real (state-driven puro).

Cada hito está "hecho" si existe la fila/flag que lo prueba: no guardamos "el
usuario va en el paso 3", lo derivamos. La checklist de la consola consume esto;
el "tour visto/descartado" vive solo en localStorage del cliente.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.engine.provider import credential_from_config, credential_from_store
from aiuda_core.models import Customer, Reminder, Tenant

router = APIRouter()


@router.get("/v1/workspace")
def workspace(tenant: Tenant = Depends(get_tenant)):
    """Identidad local: la consola muestra el negocio y sabe que el rol es dueño."""
    return {"business_name": tenant.name, "role": "dueño"}


@router.get("/v1/onboarding/state")
def onboarding_state(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    config = tenant.config or {}

    # Datos cargados: de ejemplo (sample_ids en config) o clientes reales importados.
    has_data = bool(config.get("sample_ids")) or bool(
        db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(Customer.tenant_id == tenant.id)
        )
    )
    # IA conectada: fila cifrada o config legado (cualquiera de las dos).
    ai_connected = (
        credential_from_store(db, tenant.id) is not None
        or credential_from_config(config) is not None
    )
    # Primer recordatorio aprobado: el momento HITL estrella (soberanía humana).
    approved = bool(
        db.scalar(
            select(func.count())
            .select_from(Reminder)
            .where(
                Reminder.tenant_id == tenant.id,
                Reminder.status.in_(("approved", "sent")),
            )
        )
    )

    steps = [
        {"key": "datos_cargados", "label": "Cargar tus datos", "done": has_data, "href": "/importar"},
        {"key": "ia_conectada", "label": "Conectar tu IA", "done": ai_connected, "href": "/proveedor"},
        {"key": "recordatorio_aprobado", "label": "Aprobar tu primer recordatorio", "done": approved, "href": "/centro"},
    ]
    done_count = sum(1 for s in steps if s["done"])
    return {"steps": steps, "done_count": done_count, "total": len(steps)}
