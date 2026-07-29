"""Cobro con link de pago: genera un link (Mercado Pago / Clip / Conekta) que el ayudante
manda por WhatsApp junto con el recordatorio. Consume la capacidad ``link_de_pago``.

El proveedor se resuelve de la credencial CIFRADA del tenant: el primero conectado gana
(orden de preferencia en ``_PASARELAS``). Así el dueño conecta una pasarela y el endpoint
la usa sin más configuración.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.engine.cobro import resolver_pasarela
from aiuda_core.models import Tenant

router = APIRouter()


class CobroLinkBody(BaseModel):
    monto: float
    concepto: str = ""
    referencia: str = ""  # p.ej. folio de la factura, para casar el pago después


@router.post("/v1/cobro/link")
def crear_link_cobro(
    body: CobroLinkBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Genera un link de pago con la pasarela conectada del tenant. El ayudante lo incluye
    en el recordatorio; el cliente paga con un clic (tarjeta, OXXO o SPEI según la pasarela).
    Nada se cobra aquí: solo se crea el link."""
    if body.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero.")
    prov, client = resolver_pasarela(db, tenant)
    if client is None:
        raise HTTPException(
            status_code=409,
            detail="No hay pasarela de cobro conectada. Conecta Mercado Pago, Clip o Conekta en Integraciones.",
        )
    try:
        link = client.crear_link_pago(body.monto, body.concepto, body.referencia)
    except Exception as exc:  # pasarela caída, credencial mala, contrato distinto
        raise HTTPException(status_code=502, detail=f"La pasarela no generó el link: {exc}")
    return {"proveedor": prov, "link": link}
