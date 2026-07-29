"""Buscador global del tenant.

GET /v1/search?q=<texto>

Devuelve hasta 5 resultados por grupo (Clientes, Prospectos, Facturas, Productos,
Conversaciones, Promesas, Conexiones a la medida) filtrando SIEMPRE por tenant.id.
Grupos vacíos se omiten. Cada resultado deep-linkea a su ficha cuando existe
(clickabilidad total); si no hay ficha propia, a la lista donde vive.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from aiuda_core.models import Conversation, Customer, Invoice, PaymentPromise, Product
from aiuda_server.api.deps import get_db, get_tenant

router = APIRouter()

_MAX = 5


def _estado_factura(status: str) -> str:
    return "pagada" if status == "paid" else "abierta"


@router.get("/v1/search")
def search(
    q: str = Query(default=""),
    tenant=Depends(get_tenant),
    db=Depends(get_db),
):
    q = q.strip()
    if len(q) < 2:
        return {"groups": []}

    pat = f"%{q}%"
    tid = tenant.id
    groups = []

    # ── Clientes ──────────────────────────────────────────────────────────────
    # Los prospectos son Customer con kind="prospecto": van en su propio grupo
    # (viven en /prospectos, no en /clientes) para que el resultado lleve bien.
    clientes = db.scalars(
        select(Customer)
        .where(
            Customer.tenant_id == tid,
            Customer.kind != "prospecto",
            (Customer.name.ilike(pat)) | (Customer.phone.ilike(pat)),
        )
        .limit(_MAX)
    ).all()

    if clientes:
        groups.append(
            {
                "title": "Clientes",
                "items": [
                    {
                        "label": c.name,
                        "sublabel": c.phone,
                        "href": f"/clientes/{c.id}",
                    }
                    for c in clientes
                ],
            }
        )

    # ── Prospectos (DENUE u otros orígenes) ───────────────────────────────────
    prospectos = db.scalars(
        select(Customer)
        .where(
            Customer.tenant_id == tid,
            Customer.kind == "prospecto",
            (Customer.name.ilike(pat)) | (Customer.phone.ilike(pat)),
        )
        .limit(_MAX)
    ).all()

    if prospectos:
        groups.append(
            {
                "title": "Prospectos",
                "items": [
                    {
                        "label": c.name,
                        "sublabel": c.phone or (c.meta or {}).get("municipio") or "prospecto",
                        "href": "/prospectos",
                    }
                    for c in prospectos
                ],
            }
        )

    # ── Facturas ──────────────────────────────────────────────────────────────
    inv_rows = db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.tenant_id == tid,
            (Invoice.folio.ilike(pat)) | (Customer.name.ilike(pat)),
        )
        .limit(_MAX)
    ).all()

    if inv_rows:
        groups.append(
            {
                "title": "Facturas",
                "items": [
                    {
                        "label": f"{inv.folio} · ${float(inv.amount):,.2f}",
                        "sublabel": f"{cust.name} · {_estado_factura(inv.status)}",
                        "href": f"/facturas/{inv.id}",
                    }
                    for inv, cust in inv_rows
                ],
            }
        )

    # ── Productos ─────────────────────────────────────────────────────────────
    productos = db.scalars(
        select(Product)
        .where(
            Product.tenant_id == tid,
            (Product.name.ilike(pat)) | (Product.sku.ilike(pat)),
        )
        .limit(_MAX)
    ).all()

    if productos:
        groups.append(
            {
                "title": "Productos",
                "items": [
                    {
                        "label": p.name,
                        "sublabel": p.sku or "producto",
                        "href": "/productos",
                    }
                    for p in productos
                ],
            }
        )

    # ── Conversaciones ────────────────────────────────────────────────────────
    # Busca clientes cuyo nombre o teléfono coincida, luego junta con Conversation
    conv_rows = db.execute(
        select(Conversation, Customer)
        .join(Customer, Conversation.remote_phone == Customer.phone)
        .where(
            Conversation.tenant_id == tid,
            Customer.tenant_id == tid,
            (Customer.name.ilike(pat)) | (Customer.phone.ilike(pat)),
        )
        .limit(_MAX)
    ).all()

    if conv_rows:
        groups.append(
            {
                "title": "Conversaciones",
                "items": [
                    {
                        "label": cust.name,
                        "sublabel": cust.phone,
                        "href": f"/conversaciones/{conv.id}",
                    }
                    for conv, cust in conv_rows
                ],
            }
        )

    # ── Promesas de pago ──────────────────────────────────────────────────────
    promesas = db.scalars(
        select(PaymentPromise)
        .where(
            PaymentPromise.tenant_id == tid,
            PaymentPromise.note.ilike(pat),
        )
        .limit(_MAX)
    ).all()

    if promesas:
        groups.append(
            {
                "title": "Promesas de pago",
                "items": [
                    {
                        "label": (p.note or "")[:80],
                        "sublabel": "promesa de pago",
                        "href": "/promesas",
                    }
                    for p in promesas
                ],
            }
        )

    # ── Conexiones a la medida ────────────────────────────────────────────────
    # Viven en tenant.config (no en tabla propia); se buscan por el nombre que
    # les puso el dueño y llevan a Integraciones, donde se administran.
    q_lower = q.lower()
    conexiones = [
        c
        for c in (tenant.config or {}).get("custom_sources") or []
        if q_lower in str(c.get("name", "")).lower()
    ][:_MAX]

    if conexiones:
        groups.append(
            {
                "title": "Conexiones a la medida",
                "items": [
                    {
                        "label": c.get("name", ""),
                        "sublabel": "conexión a la medida",
                        "href": "/integraciones",
                    }
                    for c in conexiones
                ],
            }
        )

    return {"groups": groups}
