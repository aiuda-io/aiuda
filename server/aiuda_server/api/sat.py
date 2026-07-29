"""La bóveda fiscal del SAT: los CFDI del negocio, en su computadora.

Un negocio puede tener hasta TRES empresas (razones sociales, RFCs) — lo normal
en la PyME mexicana: la persona física, la S.A., a veces una tercera. Todas son
el mismo negocio para operarlo; para el SAT son contribuyentes separados. Aquí
se administran esas empresas, se suben XML/ZIP a mano y se consulta la bóveda
(cada CFDI clasificado por empresa y dirección; lo intercompañía —una empresa
suya facturándole a otra— queda fuera de la cartera).

Seguridad (regla dura): la e.firma se guarda cifrada (Fernet, una fila por RFC)
y NUNCA sale por esta API — ningún endpoint devuelve la llave, el certificado ni
la contraseña, ni siquiera enmascarados por partes. Nada de secretos en logs.
"""

import base64
import io
import re
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.sat_descarga import (
    SatCredencialInvalida,
    SatDescargaClient,
    validar_efirma,
)
from aiuda_core.engine.sync import (
    SAT_EFIRMA_PREFIX,
    SAT_MAX_EMPRESAS,
    SAT_PLAZO_DEFAULT,
    importar_cfdis,
    sat_empresas,
)
from aiuda_core.models import CfdiBoveda, IntegrationCredential, Invoice, Tenant

router = APIRouter()

_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

# Un ZIP del SAT trae puros XML chicos; 80 MB da de sobra y corta un archivo loco.
_MAX_ARCHIVO_MB = 80


def _rfc_valido(rfc: str) -> str:
    rfc = (rfc or "").strip().upper()
    if not _RFC_RE.match(rfc):
        raise HTTPException(
            status_code=422,
            detail="Ese RFC no se ve bien (ej. HCO250213281 o GOBM980902FL1).",
        )
    return rfc


def _tope_empresas(db, tenant: Tenant, rfc_nuevo: str) -> None:
    """Hasta 3 empresas por negocio. Agregar una ya registrada no cuenta doble."""
    actuales = {e["rfc"] for e in sat_empresas(db, tenant)}
    if rfc_nuevo not in actuales and len(actuales) >= SAT_MAX_EMPRESAS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya tienes {SAT_MAX_EMPRESAS} empresas registradas, el tope de "
                "aiuda. Borra una para agregar otra."
            ),
        )


def _leer_xmls(nombre: str, contenido: bytes) -> list[bytes]:
    """XML suelto o ZIP (como lo entrega el SAT) → lista de XML, todo en memoria.
    Nada se escribe a disco."""
    if len(contenido) > _MAX_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"El archivo pasa de {_MAX_ARCHIVO_MB} MB."
        )
    nombre = (nombre or "").lower()
    if nombre.endswith(".zip") or contenido[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(contenido))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail="El ZIP no se pudo abrir.") from exc
        out = []
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            out.append(zf.read(info))
        return out
    return [contenido]


@router.post("/v1/sat/importar")
def sat_importar(
    archivo: UploadFile = File(...),
    rfc: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Sube XML de CFDI (uno o un ZIP del SAT) a la bóveda y arma la cartera con
    los emitidos a crédito. `rfc` opcional: registra de una vez esa empresa del
    negocio (si aún no está) para clasificar bien los comprobantes."""
    if rfc.strip():
        _registrar_empresa_manual(db, tenant, _rfc_valido(rfc), "")
    contenido = archivo.file.read()
    xmls = _leer_xmls(archivo.filename or "", contenido)
    if not xmls:
        raise HTTPException(
            status_code=422, detail="No encontré ningún XML en el archivo."
        )
    res = importar_cfdis(db, tenant, xmls, source="importado")
    audit.record(
        db,
        tenant_id=tenant.id,
        action="sat.importar",
        entity_type="cfdi",
        after={k: v for k, v in res.items() if k != "avisos"},  # conteos, nunca contenido
    )
    db.flush()
    return res


def _guardar_plazo(tenant: Tenant, rfc: str, plazo_dias: int) -> None:
    cfg = dict(tenant.config or {})
    plazos = dict(cfg.get("sat_plazos") or {})
    plazos[rfc] = max(1, min(365, int(plazo_dias)))
    cfg["sat_plazos"] = plazos
    tenant.config = cfg
    flag_modified(tenant, "config")


def _registrar_empresa_manual(
    db, tenant: Tenant, rfc: str, nombre: str, plazo_dias: int | None = None
) -> None:
    _tope_empresas(db, tenant, rfc)
    cfg = dict(tenant.config or {})
    lista = [dict(e) for e in cfg.get("sat_empresas") or []]
    if any((e.get("rfc") or "").upper() == rfc for e in lista):
        if nombre:  # ya estaba: a lo más se completa el nombre
            for e in lista:
                if (e.get("rfc") or "").upper() == rfc and not e.get("nombre"):
                    e["nombre"] = nombre
        # con e.firma la empresa ya existe por su credencial; la lista manual no duplica
    elif not any(e["rfc"] == rfc and e["efirma"] for e in sat_empresas(db, tenant)):
        lista.append({"rfc": rfc, "nombre": nombre})
    cfg["sat_empresas"] = lista
    tenant.config = cfg
    flag_modified(tenant, "config")
    if plazo_dias is not None:
        _guardar_plazo(tenant, rfc, plazo_dias)
    db.flush()


class EmpresaBody(BaseModel):
    rfc: str
    nombre: str = ""
    plazo_dias: int = Field(SAT_PLAZO_DEFAULT, ge=1, le=365)


class EmpresaCambioBody(BaseModel):
    nombre: str | None = None
    plazo_dias: int | None = Field(None, ge=1, le=365)


@router.post("/v1/sat/empresas", status_code=201)
def sat_agregar_empresa(
    body: EmpresaBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Registra una empresa (razón social) del negocio por su RFC, sin e.firma.
    Sirve para clasificar XML subidos a mano; la descarga automática del SAT
    necesita además su e.firma."""
    rfc = _rfc_valido(body.rfc)
    _registrar_empresa_manual(db, tenant, rfc, body.nombre.strip(), body.plazo_dias)
    audit.record(
        db, tenant_id=tenant.id, action="sat.empresa.agregar",
        entity_type="integration", entity_id=rfc, principal=actor,
    )
    db.flush()
    return {"empresas": sat_empresas(db, tenant), "maximo": SAT_MAX_EMPRESAS}


@router.patch("/v1/sat/empresas/{rfc}")
def sat_cambiar_empresa(
    rfc: str,
    body: EmpresaCambioBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Ajusta el plazo estimado del RFC. No modifica facturas ya importadas."""
    rfc = _rfc_valido(rfc)
    if rfc not in {e["rfc"] for e in sat_empresas(db, tenant)}:
        raise HTTPException(status_code=404, detail="Esa empresa no está registrada.")
    if body.plazo_dias is not None:
        _guardar_plazo(tenant, rfc, body.plazo_dias)
    if body.nombre is not None:
        cfg = dict(tenant.config or {})
        lista = [dict(e) for e in cfg.get("sat_empresas") or []]
        for e in lista:
            if (e.get("rfc") or "").upper() == rfc:
                e["nombre"] = body.nombre.strip()
        cfg["sat_empresas"] = lista
        tenant.config = cfg
        flag_modified(tenant, "config")
    audit.record(
        db, tenant_id=tenant.id, action="sat.empresa.cambiar",
        entity_type="integration", entity_id=rfc, principal=actor,
        after={
            k: v
            for k, v in {
                "nombre": body.nombre.strip() if body.nombre is not None else None,
                "plazo_dias": body.plazo_dias,
            }.items()
            if v is not None
        },
    )
    db.flush()
    return {"empresas": sat_empresas(db, tenant), "maximo": SAT_MAX_EMPRESAS}


@router.delete("/v1/sat/empresas/{rfc}")
def sat_quitar_empresa(
    rfc: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Quita una empresa registrada a mano. Si tiene e.firma conectada, primero
    se borra la e.firma (así el dueño no pierde una credencial sin querer)."""
    rfc = _rfc_valido(rfc)
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == f"{SAT_EFIRMA_PREFIX}{rfc}",
        )
    )
    if row is not None:
        raise HTTPException(
            status_code=409,
            detail="Esa empresa tiene su e.firma conectada. Borra primero la e.firma.",
        )
    cfg = dict(tenant.config or {})
    lista = [e for e in cfg.get("sat_empresas") or [] if (e.get("rfc") or "").upper() != rfc]
    cfg["sat_empresas"] = lista
    plazos = dict(cfg.get("sat_plazos") or {})
    plazos.pop(rfc, None)
    cfg["sat_plazos"] = plazos
    tenant.config = cfg
    flag_modified(tenant, "config")
    audit.record(
        db, tenant_id=tenant.id, action="sat.empresa.quitar",
        entity_type="integration", entity_id=rfc, principal=actor,
    )
    db.flush()
    return {"empresas": sat_empresas(db, tenant), "maximo": SAT_MAX_EMPRESAS}


@router.post("/v1/sat/efirma", status_code=201)
def sat_conectar_efirma(
    cer: UploadFile = File(...),
    key: UploadFile = File(...),
    password: str = Form(...),
    plazo_dias: int = Form(SAT_PLAZO_DEFAULT, ge=1, le=365),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Conecta la e.firma de UNA empresa del negocio (hasta 3). Se valida ANTES
    de guardar: que abra con esa contraseña, que sea FIEL y no CSD (la Descarga
    Masiva exige e.firma) y que esté vigente. Los tres archivos se cifran juntos
    (Fernet) en una fila por RFC; jamás se guardan en claro ni salen por la API.
    La respuesta y la auditoría llevan solo lo público: RFC, titular, vigencia."""
    cer_bytes = cer.file.read()
    key_bytes = key.file.read()
    try:
        info = validar_efirma(cer_bytes, key_bytes, password)
    except SatCredencialInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:  # falta satcfdi en este entorno
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _tope_empresas(db, tenant, info["rfc"])
    cred.set_credential(
        db,
        tenant.id,
        f"{SAT_EFIRMA_PREFIX}{info['rfc']}",
        {
            # Secretos (van cifrados): los archivos en base64 y la contraseña.
            "cer": base64.b64encode(cer_bytes).decode(),
            "key": base64.b64encode(key_bytes).decode(),
            "password": password,
            # Público (lo único que la UI puede enseñar).
            **info,
        },
    )
    # Si el RFC estaba declarado a mano, la credencial lo cubre: sin duplicado.
    cfg = dict(tenant.config or {})
    manuales = [
        e for e in cfg.get("sat_empresas") or []
        if (e.get("rfc") or "").upper() != info["rfc"]
    ]
    cfg["sat_empresas"] = manuales
    tenant.config = cfg
    flag_modified(tenant, "config")
    _guardar_plazo(tenant, info["rfc"], plazo_dias)
    audit.record(
        db, tenant_id=tenant.id, action="sat.efirma.conectar",
        entity_type="integration", entity_id=info["rfc"], principal=actor,
        after=info,  # rfc/titular/vigencia; nunca la llave ni la contraseña
    )
    db.flush()
    return {"empresa": {**info, "efirma": True}, "maximo": SAT_MAX_EMPRESAS}


@router.post("/v1/sat/efirma/{rfc}/probar")
def sat_probar_efirma(
    rfc: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Autentica contra el SAT sin solicitar ni descargar CFDIs."""
    rfc = _rfc_valido(rfc)
    provider = f"{SAT_EFIRMA_PREFIX}{rfc}"
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == provider,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Esa empresa no tiene e.firma guardada.")
    try:
        datos = cred.get_credential(db, tenant.id, provider)
        if not datos:
            raise RuntimeError("No se pudo abrir la e.firma guardada.")
        resultado = SatDescargaClient(
            base64.b64decode(datos["cer"]),
            base64.b64decode(datos["key"]),
            datos["password"],
        ).probar()
    except Exception as exc:  # noqa: BLE001
        row.status = "error"
        row.last_test_at = datetime.now(timezone.utc)
        row.last_error = str(exc)
        db.flush()
        raise HTTPException(
            status_code=502,
            detail=f"El SAT no aceptó la e.firma de {rfc}: {exc}",
        ) from exc
    row.status = "connected"
    row.last_test_at = datetime.now(timezone.utc)
    row.last_error = None
    audit.record(
        db, tenant_id=tenant.id, action="sat.efirma.probar",
        entity_type="integration", entity_id=rfc, principal=actor,
        after={"ok": True, "rfc": rfc},
    )
    db.flush()
    return resultado


@router.delete("/v1/sat/efirma/{rfc}")
def sat_borrar_efirma(
    rfc: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Borra la e.firma de esa empresa, de verdad: desaparece la fila cifrada.
    La bóveda y la cartera ya descargadas se quedan (son datos del negocio)."""
    rfc = _rfc_valido(rfc)
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == f"{SAT_EFIRMA_PREFIX}{rfc}",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Esa empresa no tiene e.firma guardada.")
    db.delete(row)
    cfg = dict(tenant.config or {})
    plazos = dict(cfg.get("sat_plazos") or {})
    plazos.pop(rfc, None)
    cfg["sat_plazos"] = plazos
    tenant.config = cfg
    flag_modified(tenant, "config")
    audit.record(
        db, tenant_id=tenant.id, action="sat.efirma.borrar",
        entity_type="integration", entity_id=rfc, principal=actor,
    )
    db.flush()
    return {"empresas": sat_empresas(db, tenant), "maximo": SAT_MAX_EMPRESAS}


def _cartera_por_empresa(db, tenant: Tenant, rfcs: list[str]) -> dict:
    """Totales de cartera abierta por empresa (meta.empresa_rfc) y todo junto.
    Lo intercompañía nunca llega aquí: el importador no lo mete a cartera."""
    abiertas = db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.status == "open")
    ).all()
    por_rfc = {rfc: {"rfc": rfc, "abiertas": 0, "total": 0.0} for rfc in rfcs}
    todo = {"abiertas": 0, "total": 0.0}
    for inv in abiertas:
        monto = float(inv.amount or 0)
        todo["abiertas"] += 1
        todo["total"] += monto
        rfc = (inv.meta or {}).get("empresa_rfc")
        if rfc in por_rfc:
            por_rfc[rfc]["abiertas"] += 1
            por_rfc[rfc]["total"] += monto
    return {"por_empresa": list(por_rfc.values()), "todo_junto": todo}


@router.get("/v1/sat/estado")
def sat_estado(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """El estado de la bóveda: empresas (hasta 3), sincronización por RFC, conteos
    de la bóveda y la cartera por empresa o todo junto. Sin secretos: de la
    e.firma solo se dice que existe y hasta cuándo es vigente."""
    empresas = sat_empresas(db, tenant)
    estado_sync = (tenant.config or {}).get("sat_descarga") or {}
    for e in empresas:
        st = estado_sync.get(e["rfc"]) or {}
        e["sync"] = {
            scope: {
                "ultima_fecha": (st.get(scope) or {}).get("ultima_fecha"),
                "solicitud_pendiente": bool((st.get(scope) or {}).get("solicitud")),
            }
            for scope in ("emitidas", "recibidas")
        }
    filas = db.scalars(
        select(CfdiBoveda).where(CfdiBoveda.tenant_id == tenant.id)
    ).all()
    boveda = {
        "total": len(filas),
        "emitidas": sum(1 for f in filas if f.direccion == "emitida"),
        "recibidas": sum(1 for f in filas if f.direccion == "recibida"),
        "intercompania": sum(1 for f in filas if f.direccion == "intercompania"),
        "desconocida": sum(1 for f in filas if f.direccion == "desconocida"),
    }
    return {
        "empresas": empresas,
        "maximo": SAT_MAX_EMPRESAS,
        "boveda": boveda,
        "cartera": _cartera_por_empresa(db, tenant, [e["rfc"] for e in empresas]),
    }


@router.get("/v1/sat/boveda")
def sat_boveda(
    rfc: str = "",
    direccion: str = "",
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """La bóveda, filtrable por empresa (RFC, como emisor o receptor) y por
    dirección. Devuelve los datos del comprobante, nunca el XML completo (ese
    se descarga por pieza cuando exista esa vista)."""
    q = select(CfdiBoveda).where(CfdiBoveda.tenant_id == tenant.id)
    if direccion:
        q = q.where(CfdiBoveda.direccion == direccion)
    filas = db.scalars(q.order_by(CfdiBoveda.fecha.desc()).limit(2000)).all()
    if rfc:
        rfc = rfc.strip().upper()
        filas = [f for f in filas if rfc in (f.rfc_emisor, f.rfc_receptor)]
    total = sum(Decimal(str(f.total)) for f in filas if f.total is not None)
    return {
        "cfdis": [
            {
                "uuid": f.uuid,
                "tipo": f.tipo,
                "metodo_pago": f.metodo_pago,
                "folio": f.folio,
                "fecha": f.fecha,
                "rfc_emisor": f.rfc_emisor,
                "nombre_emisor": f.nombre_emisor,
                "rfc_receptor": f.rfc_receptor,
                "nombre_receptor": f.nombre_receptor,
                "total": float(f.total) if f.total is not None else None,
                "moneda": f.moneda,
                "direccion": f.direccion,
                "source": f.source,
                "invoice_id": f.invoice_id,
            }
            for f in filas
        ],
        "count": len(filas),
        "suma_total": float(total),
    }
