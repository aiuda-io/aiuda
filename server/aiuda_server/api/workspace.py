"""Identidad local del negocio: nombre, rol y versión de aiuda."""

from fastapi import APIRouter, Depends

from aiuda_server.api.deps import get_tenant
from aiuda_core.models import Tenant

router = APIRouter()


@router.get("/v1/workspace")
def workspace(tenant: Tenant = Depends(get_tenant)):
    """Identidad local: la consola muestra el negocio y sabe que el rol es dueño."""
    from aiuda_core import __version__

    return {"business_name": tenant.name, "role": "dueño", "version": __version__}

