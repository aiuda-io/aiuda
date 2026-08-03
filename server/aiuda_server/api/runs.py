"""Qué hizo cada ayudante: la lista, el detalle y la transcripción.

Dos profundidades a propósito. La lista y el detalle hablan en el idioma del dueño (qué
leyó, qué propuso, qué no pudo y por qué). La transcripción, en un endpoint aparte, es
para cuando alguien quiere el turno completo: prompts, tools con sus argumentos y tiempos.

Se separan porque no cuestan lo mismo ni duran lo mismo: los turnos se podan y la
narrativa se queda.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.models import Customer, Invoice, Reminder, Run, RunLink, RunTurn, Tenant

router = APIRouter()

RETENCION_DEFAULT = 90

DISPARO_LABEL = {
    "corrida": "Corrida del día",
    "sincronizacion": "Leyó tus fuentes",
    "manual": "Lo corriste tú",
    "chat": "Le preguntaste",
    "entrante": "Contestó un mensaje",
    "rutina": "Encargo a un portal",
}

ESTADO_LABEL = {
    "running": "Trabajando",
    "done": "Terminó",
    "failed": "No pudo",
    "cortado": "Se detuvo",
}


def _fila(r: Run) -> dict:
    return {
        "id": r.id,
        "ayudante_id": r.ayudante_id,
        # El nombre es un SNAPSHOT: el dueño renombra o borra, y la bitácora no cambia
        # lo que dice que pasó.
        "ayudante": r.ayudante_nombre,
        "aiudita": r.aiudita_id,
        "disparo": r.disparo,
        "disparo_label": DISPARO_LABEL.get(r.disparo, r.disparo),
        "status": r.status,
        "status_label": ESTADO_LABEL.get(r.status, r.status),
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "duracion_ms": (
            int((r.finished_at - r.started_at).total_seconds() * 1000)
            if r.started_at and r.finished_at
            else None
        ),
        "resumen": r.resumen,
        "conteos": r.conteos or {},
        "motivos": r.motivos or [],
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "costo_usd": float(r.costo_usd) if r.costo_usd is not None else None,
        "error": r.error,
    }


@router.get("/v1/runs")
def listar_runs(
    ayudante_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> list[dict]:
    """Lo que han hecho tus ayudantes, de lo más reciente a lo más viejo."""
    q = select(Run).where(Run.tenant_id == tenant.id)
    if ayudante_id:
        q = q.where(Run.ayudante_id == ayudante_id)
    if status:
        q = q.where(Run.status == status)
    filas = db.scalars(q.order_by(Run.started_at.desc()).limit(limit)).all()
    return [_fila(r) for r in filas]


@router.get("/v1/runs/{run_id}")
def detalle_run(run_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    """El run con sus enlaces YA RESUELTOS a nombres de negocio.

    Sin resolver, la pantalla enseñaría "propuso 4" y una lista de ids: no serviría de
    nada. Con esto el dueño abre la propuesta concreta desde aquí."""
    r = db.get(Run, run_id)
    if r is None or r.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Ese registro no existe.")

    ligas = db.scalars(select(RunLink).where(RunLink.run_id == r.id)).all()
    resueltas = []
    for x in ligas:
        etiqueta = x.entity_id
        if x.entity_type == "reminder":
            rem = db.get(Reminder, x.entity_id)
            if rem is not None:
                inv = db.get(Invoice, rem.invoice_id) if rem.invoice_id else None
                cliente = db.get(Customer, inv.customer_id) if inv else None
                etiqueta = (
                    " · ".join(
                        p for p in [cliente.name if cliente else None, inv.folio if inv else None] if p
                    )
                    or rem.title
                    or "Propuesta"
                )
        elif x.entity_type == "invoice":
            inv = db.get(Invoice, x.entity_id)
            if inv is not None:
                etiqueta = inv.folio
        elif x.entity_type == "customer":
            c = db.get(Customer, x.entity_id)
            if c is not None:
                etiqueta = c.name
        resueltas.append(
            {"tipo": x.entity_type, "id": x.entity_id, "rol": x.rol, "etiqueta": etiqueta}
        )

    turnos = db.scalar(
        select(RunTurn.id).where(RunTurn.run_id == r.id).limit(1)
    )
    return {
        **_fila(r),
        "toco": resueltas,
        # Si ya se podó, la pantalla no ofrece un botón que no lleva a ningún lado.
        "hay_transcripcion": turnos is not None,
    }


@router.get("/v1/runs/{run_id}/turnos")
def turnos_run(run_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> list[dict]:
    """La transcripción: cada ida y vuelta al modelo, con sus tools.

    Los prompts salen ya redactados desde que se guardaron: aquí no hay un camino para
    leer el dato original, porque nunca se escribió."""
    r = db.get(Run, run_id)
    if r is None or r.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Ese registro no existe.")
    filas = db.scalars(
        select(RunTurn).where(RunTurn.run_id == r.id).order_by(RunTurn.idx)
    ).all()
    return [
        {
            "idx": t.idx,
            "role": t.role,
            "task": t.task,
            "model": t.model,
            "system_prompt": t.system_prompt,
            "user_prompt": t.user_prompt,
            "output_text": t.output_text,
            "tools": t.tools or [],
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "latencia_ms": t.latencia_ms,
            "error": t.error,
        }
        for t in filas
    ]


def podar_runs(db, tenant: Tenant, dias: int | None = None) -> int:
    """Borra los TURNOS viejos y conserva los runs.

    La narrativa es barata y permanente: "el 2 de agosto propuso 4 recordatorios" cabe en
    una fila y sirve para siempre. La transcripción es cara y sensible, así que caduca.

    `audit_logs` no se toca NUNCA: es la prueba de quién autorizó un cobro."""
    cfg = ((tenant.config or {}).get("observabilidad") or {})
    dias = dias if dias is not None else int(cfg.get("retencion_dias", RETENCION_DEFAULT))
    if dias <= 0:
        return 0
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    viejos = db.scalars(
        select(Run.id).where(Run.tenant_id == tenant.id, Run.started_at < corte)
    ).all()
    if not viejos:
        return 0
    borrados = 0
    for rid in viejos:
        for t in db.scalars(select(RunTurn).where(RunTurn.run_id == rid)).all():
            db.delete(t)
            borrados += 1
    db.flush()
    return borrados
