"""Exportar a Excel: aiuda NO es el sistema maestro; Excel es el maestro universal
de las PYMEs. Cada lista de la consola baja como .xlsx con lo que el usuario ve
(sus filtros activos) y con encabezados que el importador entiende: un archivo
exportado por aiuda se puede re-importar tal cual (roundtrip sin pérdida).

Forma del archivo: una hoja por entidad, encabezado en negritas y freeze en A2.
Primero van las columnas REIMPORTABLES (exactamente los campos de
smart_import.ENTITY_FIELDS); después las informativas (estado, procedencia).
Montos como número y fechas como fecha, no strings.

Cada export queda en la bitácora (action=data.export) con filas y filtros.
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from aiuda_server import audit
from aiuda_server.api.deps import Principal, get_db, get_principal
from aiuda_core.cartera.aging import classify
from aiuda_core.models import (
    Appointment,
    Customer,
    Invoice,
    Payment,
    PaymentPromise,
    Product,
    Tenant,
)

router = APIRouter()

MX_TZ = ZoneInfo("America/Mexico_City")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ESTADO_FACTURA = {"open": "abierta", "paid": "pagada", "cancelled": "cancelada"}
TRAMO_LABEL = {
    "por_vencer": "Por vencer",
    "vence_pronto": "Vence pronto",
    "vencida_reciente": "Vencida 1-15 días",
    "vencida": "Vencida 16-45 días",
    "critica": "Crítica +45 días",
}


def _naive(dt: datetime | None) -> datetime | None:
    """Excel no acepta datetimes con zona horaria: a hora de pared MX, sin tzinfo."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(MX_TZ)
    return dt.replace(tzinfo=None)


def _contains(q: str, *values) -> bool:
    return any(q in str(v or "").lower() for v in values)


def _tag_names(tenant: Tenant) -> dict[str, str]:
    return {t["id"]: t["name"] for t in (tenant.config or {}).get("tags") or []}


# --- Builders por entidad -----------------------------------------------------
# Cada builder devuelve (encabezados, filas). Replican la carga de los list
# endpoints (main.py / reconciliation.py) y los filtros que las páginas aplican
# client-side (q, bucket, tag), para exportar exactamente lo que el usuario ve.


def _facturas(db, tenant, *, status, bucket, q, tag):
    today = datetime.now(MX_TZ).date()
    status = status or "open"
    rows = db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.tenant_id == tenant.id, Invoice.status == status)
        .order_by(Invoice.due_date)
    ).all()
    out = []
    for inv, cust in rows:
        b = str(classify(inv.due_date, today))
        if bucket and b != bucket:
            continue
        if q and not _contains(q, cust.name, inv.folio):
            continue
        out.append(
            [
                inv.folio,
                cust.name,
                cust.phone or "",
                float(inv.amount),
                inv.issued_date,
                inv.due_date,
                ESTADO_FACTURA.get(inv.status, inv.status),
                TRAMO_LABEL.get(b, b) if inv.status == "open" else "",
                inv.source,
                (_naive(inv.paid_at).date() if inv.paid_at else None),
            ]
        )
    headers = [
        "folio", "cliente", "telefono", "monto", "fecha_emision", "fecha_vencimiento",
        "estado", "tramo", "procedencia", "pagada_el",
    ]
    return headers, out


def _personas(db, tenant, kind, *, q, tag):
    """Clientes y prospectos comparten tabla (Customer.kind) y filtros (q, tag)."""
    tags = _tag_names(tenant)
    customers = db.scalars(
        select(Customer)
        .where(Customer.tenant_id == tenant.id, Customer.kind == kind)
        .order_by(Customer.name)
    ).all()
    # Saldo abierto por cliente en UNA consulta (el list endpoint lo hace por fila).
    abiertos = {
        cid: (int(cnt), float(total))
        for cid, cnt, total in db.execute(
            select(
                Invoice.customer_id,
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.amount), 0),
            )
            .where(Invoice.tenant_id == tenant.id, Invoice.status == "open")
            .group_by(Invoice.customer_id)
        )
    }
    out = []
    for c in customers:
        meta = c.meta or {}
        if q and not _contains(q, c.name, c.phone, meta.get("empresa")):
            continue
        if tag and tag not in (c.tags or []):
            continue
        etiquetas = ", ".join(tags[t] for t in (c.tags or []) if t in tags)
        cnt, total = abiertos.get(c.id, (0, 0.0))
        base = [c.name, c.phone or "", c.email or "", meta.get("empresa") or ""]
        if kind == "prospecto":
            out.append([*base, meta.get("origen") or "", etiquetas])
        else:
            out.append([*base, etiquetas, cnt, total])
    if kind == "prospecto":
        return ["nombre", "telefono", "correo", "empresa", "origen", "etiquetas"], out
    return (
        ["nombre", "telefono", "correo", "empresa", "etiquetas", "facturas_abiertas", "saldo_abierto"],
        out,
    )


def _clientes(db, tenant, *, status, bucket, q, tag):
    return _personas(db, tenant, "cliente", q=q, tag=tag)


def _prospectos(db, tenant, *, status, bucket, q, tag):
    return _personas(db, tenant, "prospecto", q=q, tag=tag)


def _productos(db, tenant, *, status, bucket, q, tag):
    rows = db.scalars(
        select(Product).where(Product.tenant_id == tenant.id).order_by(Product.name)
    ).all()
    out = [
        [
            p.name,
            p.sku or "",
            float(p.price) if p.price is not None else None,
            float(p.stock) if p.stock is not None else None,
            p.unit or "",
            p.source,
        ]
        for p in rows
        if not q or _contains(q, p.name, p.sku)
    ]
    return ["nombre", "sku", "precio", "existencia", "unidad", "procedencia"], out


def _citas(db, tenant, *, status, bucket, q, tag):
    rows = db.scalars(
        select(Appointment)
        .where(Appointment.tenant_id == tenant.id)
        .order_by(Appointment.starts_at.is_(None), Appointment.starts_at)
    ).all()
    out = [
        [
            a.title,
            a.customer_name or "",
            a.customer_phone or "",
            _naive(a.starts_at),
            a.notes or "",
            a.source,
        ]
        for a in rows
        if not q or _contains(q, a.title, a.customer_name)
    ]
    return ["titulo", "cliente", "telefono", "fecha", "notas", "procedencia"], out


def _promesas(db, tenant, *, status, bucket, q, tag):
    status = status or "active"
    fulfilled = status == "fulfilled"
    rows = db.execute(
        select(PaymentPromise, Invoice, Customer)
        .join(Invoice, PaymentPromise.invoice_id == Invoice.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            PaymentPromise.tenant_id == tenant.id,
            PaymentPromise.fulfilled.is_(fulfilled),
        )
        .order_by(
            PaymentPromise.promised_date.desc() if fulfilled else PaymentPromise.promised_date
        )
    ).all()
    out = [
        [
            cust.name,
            inv.folio,
            float(inv.amount),
            p.promised_date,
            p.note or "",
            "cumplida" if p.fulfilled else "activa",
            (_naive(p.fulfilled_at).date() if p.fulfilled_at else None),
        ]
        for p, inv, cust in rows
        if not q or _contains(q, cust.name, inv.folio)
    ]
    return ["cliente", "folio", "monto", "fecha_promesa", "nota", "estado", "cumplida_el"], out


def _conciliacion(db, tenant, *, status, bucket, q, tag):
    """Historial de conciliación (resueltos). Sin el límite de 50 de la bandeja:
    un archivo exportado que trunca en silencio pierde datos."""
    pays = db.scalars(
        select(Payment)
        .where(Payment.tenant_id == tenant.id, Payment.status.in_(["conciliado", "ignorado"]))
        .order_by(Payment.updated_at.desc())
    ).all()
    out = []
    for p in pays:
        aplicaciones = list((p.meta or {}).get("aplicaciones") or [])
        if not aplicaciones and p.invoice_id:
            inv = db.get(Invoice, p.invoice_id)
            if inv is not None:
                aplicaciones = [{"folio": inv.folio, "aplicado": float(p.amount)}]
        folios = ", ".join(str(a.get("folio") or "") for a in aplicaciones)
        out.append(
            [
                p.paid_at,
                float(p.amount),
                p.currency,
                p.source,
                p.reference or "",
                p.counterparty or "",
                p.status,
                folios,
                float((p.meta or {}).get("excedente") or 0.0),
                (_naive(p.updated_at).date() if p.updated_at else None),
            ]
        )
    headers = [
        "fecha_pago", "monto", "moneda", "origen", "referencia", "deposito_de",
        "estado", "facturas_aplicadas", "excedente", "resuelto_el",
    ]
    return headers, out


_BUILDERS = {
    "facturas": _facturas,
    "clientes": _clientes,
    "prospectos": _prospectos,
    "productos": _productos,
    "citas": _citas,
    "promesas": _promesas,
    "conciliacion": _conciliacion,
}


def _xlsx(sheet: str, headers: list[str], rows: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold
    ws.freeze_panes = "A2"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/v1/export/{entidad}.xlsx")
def export_xlsx(
    entidad: str,
    request: Request,
    status: str | None = Query(default=None),
    bucket: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    db=Depends(get_db),
):
    """Descarga la lista como Excel, respetando los filtros activos de la página.
    Filtros por entidad: facturas status|bucket|q · clientes/prospectos q|tag ·
    productos/citas q · promesas status|q · conciliacion (resueltos) sin filtros."""
    builder = _BUILDERS.get(entidad)
    if builder is None:
        raise HTTPException(status_code=404, detail="No hay exportación para esa lista.")
    tenant = principal.tenant
    q_norm = (q or "").strip().lower() or None
    headers, rows = builder(db, tenant, status=status, bucket=bucket, q=q_norm, tag=tag)
    content = _xlsx(entidad, headers, rows)
    filtros = {
        k: v for k, v in {"status": status, "bucket": bucket, "q": q, "tag": tag}.items() if v
    }
    audit.record(
        db,
        tenant_id=tenant.id,
        action="data.export",
        entity_type=entidad,
        principal=principal,
        after={"formato": "xlsx", "filas": len(rows), "filtros": filtros},
        ip=request.client.host if request.client else None,
    )
    fecha = datetime.now(MX_TZ).date().isoformat()
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{entidad}-{fecha}.xlsx"'},
    )
