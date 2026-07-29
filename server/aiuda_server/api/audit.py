"""Lectura de la bitácora de auditoría (quién aprobó/concilió/revocó qué)."""

from fastapi import APIRouter, Depends

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.models import Tenant

router = APIRouter()


@router.get("/v1/audit")
def list_audit(
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Bitácora del negocio, más reciente primero. Solo admin+ (revela quién hizo qué)."""
    return [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor_user_id": r.actor_user_id,
            "before": r.before,
            "after": r.after,
            "at": r.created_at.isoformat(),
        }
        for r in audit.recent(db, tenant.id)
    ]
