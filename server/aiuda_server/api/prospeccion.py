"""Prospección con DENUE · INEGI: buscar negocios reales y cargarlos como prospectos.

El DENUE es el directorio público del INEGI (5.5M unidades económicas). Aquí se
consulta EN VIVO — buscar no guarda nada — y el dueño previsualiza, selecciona
y carga a su cartera. Cada prospecto cargado es un ``Customer kind='prospecto'``
con procedencia denue (``presence`` + ``meta.origen``), deduplicado contra la
cartera por referencia DENUE, teléfono normalizado (``match_key``) y nombre sin
acentos: cargar dos veces (o cargar un negocio que ya es cliente) NO duplica.

Contrato con INEGI (``Buscar/{condicion}/{lat,lng}/{radio_m}/{token}``):
  - radio máximo documentado: 5,000 m; la condición "todos" trae de todo.
  - token inválido: INEGI responde una línea de estado inválida ("HTTP/1.1 000")
    que httpx reporta como ``RemoteProtocolError`` (verificado en vivo 2026-07-07).
  - la respuesta con resultados es un arreglo JSON; su estructura documentada
    vive en ``core/tests/data/denue_buscar_contrato.json`` (pendiente de
    grabarla de una llamada real cuando el negocio tenga token).
"""

import unicodedata

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.denue import DenueClient, Negocio
from aiuda_core.engine.presence import add_presence
from aiuda_core.models import Customer, Tenant
from aiuda_core.phones import match_key

router = APIRouter()

RADIO_MIN_M = 100
RADIO_MAX_M = 5000  # máximo documentado por INEGI para Buscar


def _creds_denue(db, tenant: Tenant) -> dict | None:
    """Credenciales efectivas del DENUE para este negocio (cifradas → legado →
    settings), o ``None`` si no hay token por ninguna vía."""
    creds = cred.get_credential(db, tenant.id, "denue")
    return creds if creds and creds.get("token") else None


def _clave_nombre(nombre: str) -> str:
    """Clave de dedupe por nombre: sin acentos, minúsculas, espacios colapsados.
    El DENUE viene en MAYÚSCULAS sin acentos ("FERRETERIA LA CENTRAL"); el dueño
    captura "Ferretería La Central" — misma clave para ambos."""
    plano = unicodedata.normalize("NFKD", nombre or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(plano.lower().split())


def _indice_cartera(db, tenant_id: str):
    """Índices de dedupe sobre la cartera completa (clientes Y prospectos):
    por referencia DENUE ya cargada, por teléfono normalizado (``match_key``,
    tolera 10 dígitos vs 52/521), por nombre sin acentos, y el set de teléfonos
    exactos (la unicidad (tenant, phone) de la BD no perdona ni la basura)."""
    por_ref: dict[str, Customer] = {}
    por_tel: dict[str, Customer] = {}
    por_nombre: dict[str, Customer] = {}
    tel_exactos: set[str] = set()
    for c in db.scalars(select(Customer).where(Customer.tenant_id == tenant_id)):
        ref = ((c.presence or {}).get("denue") or {}).get("ref")
        if ref:
            por_ref.setdefault(str(ref), c)
        if c.phone:
            tel_exactos.add(c.phone)
        tel = match_key(c.phone)
        if tel:
            por_tel.setdefault(tel, c)
        clave = _clave_nombre(c.name)
        if clave:
            por_nombre.setdefault(clave, c)
    return por_ref, por_tel, por_nombre, tel_exactos


def _existente(indices, *, ref: str, telefono: str, nombre: str) -> Customer | None:
    """El registro de la cartera que ya ES este negocio, si lo hay. Orden:
    referencia DENUE (ya se cargó antes) → teléfono normalizado → nombre."""
    por_ref, por_tel, por_nombre, _ = indices
    if ref and str(ref) in por_ref:
        return por_ref[str(ref)]
    tel = match_key(telefono)
    if tel and tel in por_tel:
        return por_tel[tel]
    clave = _clave_nombre(nombre)
    if clave and clave in por_nombre:
        return por_nombre[clave]
    return None


@router.get("/v1/prospeccion/fuente")
def fuente_prospeccion(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Estado honesto de la fuente: sin token del INEGI no hay búsqueda. El
    token es gratuito (inegi.org.mx/app/api/denue) y se guarda en Integraciones."""
    return {
        "fuente": "denue",
        "nombre": "DENUE · INEGI",
        "conectada": _creds_denue(db, tenant) is not None,
    }


class BusquedaBody(BaseModel):
    condicion: str
    lat: float
    lng: float
    radio_m: int = 2500


def _buscar_denue(
    creds: dict, condicion: str, lat: float, lng: float, radio_m: int
) -> list[Negocio]:
    """Consulta real al INEGI. Función aparte para poder fingirla en pruebas."""
    return DenueClient(**cred.ctor_kwargs("denue", creds)).buscar(
        condicion, lat, lng, radio_m
    )


@router.post("/v1/prospeccion/buscar")
def buscar_prospectos(
    body: BusquedaBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Busca negocios en el DENUE por giro/palabra clave alrededor de un punto
    (los parámetros que la API pública soporta: condición + lat,lng + radio).
    No guarda nada: es la previsualización. Cada resultado dice si YA está en
    la cartera (``ya_registrado`` + ``cliente_id``) para no ofrecer duplicados."""
    condicion = body.condicion.strip()
    if not condicion:
        raise HTTPException(
            status_code=422, detail="Escribe un giro o palabra clave (o 'todos')."
        )
    creds = _creds_denue(db, tenant)
    if creds is None:
        raise HTTPException(
            status_code=409,
            detail="DENUE no está conectado. Guarda tu token gratuito del INEGI en Integraciones.",
        )
    radio_m = min(max(body.radio_m, RADIO_MIN_M), RADIO_MAX_M)
    try:
        negocios = _buscar_denue(creds, condicion, body.lat, body.lng, radio_m)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # INEGI responde 404 cuando la búsqueda no encuentra nada en esa zona.
            return {"total": 0, "resultados": []}
        raise HTTPException(
            status_code=502,
            detail=f"La fuente INEGI respondió {exc.response.status_code}. Intenta de nuevo en un momento.",
        )
    except httpx.RemoteProtocolError:
        # Token inválido: INEGI responde "HTTP/1.1 000" (verificado en vivo).
        raise HTTPException(
            status_code=502,
            detail="INEGI rechazó la consulta. Revisa que tu token del DENUE sea válido (Integraciones → DENUE · INEGI).",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo llegar al INEGI ({exc.__class__.__name__}). Revisa tu conexión e intenta de nuevo.",
        )
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="INEGI devolvió una respuesta que no se pudo leer. Intenta de nuevo.",
        )
    indices = _indice_cartera(db, tenant.id)
    resultados = []
    for n in negocios:
        existente = _existente(
            indices, ref=n.id, telefono=n.telefono, nombre=n.nombre or n.razon_social
        )
        resultados.append(
            {
                "id": n.id,
                "nombre": n.nombre or n.razon_social or "Negocio",
                "razon_social": n.razon_social,
                "actividad": n.actividad,
                "telefono": n.telefono,
                "correo": n.correo,
                "direccion": n.direccion,
                "contactable": n.contactable,
                "ya_registrado": existente is not None,
                "cliente_id": existente.id if existente is not None else None,
            }
        )
    return {"total": len(resultados), "resultados": resultados}


class NegocioBody(BaseModel):
    id: str = ""
    nombre: str = ""
    razon_social: str = ""
    actividad: str = ""
    telefono: str = ""
    correo: str = ""
    direccion: str = ""


class ImportarBody(BaseModel):
    negocios: list[NegocioBody]


@router.post("/v1/prospeccion/importar")
def importar_prospectos(
    body: ImportarBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Carga la selección a la cartera como prospectos con procedencia denue.
    Si el negocio YA está (por referencia DENUE, teléfono o nombre) no se
    duplica ni se degrada un cliente a prospecto: solo se le completa lo que
    falte (teléfono/correo/meta) y se le marca la presencia en DENUE."""
    if not body.negocios:
        raise HTTPException(status_code=422, detail="Selecciona al menos un negocio.")
    indices = _indice_cartera(db, tenant.id)
    por_ref, por_tel, por_nombre, tel_exactos = indices
    importados = ya_existian = omitidos = 0
    detalle = []
    for n in body.negocios:
        nombre = (n.nombre or n.razon_social or "").strip()
        if not nombre:
            omitidos += 1
            continue
        existente = _existente(indices, ref=n.id, telefono=n.telefono, nombre=nombre)
        if existente is not None:
            # RELLENA sin pisar (aiuda no es el maestro del directorio) y no
            # cambia el kind: un cliente no se degrada a prospecto.
            if n.telefono and not existente.phone and n.telefono not in tel_exactos:
                existente.phone = n.telefono
                tel_exactos.add(n.telefono)
            if n.correo and not existente.email:
                existente.email = n.correo
            meta_nueva = {
                "actividad": n.actividad,
                "direccion": n.direccion,
                "origen": "denue",
            }
            existente.meta = {**meta_nueva, **(existente.meta or {})}
            if n.id:
                add_presence(existente, "denue", str(n.id))
            db.add(existente)
            ya_existian += 1
            cliente, creado = existente, False
        else:
            # La unicidad (tenant, phone) es por cadena exacta: si un teléfono
            # corto/basura choca literal con uno ya guardado (y no dedupeó por
            # match_key), el prospecto entra sin teléfono en vez de tirar todo.
            telefono = n.telefono or None
            if telefono and telefono in tel_exactos:
                telefono = None
            cliente = Customer(
                tenant_id=tenant.id,
                name=nombre,
                phone=telefono,
                email=n.correo or None,
                kind="prospecto",
                meta={
                    "actividad": n.actividad,
                    "direccion": n.direccion,
                    "origen": "denue",
                },
                presence={"denue": {"ref": str(n.id)}} if n.id else {},
            )
            db.add(cliente)
            db.flush()  # id disponible para el detalle
            importados += 1
            creado = True
            # El recién creado entra a los índices: si la misma selección trae
            # el negocio dos veces (o dos con el mismo teléfono), no se duplica.
            if n.id:
                por_ref.setdefault(str(n.id), cliente)
            if telefono:
                tel_exactos.add(telefono)
            tel = match_key(telefono)
            if tel:
                por_tel.setdefault(tel, cliente)
            por_nombre.setdefault(_clave_nombre(nombre), cliente)
        detalle.append({"id": n.id, "cliente_id": cliente.id, "creado": creado})
    db.flush()
    return {
        "importados": importados,
        "ya_existian": ya_existian,
        "omitidos": omitidos,
        "total": len(body.negocios),
        "detalle": detalle,
    }
