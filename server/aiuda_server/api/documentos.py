"""Documentos oficiales del negocio que una rutina bajó de un portal: la Opinión de
cumplimiento (32-D) y la Constancia de situación fiscal del SAT.

Aquí solo se leen: los crea la corrida que los trae (ver
`aiuda_core.cua.fallback`). El listado nunca lleva el PDF; ese se pide por pieza.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.models import Documento, Tenant

router = APIRouter()

NOMBRE_TIPO = {
    "opinion_32d": "Opinión de cumplimiento (32-D)",
    "constancia": "Constancia de situación fiscal",
}


def serializar(d: Documento) -> dict:
    return {
        "id": d.id,
        "rfc": d.rfc,
        "tipo": d.tipo,
        "nombre": NOMBRE_TIPO.get(d.tipo, d.tipo),
        "folio": d.folio,
        "sentido": d.sentido,
        "fecha": d.fecha.isoformat() if d.fecha else None,
        "mission_id": d.mission_id,
    }


@router.get("/v1/documentos")
def listar_documentos(
    rfc: str = "",
    tipo: str = "",
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> dict:
    """Los documentos bajados, del más reciente al más viejo, filtrables por RFC y
    tipo. Sin el PDF."""
    q = select(Documento).where(Documento.tenant_id == tenant.id)
    if rfc:
        q = q.where(Documento.rfc == rfc.strip().upper())
    if tipo:
        q = q.where(Documento.tipo == tipo)
    filas = db.scalars(q.order_by(Documento.fecha.desc()).limit(200)).all()
    return {"documentos": [serializar(d) for d in filas]}


@router.get("/v1/documentos/{documento_id}.pdf")
def documento_pdf(
    documento_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Sirve el PDF de un documento para verlo o descargarlo."""
    doc = db.scalar(
        select(Documento).where(
            Documento.tenant_id == tenant.id, Documento.id == documento_id
        )
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    nombre = f"{doc.tipo}_{doc.rfc}_{doc.fecha:%Y-%m-%d}.pdf"
    return Response(
        content=doc.pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )
