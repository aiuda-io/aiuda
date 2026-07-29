"""Conciliación de pagos (Diego): la bandeja donde el dinero que entró se casa con
las facturas que liquida. Diego PROPONE con evidencia (por qué cuadra); el humano
confirma, ajusta (elige otra factura) o rechaza. Nada se cierra solo.

Qué vive aquí:
- GET  /v1/reconciliation            — pagos pendientes con propuesta + evidencia,
  dichos de pago por verificar, estado de fuentes y tolerancia vigente.
- POST /v1/reconciliation/{id}/confirm — aplica el pago a una o VARIAS facturas
  (cascada por vencimiento): cierra las cubiertas, abona la parcial. Con auditoría.
- POST /v1/reconciliation/{id}/ignore  — rechaza el pago de la bandeja.
- GET  /v1/reconciliation/resueltos    — historial: qué se concilió/rechazó y cómo.
- GET/PUT /v1/reconciliation/config    — tolerancia de monto (Tenant.config, sin migración).

Honestidad: Belvo/Stripe (confirmación de pago) están probados SOLO con fixtures de
contrato; `verificada_en_vivo` es False hasta que exista una corrida real contra la
API del proveedor. No se inventa liveness.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import Principal, get_db, get_principal, get_tenant
from aiuda_core.engine.reconcile import (
    Candidate,
    GroupCandidate,
    tol_monto,
    abonos_de,
    evaluate,
    saldo_pendiente,
    tolerancia,
)
from aiuda_core.models import Customer, Invoice, Payment, Tenant

router = APIRouter()

MX_TZ = ZoneInfo("America/Mexico_City")


def _candidate_json(c: Candidate) -> dict:
    return {
        "invoice_id": c.invoice_id,
        "folio": c.folio,
        "customer": c.customer,
        "amount": c.amount,
        "saldo": c.saldo,
        "due_date": c.due_date,
        "score": c.score,
        "reason": c.reason,
        "cuadra": c.cuadra,
        "parcial": c.parcial,
    }


def _group_json(g: GroupCandidate) -> dict:
    return {
        "invoice_ids": g.invoice_ids,
        "folios": g.folios,
        "customer": g.customer,
        "total": g.total,
        "score": g.score,
        "reason": g.reason,
        "cuadra": g.cuadra,
    }


def _origen_pago(p: Payment) -> str | None:
    """Procedencia legible cuando el pago vino de un estado de cuenta en PDF:
    "de tu estado de cuenta de BBVA, marzo 2026". None para las demás fuentes
    (el `source` ya las nombra)."""
    ec = (p.meta or {}).get("estado_cuenta") or {}
    if not ec:
        return None
    banco = ec.get("banco") or "tu banco"
    periodo = ec.get("periodo") or ""
    return f"de tu estado de cuenta de {banco}" + (f", {periodo}" if periodo else "")


def _fuentes_estado(db, tenant: Tenant) -> dict:
    """Estado honesto de las fuentes de confirmación de pago.

    `verificada_en_vivo` es False FIJO: los conectores Belvo/Stripe tienen contrato
    y fixtures, pero nunca han corrido contra la API real del proveedor. Se voltea
    a True cuando esa corrida exista y quede registrada — no antes."""
    from aiuda_core.connectors.credentials import get_credential

    def _cfg(provider: str, gate: str) -> dict:
        try:
            creds = get_credential(db, tenant.id, provider)
        except Exception:
            creds = None
        return {
            "configurada": bool(creds and creds.get(gate)),
            "verificada_en_vivo": False,
        }

    return {"belvo": _cfg("belvo", "secret_id"), "stripe": _cfg("stripe", "api_key")}


def _dichos(db, tenant: Tenant, pendientes: list[Payment], tol_pct: float, tol_abs: float) -> list[dict]:
    """Dichos de pago: facturas abiertas donde el cliente DICE que ya pagó
    (payment_reported). Se contrastan contra los pagos pendientes del banco/pasarela:
    con respaldo se puede conciliar; sin respaldo, la factura sigue abierta —
    un dicho no es un pago."""
    rows = db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.tenant_id == tenant.id,
            Invoice.status == "open",
            Invoice.payment_reported.is_(True),
        )
        .order_by(Invoice.due_date)
    ).all()
    out = []
    for inv, cust in rows:
        saldo = saldo_pendiente(inv)
        tol = tol_monto(saldo, tol_pct, tol_abs)
        respaldo = None
        mejor_diff = None
        for pay in pendientes:
            diff = abs(float(pay.amount) - saldo)
            if diff > tol:
                continue
            # El de menor diferencia gana; a igual diferencia, el que trae el
            # nombre del cliente en el depósito.
            nombre_en_deposito = bool(
                pay.counterparty and cust.name and cust.name.lower() in pay.counterparty.lower()
            )
            if mejor_diff is None or diff < mejor_diff or (diff == mejor_diff and nombre_en_deposito):
                mejor_diff = diff
                respaldo = {
                    "payment_id": pay.id,
                    "amount": float(pay.amount),
                    "paid_at": pay.paid_at.isoformat(),
                    "source": pay.source,
                    "diferencia": round(diff, 2),
                }
        out.append(
            {
                "invoice_id": inv.id,
                "folio": inv.folio,
                "customer": cust.name,
                "amount": float(inv.amount),
                "saldo": saldo,
                "due_date": inv.due_date.isoformat(),
                "respaldo": respaldo,
            }
        )
    return out


@router.get("/v1/reconciliation")
def list_reconciliation(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Bandeja de Diego: pagos detectados pendientes con la evidencia completa
    (propuesta, alternativas, grupos multifactura, veredicto de ambigüedad), más
    los dichos de pago por verificar y el estado honesto de las fuentes."""
    tol_pct, tol_abs = tolerancia(tenant.config)
    pays = db.scalars(
        select(Payment)
        .where(Payment.tenant_id == tenant.id, Payment.status == "pendiente")
        .order_by(Payment.paid_at.desc())
    ).all()
    out = []
    for p in pays:
        ev = evaluate(db, tenant.id, p, tol_pct=tol_pct, tol_abs=tol_abs)
        # Ambiguo = SIN propuesta única: todas las candidatas van como alternativas
        # y el humano elige. Con propuesta clara, la mejor va aparte.
        propone_factura = ev.proposal_kind == "factura" and ev.candidates
        proposal = _candidate_json(ev.candidates[0]) if propone_factura else None
        alternates = [_candidate_json(c) for c in (ev.candidates[1:] if propone_factura else ev.candidates)]
        out.append(
            {
                "id": p.id,
                "amount": float(p.amount),
                "currency": p.currency,
                "paid_at": p.paid_at.isoformat(),
                "source": p.source,
                "origen": _origen_pago(p),
                "reference": p.reference,
                "counterparty": p.counterparty,
                "proposal": proposal,
                "alternates": alternates,
                "grupos": [_group_json(g) for g in ev.groups],
                "propuesta_tipo": ev.proposal_kind,
                "ambiguo": ev.ambiguous,
                "nota": ev.note,
            }
        )
    return {
        "pending": out,
        "count": len(out),
        "dichos": _dichos(db, tenant, pays, tol_pct, tol_abs),
        "fuentes": _fuentes_estado(db, tenant),
        "config": {"tolerancia_pct": tol_pct, "tolerancia_abs": tol_abs},
    }


class ReconcileBody(BaseModel):
    # Compat: `invoice_id` (una factura) fue el contrato original; `invoice_ids`
    # permite que un pago cubra varias. Se acepta cualquiera de los dos.
    invoice_id: str | None = None
    invoice_ids: list[str] | None = None


@router.post("/v1/reconciliation/{payment_id}/confirm")
def confirm_reconciliation(
    payment_id: str,
    body: ReconcileBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Conciliar: el humano confirma que este pago se aplica a estas facturas.

    Cascada por vencimiento (la más antigua primero): cada factura cuyo saldo queda
    cubierto (dentro de la tolerancia) se CIERRA — pagada, verificada por el origen
    del pago, con write-back y auditoría. Si el pago no alcanza la última, queda
    como ABONO: la factura sigue abierta con su saldo y el abono registrado.
    Si el pago EXCEDE lo elegido más la tolerancia, se rechaza: elegir más facturas
    o corregir, nunca desaparecer dinero en silencio."""
    ids: list[str] = []
    for iid in body.invoice_ids or ([body.invoice_id] if body.invoice_id else []):
        if iid and iid not in ids:
            ids.append(iid)
    if not ids:
        raise HTTPException(status_code=422, detail="Indica al menos una factura.")

    pay = db.scalar(
        select(Payment).where(Payment.tenant_id == tenant.id, Payment.id == payment_id)
    )
    if pay is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if pay.status != "pendiente":
        raise HTTPException(status_code=409, detail="Ese pago ya se concilió o se ignoró.")

    # Conciliar cierra facturas y las devuelve a la fuente: pesa lo mismo que
    # aprobar un envío, así que el tope del aparato manda igual aquí. Faltaba: un
    # invitado con tope chico podía cerrar una factura de cualquier monto.
    if not principal.puede_aprobar(float(pay.amount)):
        raise HTTPException(
            403,
            "Este pago pasa del monto que puedes conciliar desde tu aparato. "
            "Déjalo para el dueño.",
        )

    invoices = db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.id.in_(ids))
    ).all()
    if len(invoices) != len(ids):
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    ya_pagadas = [i.folio for i in invoices if i.status == "paid"]
    if ya_pagadas:
        raise HTTPException(status_code=409, detail=f"Ya está pagada: {', '.join(ya_pagadas)}.")
    if any(i.status != "open" for i in invoices):
        raise HTTPException(status_code=409, detail="Solo se concilian facturas abiertas.")

    tol_pct, tol_abs = tolerancia(tenant.config)
    monto = float(pay.amount)
    invoices.sort(key=lambda i: i.due_date)  # cascada: la más antigua por vencer primero
    saldos = {i.id: saldo_pendiente(i) for i in invoices}
    suma = sum(saldos.values())
    if monto > suma + tol_monto(suma, tol_pct, tol_abs):
        raise HTTPException(
            status_code=409,
            detail=(
                f"El pago (${monto:,.2f}) excede lo elegido (${suma:,.2f}) más la "
                "tolerancia. Agrega otra factura o revisa el monto."
            ),
        )

    now = datetime.now(MX_TZ)
    restante = monto
    aplicaciones = []
    from aiuda_core.engine.writeback import queue_payment_writeback

    for inv in invoices:
        saldo = saldos[inv.id]
        aplicado = round(min(saldo, restante), 2)
        if aplicado <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"El pago no alcanza a tocar {inv.folio}. Quita esa factura.",
            )
        restante = round(restante - aplicado, 2)
        abono = {
            "payment_id": pay.id,
            "aplicado": aplicado,
            "fecha": pay.paid_at.isoformat(),
            "source": pay.source,
        }
        # Columna JSON: reasignar SIEMPRE (la mutación in-place no se trackea).
        inv.meta = {**(inv.meta or {}), "abonos": [*abonos_de(inv), abono]}
        cubierta = aplicado >= saldo - tol_monto(saldo, tol_pct, tol_abs)
        if cubierta:
            inv.status = "paid"
            inv.paid_at = now
            inv.paid_source = pay.source
            inv.payment_reported = False
            inv.verified = "verificada"
            # Write-back solo del cierre: el abono parcial aún no tiene ejecutor
            # (writeback registra el pago completo en la fuente).
            queue_payment_writeback(db, tenant, inv)
        audit.record(
            db,
            tenant_id=tenant.id,
            action="payment.reconcile" if cubierta else "payment.abono",
            entity_type="payment",
            entity_id=pay.id,
            principal=principal,
            before={"invoice_status": "open", "saldo": f"{saldo:.2f}"},
            after={
                "invoice_id": inv.id,
                "folio": inv.folio,
                "aplicado": f"{aplicado:.2f}",
                "saldo_restante": f"{max(0.0, saldo - aplicado):.2f}",
                "amount": str(pay.amount),
                "fuente_pago": pay.source,
            },
        )
        aplicaciones.append(
            {
                "invoice_id": inv.id,
                "folio": inv.folio,
                "aplicado": aplicado,
                "cerrada": cubierta,
                "saldo": round(max(0.0, saldo - aplicado), 2),
            }
        )

    pay.status = "conciliado"
    pay.invoice_id = invoices[0].id  # la columna es una FK; el detalle completo va en meta
    pay.meta = {
        **(pay.meta or {}),
        "aplicaciones": aplicaciones,
        # Excedente dentro de tolerancia (redondeos/comisiones): se registra, no se esconde.
        **({"excedente": restante} if restante > 0.005 else {}),
    }
    db.flush()
    primera = invoices[0]
    return {
        "id": pay.id,
        "status": pay.status,
        "invoice": {"id": primera.id, "folio": primera.folio, "status": primera.status},
        "invoices": [
            {**a, "status": "paid" if a["cerrada"] else "open"} for a in aplicaciones
        ],
        "excedente": restante if restante > 0.005 else 0.0,
    }


@router.post("/v1/reconciliation/{payment_id}/ignore")
def ignore_reconciliation(
    payment_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Rechazar: este pago no corresponde a ninguna factura (o no es de clientes).
    Sale de la bandeja; queda en el historial como ignorado, con auditoría."""
    pay = db.scalar(
        select(Payment).where(Payment.tenant_id == tenant.id, Payment.id == payment_id)
    )
    if pay is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    pay.status = "ignorado"
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="payment.ignore",
        entity_type="payment",
        entity_id=pay.id,
        principal=principal,
    )
    return {"id": pay.id, "status": pay.status}


@router.get("/v1/reconciliation/resueltos")
def list_resolved(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Historial de la bandeja: pagos ya conciliados o rechazados, con el detalle
    de a qué facturas se aplicaron (ver estado, rastrear una decisión)."""
    pays = db.scalars(
        select(Payment)
        .where(Payment.tenant_id == tenant.id, Payment.status.in_(["conciliado", "ignorado"]))
        .order_by(Payment.updated_at.desc())
        .limit(50)
    ).all()
    out = []
    for p in pays:
        aplicaciones = list((p.meta or {}).get("aplicaciones") or [])
        if not aplicaciones and p.invoice_id:
            # Conciliados de antes de las aplicaciones: reconstruir lo mínimo.
            inv = db.get(Invoice, p.invoice_id)
            if inv is not None:
                aplicaciones = [
                    {
                        "invoice_id": inv.id,
                        "folio": inv.folio,
                        "aplicado": float(p.amount),
                        "cerrada": inv.status == "paid",
                        "saldo": 0.0,
                    }
                ]
        out.append(
            {
                "id": p.id,
                "amount": float(p.amount),
                "currency": p.currency,
                "paid_at": p.paid_at.isoformat(),
                "source": p.source,
                "origen": _origen_pago(p),
                "reference": p.reference,
                "counterparty": p.counterparty,
                "status": p.status,
                "resuelto_el": p.updated_at.isoformat(),
                "aplicaciones": aplicaciones,
                "excedente": float((p.meta or {}).get("excedente") or 0.0),
            }
        )
    return {"resueltos": out, "count": len(out)}


class ToleranciaBody(BaseModel):
    tolerancia_pct: float = Field(ge=0, le=100)
    tolerancia_abs: float = Field(ge=0, le=100000)


@router.get("/v1/reconciliation/config")
def get_config(tenant: Tenant = Depends(get_tenant)):
    tol_pct, tol_abs = tolerancia(tenant.config)
    return {"tolerancia_pct": tol_pct, "tolerancia_abs": tol_abs}


@router.put("/v1/reconciliation/config")
def put_config(
    body: ToleranciaBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Tolerancia de monto del matching. Vive en Tenant.config (sin migración)."""
    antes = dict(zip(("tolerancia_pct", "tolerancia_abs"), tolerancia(tenant.config)))
    conciliacion = {
        **((tenant.config or {}).get("conciliacion") or {}),
        "tolerancia_pct": body.tolerancia_pct,
        "tolerancia_abs": body.tolerancia_abs,
    }
    # Columna JSON: reasignar, la mutación in-place no se trackea.
    tenant.config = {**(tenant.config or {}), "conciliacion": conciliacion}
    db.add(tenant)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="reconciliation.config",
        entity_type="tenant",
        entity_id=tenant.id,
        principal=principal,
        before=antes,
        after={"tolerancia_pct": body.tolerancia_pct, "tolerancia_abs": body.tolerancia_abs},
    )
    return {"tolerancia_pct": body.tolerancia_pct, "tolerancia_abs": body.tolerancia_abs}
