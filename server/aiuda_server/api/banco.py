"""Importar el estado de cuenta bancario (PDF) a la conciliación.

El dueño arrastra el PDF que su banco ya le manda; aiuda lo lee (BBVA y Banorte
directo, cualquier otro banco con la IA del dueño), le enseña la previa con el
cuadre, y SOLO cuando él aprueba, los depósitos entran a la misma bandeja de
conciliación que alimentan Belvo o Stripe, con su procedencia visible.

Dos pasos, como el importador de Excel:
- POST /v1/banco/analizar — lee el PDF y devuelve la previa. NO escribe nada.
- POST /v1/banco/importar — el dueño aprobó: los depósitos entran como pagos
  por conciliar. El cuadre se re-verifica aquí; un estado que no cuadra se
  rechaza aunque el navegador diga otra cosa.
"""

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from aiuda_server import audit
from aiuda_server.api.deps import Principal, get_db, get_principal, get_tenant
from aiuda_core.connectors.estado_cuenta import (
    EstadoCuenta,
    EstadoNoCuadra,
    EstadoNoLegible,
    Movimiento,
    analizar,
    importar_movimientos,
)
from aiuda_core.models import Tenant

router = APIRouter()

_MAX_PDF = 10 * 1024 * 1024  # un estado de cuenta normal pesa menos de 1 MB


def _estado_json(estado: EstadoCuenta, archivo: str) -> dict:
    cuadra, diferencia = estado.cuadre()
    abonos = [m for m in estado.movimientos if m.abono]
    cargos = [m for m in estado.movimientos if m.cargo]
    return {
        "archivo": archivo,
        "banco": estado.banco,
        "metodo": estado.metodo,
        "moneda": estado.moneda,
        "periodo_inicio": estado.periodo_inicio.isoformat() if estado.periodo_inicio else None,
        "periodo_fin": estado.periodo_fin.isoformat() if estado.periodo_fin else None,
        "periodo": estado.periodo_etiqueta(),
        "saldo_inicial": estado.saldo_inicial,
        "saldo_final": estado.saldo_final,
        "cuadra": cuadra,
        "diferencia": diferencia,
        "depositos": {"n": len(abonos), "total": estado.total_abonos},
        "retiros": {"n": len(cargos), "total": estado.total_cargos},
        "movimientos": [
            {
                "fecha": m.fecha.isoformat(),
                "concepto": m.concepto,
                "referencia": m.referencia,
                "cargo": m.cargo,
                "abono": m.abono,
            }
            for m in estado.movimientos
        ],
        "avisos": estado.avisos,
    }


@router.post("/v1/banco/analizar")
async def analizar_estado(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Paso 1: leer el PDF y devolver la previa (banco, periodo, movimientos y
    cuadre) SIN importar nada. BBVA/Banorte no gastan IA; el resto usa la del
    dueño, con la red anti-invención del lector."""
    from aiuda_server.metering import BudgetExceeded, tenant_runner

    content = await file.read()
    if len(content) > _MAX_PDF:
        raise HTTPException(status_code=413, detail="El PDF pesa más de 10 MB.")
    try:
        estado = analizar(content, runner=tenant_runner(db, tenant))
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except (EstadoNoLegible, EstadoNoCuadra) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="No pude leer el archivo. ¿Es el PDF del estado de cuenta?",
        )
    return _estado_json(estado, file.filename or "estado.pdf")


class MovimientoBody(BaseModel):
    fecha: date
    concepto: str = ""
    referencia: str = ""
    cargo: float | None = Field(default=None, ge=0)
    abono: float | None = Field(default=None, ge=0)


class ImportarBody(BaseModel):
    """La previa que el dueño aprobó, tal cual la devolvió /analizar."""

    archivo: str = "estado.pdf"
    banco: str = ""
    moneda: str = "MXN"
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    saldo_inicial: float
    saldo_final: float
    movimientos: list[MovimientoBody]


@router.post("/v1/banco/importar")
def importar_estado(
    body: ImportarBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Paso 2: el dueño aprobó la previa. Los DEPÓSITOS entran como pagos por
    conciliar (el ayudante propone factura; el humano confirma, como siempre).
    Regla dura: el cuadre se verifica de nuevo aquí; si no cuadra, nada entra."""
    if not body.movimientos:
        raise HTTPException(status_code=422, detail="No hay movimientos que importar.")
    estado = EstadoCuenta(
        banco=body.banco.strip()[:40] or "tu banco",
        metodo="importado",
        moneda=body.moneda[:8] or "MXN",
        periodo_inicio=body.periodo_inicio,
        periodo_fin=body.periodo_fin,
        saldo_inicial=round(body.saldo_inicial, 2),
        saldo_final=round(body.saldo_final, 2),
        movimientos=[
            Movimiento(
                fecha=m.fecha,
                concepto=m.concepto.strip()[:220],
                referencia=m.referencia.strip()[:64],
                cargo=round(m.cargo, 2) if m.cargo else None,
                abono=round(m.abono, 2) if m.abono else None,
            )
            for m in body.movimientos
        ],
    )
    try:
        resultado = importar_movimientos(db, tenant.id, estado, body.archivo[:120])
    except EstadoNoCuadra as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit.record(
        db,
        tenant_id=tenant.id,
        action="banco.importar_estado",
        entity_type="payment",
        entity_id=body.archivo[:64],
        principal=principal,
        after={
            "archivo": body.archivo[:120],
            "banco": resultado["banco"],
            "periodo": resultado["periodo"],
            "creados": resultado["creados"],
            "omitidos": resultado["omitidos"],
        },
    )
    return resultado
