"""Recados de CUA: la cola + el log de las misiones que los ayudantes corren en portales.

El dueño configura una misión una vez (eligiendo CUA como fuente de una capacidad) y aquí
ve el log: qué recado se encoló, si está corriendo, qué extrajo y la evidencia (capturas).
Nunca mira el navegador — todo es headless, en segundo plano.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.cua.fallback import (
    CUA_PORTALES_KEY,
    CUA_PORTALES_URL_KEY,
    CUA_TEMPLATES,
    PORTAL_PREFIX,
    borrar_sesion,
    ejecutar_recado,
    enqueue_cua_mission,
    portal_efectivo,
    portales_url,
    sesion_guardada_en,
    tiene_sesion,
)
from aiuda_core.cua.handoff import (
    cancelar_handoff,
    confirmar_handoff,
    estado_handoff_posible,
    iniciar_handoff,
    obtener,
)
from aiuda_core.cua.runner import PLANTILLAS
from aiuda_core.models import CuaMission, Tenant

router = APIRouter()

# Llave dentro de tenant.config donde viven las rutinas guardadas del dueño. Se
# persiste en el JSON del tenant (sin tabla nueva ni migración), igual que
# modo_sombra o active_agents.
RUTINAS_KEY = "rutinas_backoffice"


def _serialize(m: CuaMission, with_evidence: bool = False) -> dict:
    out = {
        "id": m.id,
        "capacidad": m.capacidad,
        "sistema": m.sistema,
        "status": m.status,
        "resumen": m.resumen or "",
        "data": m.data or {},
        "steps": m.steps or [],
        "error": m.error or "",
        "evidencia_capturas": len(m.evidence or []),
        "createdAt": m.created_at.isoformat() if m.created_at else None,
        "startedAt": m.started_at.isoformat() if m.started_at else None,
        "finishedAt": m.finished_at.isoformat() if m.finished_at else None,
    }
    if with_evidence:
        # base64 de PNG; el front las pinta como data:image/png;base64,...
        out["evidencia"] = m.evidence or []
    return out


def run_recado_blocking(recado_id: str) -> None:
    """Corre un recado encolado en su propia sesión (BackgroundTask; abre navegador headless)."""
    from aiuda_core.db import session_scope

    with session_scope() as session:
        recado = session.get(CuaMission, recado_id)
        if recado is not None and recado.status == "queued":
            ejecutar_recado(session, recado)


@router.get("/v1/cua/estado")
def estado(db=Depends(get_db), tenant: Tenant = Depends(get_tenant)) -> dict:
    """Estado HONESTO de la oficina: ¿este servidor tiene el navegador del asistente
    (extra `cua` + Chromium) y el tenant tiene credencial de IA? La UI lo muestra tal
    cual; sin esto las tareas quedan en 'No pudo' con la razón."""
    from aiuda_core.cua.computer import estado_navegador
    from aiuda_core.engine.provider import resolve_credential

    navegador_listo, detalle = estado_navegador()
    credencial = resolve_credential(session=db, tenant_id=tenant.id) is not None
    handoff_posible, handoff_detalle = estado_handoff_posible()
    return {
        "navegador_listo": navegador_listo,
        "navegador_detalle": detalle,
        "credencial_ia": credencial,
        "listo": navegador_listo and credencial,
        # ¿Esta máquina puede abrir una ventana para que el dueño entre al portal él mismo?
        "handoff_posible": handoff_posible,
        "handoff_detalle": handoff_detalle,
    }


def _capacidad_publica(tenant: Tenant, capacidad: str, sistema: str, objetivo: str) -> dict:
    """Un portal como lo ve el lanzador: su objetivo, si ya tiene dirección y si su acceso
    (login) ya quedó conectado por el handoff."""
    portal = portal_efectivo(tenant, capacidad)
    return {
        "capacidad": capacidad,
        "sistema": sistema,
        "objetivo": objetivo,
        "url": (portal or {}).get("url") or "",
        "url_configurada": bool((portal or {}).get("url")),
        "editable": capacidad.startswith(PORTAL_PREFIX),
        "tiene_sesion": tiene_sesion(tenant, capacidad),
        "sesion_guardada_en": sesion_guardada_en(tenant, capacidad),
    }


@router.get("/v1/cua/capacidades")
def capacidades(tenant: Tenant = Depends(get_tenant)) -> list[dict]:
    """Portales disponibles para el lanzador: los tres built-in (SAT, banca, tribunal) más
    los que el dueño registró por URL. Cada uno dice su objetivo, si ya tiene dirección y
    si su acceso ya quedó conectado (handoff de login)."""
    out = [
        _capacidad_publica(
            tenant, cap, PLANTILLAS[tmpl].sistema, PLANTILLAS[tmpl].objetivo
        )
        for cap, tmpl in CUA_TEMPLATES.items()
    ]
    for p in portales_url(tenant):
        out.append(
            _capacidad_publica(
                tenant,
                f"{PORTAL_PREFIX}{p['id']}",
                p.get("nombre") or "Portal",
                p.get("notas") or "Lo que le pidas al despachar.",
            )
        )
    return out


@router.get("/v1/cua/misiones")
def listar(db=Depends(get_db), tenant: Tenant = Depends(get_tenant)) -> list[dict]:
    """Los recados del tenant, del más reciente al más viejo (sin evidencia, para ir ligero)."""
    rows = db.scalars(
        select(CuaMission)
        .where(CuaMission.tenant_id == tenant.id)
        .order_by(CuaMission.created_at.desc())
        .limit(50)
    ).all()
    return [_serialize(m) for m in rows]


@router.get("/v1/cua/misiones/{mission_id}")
def detalle(
    mission_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    m = db.get(CuaMission, mission_id)
    if m is None or m.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Recado no encontrado")
    return _serialize(m, with_evidence=True)


class NuevoRecado(BaseModel):
    capacidad: str
    # Indicación específica del dueño para esta corrida (opcional). Afina el objetivo
    # por defecto del trabajador; se guarda y se le pasa al agente al operar el portal.
    instruccion: str | None = None


@router.post("/v1/cua/misiones", status_code=201)
def encolar(
    body: NuevoRecado,
    background: BackgroundTasks,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    """Encola un trabajo y lo corre en segundo plano (headless). Devuelve el trabajo en
    cola; el log se actualiza solo cuando el asistente termina."""
    if portal_efectivo(tenant, body.capacidad) is None:
        raise HTTPException(status_code=400, detail="Ese portal no está disponible.")
    instruccion = (body.instruccion or "").strip() or None
    recado = enqueue_cua_mission(db, tenant, body.capacidad, instruccion=instruccion)
    background.add_task(run_recado_blocking, recado.id)
    return _serialize(recado)


# ---------- Rutinas guardadas: una tarea de portal que el dueño repite ----------
#
# Una "rutina" es una tarea de backoffice guardada con nombre para re-correrla con
# un clic (como los comandos guardados de un editor). No es más que una capacidad +
# una instrucción en lenguaje natural; correrla reusa el mismo encolar de arriba.
# Vive en tenant.config[RUTINAS_KEY] (sin tabla nueva ni migración).


def _rutinas(tenant: Tenant) -> list[dict]:
    return list((tenant.config or {}).get(RUTINAS_KEY) or [])


def _guardar_rutinas(db, tenant: Tenant, rutinas: list[dict]) -> None:
    # Las columnas JSON no trackean mutación in-place: reasignar siempre para que
    # SQLAlchemy detecte el cambio y lo persista.
    tenant.config = {**(tenant.config or {}), RUTINAS_KEY: rutinas}
    db.add(tenant)


class NuevaRutina(BaseModel):
    nombre: str
    capacidad: str
    instruccion: str | None = None


@router.get("/v1/cua/rutinas")
def listar_rutinas(tenant: Tenant = Depends(get_tenant)) -> list[dict]:
    """Las rutinas guardadas del tenant, de la más reciente a la más vieja."""
    return sorted(_rutinas(tenant), key=lambda r: r.get("creado") or "", reverse=True)


@router.post("/v1/cua/rutinas", status_code=201)
def guardar_rutina(
    body: NuevaRutina,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    """Guarda una tarea de portal como rutina reutilizable (nombre + portal +
    instrucción). Devuelve la rutina creada."""
    nombre = (body.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Ponle un nombre a la rutina.")
    portal = portal_efectivo(tenant, body.capacidad)
    if portal is None:
        raise HTTPException(status_code=400, detail="Ese portal no está disponible.")
    rutina = {
        "id": uuid.uuid4().hex[:12],
        "nombre": nombre,
        "capacidad": body.capacidad,
        "sistema": portal["sistema"],
        "instruccion": (body.instruccion or "").strip(),
        "creado": datetime.now(timezone.utc).isoformat(),
    }
    _guardar_rutinas(db, tenant, [*_rutinas(tenant), rutina])
    return rutina


@router.delete("/v1/cua/rutinas/{rutina_id}", status_code=204)
def borrar_rutina(
    rutina_id: str,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> None:
    rutinas = _rutinas(tenant)
    quedan = [r for r in rutinas if r.get("id") != rutina_id]
    if len(quedan) == len(rutinas):
        raise HTTPException(status_code=404, detail="Esa rutina no existe.")
    _guardar_rutinas(db, tenant, quedan)


# ---------- Portales a la medida: el dueño registra a qué sitio entrar ----------
#
# Cualquier sitio suyo (su banco, un proveedor, un municipio) que no sea de los tres
# built-in. Se referencia como capacidad "portal:<id>" y aparece en el lanzador junto a
# los built-in. Vive en tenant.config[CUA_PORTALES_URL_KEY] (sin tabla nueva).


def _guardar_portales(db, tenant: Tenant, portales: list[dict]) -> None:
    tenant.config = {**(tenant.config or {}), CUA_PORTALES_URL_KEY: portales}
    flag_modified(tenant, "config")
    db.add(tenant)


def _url_limpia(url: str) -> str:
    u = (url or "").strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="La dirección del portal debe empezar con http:// o https://.",
        )
    return u


class NuevoPortal(BaseModel):
    nombre: str
    url: str
    notas: str | None = None


@router.get("/v1/cua/portales")
def listar_portales(tenant: Tenant = Depends(get_tenant)) -> list[dict]:
    """Los portales a la medida que el dueño registró."""
    return portales_url(tenant)


@router.post("/v1/cua/portales", status_code=201)
def crear_portal(
    body: NuevoPortal, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    """Registra un portal por URL. Aparece en el lanzador como un destino más; su acceso
    se conecta con el handoff de login."""
    nombre = (body.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Ponle un nombre al portal.")
    url = _url_limpia(body.url)
    portal = {
        "id": uuid.uuid4().hex[:12],
        "nombre": nombre,
        "url": url,
        "notas": (body.notas or "").strip(),
        "creado": datetime.now(timezone.utc).isoformat(),
    }
    _guardar_portales(db, tenant, [*portales_url(tenant), portal])
    return portal


@router.delete("/v1/cua/portales/{portal_id}", status_code=204)
def borrar_portal(
    portal_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> None:
    portales = portales_url(tenant)
    quedan = [p for p in portales if p.get("id") != portal_id]
    if len(quedan) == len(portales):
        raise HTTPException(status_code=404, detail="Ese portal no existe.")
    _guardar_portales(db, tenant, quedan)
    # Olvida también su acceso guardado (la sesión ya no sirve para nada).
    borrar_sesion(db, tenant, f"{PORTAL_PREFIX}{portal_id}")


class UrlBuiltin(BaseModel):
    url: str


@router.put("/v1/cua/portales/builtin/{capacidad}")
def set_url_builtin(
    capacidad: str,
    body: UrlBuiltin,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    """Fija la dirección de un portal built-in (la banca o el tribunal de tu negocio, que
    solo tú sabes). Se guarda por capacidad en tenant.config[CUA_PORTALES_KEY]."""
    if capacidad not in CUA_TEMPLATES:
        raise HTTPException(status_code=404, detail="Ese portal no existe.")
    url = _url_limpia(body.url)
    mapa = dict((tenant.config or {}).get(CUA_PORTALES_KEY) or {})
    mapa[capacidad] = url
    tenant.config = {**(tenant.config or {}), CUA_PORTALES_KEY: mapa}
    flag_modified(tenant, "config")
    db.add(tenant)
    plantilla = CUA_TEMPLATES[capacidad]
    return _capacidad_publica(
        tenant, capacidad, PLANTILLAS[plantilla].sistema, PLANTILLAS[plantilla].objetivo
    )


# ---------- Handoff de login: el dueño entra, no nosotros ----------
#
# Abre una ventana VISIBLE del navegador (en esta máquina) para que el dueño entre al
# portal él mismo; al confirmar, se guarda su sesión ya autenticada (cifrada) y el
# asistente la reusa. Nunca tocamos su contraseña. Solo posible donde hay navegador y
# pantalla (la máquina del dueño); en la nube el gate corta honesto.


class NuevaSesion(BaseModel):
    capacidad: str


@router.post("/v1/cua/sesion", status_code=201)
async def iniciar_sesion(
    body: NuevaSesion, tenant: Tenant = Depends(get_tenant)
) -> dict:
    """Abre la ventana para que el dueño entre al portal. Devuelve la sesión de handoff a
    la que el front le sigue el estado."""
    posible, detalle = estado_handoff_posible()
    if not posible:
        raise HTTPException(status_code=409, detail=detalle)
    portal = portal_efectivo(tenant, body.capacidad)
    if portal is None:
        raise HTTPException(status_code=400, detail="Ese portal no está disponible.")
    if not portal["url"]:
        raise HTTPException(
            status_code=400, detail="Primero ponle la dirección al portal."
        )
    sesion = iniciar_handoff(tenant.id, body.capacidad, portal["sistema"], portal["url"])
    return sesion.to_dict()


@router.get("/v1/cua/sesion/{session_id}")
def estado_sesion(session_id: str, tenant: Tenant = Depends(get_tenant)) -> dict:
    s = obtener(session_id, tenant.id)
    if s is None:
        raise HTTPException(status_code=404, detail="Esa sesión no existe.")
    return s.to_dict()


@router.post("/v1/cua/sesion/{session_id}/confirmar")
async def confirmar_sesion(
    session_id: str, tenant: Tenant = Depends(get_tenant)
) -> dict:
    """El dueño ya entró: captura y guarda su sesión autenticada."""
    s = obtener(session_id, tenant.id)
    if s is None:
        raise HTTPException(status_code=404, detail="Esa sesión no existe.")
    confirmar_handoff(s)
    return s.to_dict()


@router.post("/v1/cua/sesion/{session_id}/cancelar")
async def cancelar_sesion(
    session_id: str, tenant: Tenant = Depends(get_tenant)
) -> dict:
    """El dueño desistió: cierra la ventana sin guardar nada."""
    s = obtener(session_id, tenant.id)
    if s is None:
        raise HTTPException(status_code=404, detail="Esa sesión no existe.")
    cancelar_handoff(s)
    return s.to_dict()


class OlvidarSesion(BaseModel):
    capacidad: str


@router.post("/v1/cua/sesion/olvidar", status_code=204)
def olvidar_sesion(
    body: OlvidarSesion, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> None:
    """Borra el acceso guardado de un portal (para reconectarlo desde cero)."""
    borrar_sesion(db, tenant, body.capacidad)
