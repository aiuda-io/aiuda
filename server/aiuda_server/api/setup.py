"""El asistente de primer arranque: aiuda se configura solo hasta donde puede.

La idea: quien abre la app no tiene por qué saber qué es Ollama, un endpoint o
una API key. Este router MIRA la computadora (¿hay un modelo local corriendo?,
¿hay wacli?, ¿ya hay datos?) y le dice a la consola qué ofrecer y en qué orden,
en palabras del dueño de un negocio.

Nada aquí decide por el usuario: propone el camino más corto y él elige.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from aiuda_core.config import settings
from aiuda_core.engine.maquina import (
    descargar_modelo,
    detectar_maquina,
    progreso_descarga,
)
from aiuda_core.engine.openai_compat import DEFAULT_BASE_URL
from aiuda_core.engine.provider import credential_from_config, credential_from_store
from aiuda_core.models import Ayudante, Customer, IntegrationCredential, Invoice, Tenant
from aiuda_server.api.deps import DEFAULT_WORKSPACE_NAME, get_db, get_tenant

router = APIRouter()

# Modelos locales que sabemos que hacen tool calling decente. El orden es la
# recomendación: el primero que el usuario tenga instalado es el que sugerimos.
MODELOS_SUGERIDOS = ("llama3.1", "qwen2.5", "qwen2.5-coder", "mistral-nemo", "firefunction-v2")


def _ollama_modelos(base_url: str = DEFAULT_BASE_URL) -> list[str] | None:
    """Modelos instalados en el Ollama de esta computadora. None = no responde."""
    raiz = base_url.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{raiz}/api/tags", timeout=2) as res:
            datos = json.loads(res.read() or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    return [m.get("name", "") for m in datos.get("models", []) if m.get("name")]


def _sugerir(modelos: list[str]) -> str | None:
    """El modelo más recomendable de los que YA tiene instalados."""
    for preferido in MODELOS_SUGERIDOS:
        for m in modelos:
            if m.split(":")[0] == preferido:
                return m
    return modelos[0] if modelos else None


@router.get("/v1/setup/estado")
def estado(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    """Qué encontró aiuda en esta computadora y qué falta para trabajar."""
    config = tenant.config or {}

    ia = credential_from_store(db, tenant.id) or credential_from_config(config)
    modelos = _ollama_modelos()
    fuentes = list(
        db.scalars(
            select(IntegrationCredential.provider).where(
                IntegrationCredential.tenant_id == tenant.id,
                IntegrationCredential.provider != "ia",
                IntegrationCredential.status != "disabled",
            )
        ).all()
    )
    clientes = db.scalar(
        select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant.id)
    )
    facturas = db.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tenant.id)
    )
    ayudantes = db.scalar(
        select(func.count()).select_from(Ayudante).where(Ayudante.tenant_id == tenant.id)
    )

    # El negocio está listo si TIENE nombre propio, no si el asistente anotó que pasó
    # por ahí. La bandera `setup_negocio` solo la escribe el propio asistente, así que
    # un workspace armado por cualquier otra vía (un script, la API, un respaldo
    # restaurado) se quedaba bloqueado para siempre preguntando su nombre con el nombre
    # ya escrito en el campo. Las otras tres secciones ya se derivaban de la realidad;
    # esta era la única que se auto-reportaba.
    negocio_listo = bool(config.get("setup_negocio")) or (
        bool((tenant.name or "").strip()) and tenant.name != DEFAULT_WORKSPACE_NAME
    )
    datos_listo = bool(fuentes) or bool(clientes) or bool(facturas)
    ayudantes_listo = bool(ayudantes)
    # Y si ya no queda nada que preguntar, el asistente no tiene por qué salir. Un
    # negocio con nombre, IA conectada, datos y un ayudante ya terminó, lo haya
    # marcado o no.
    terminado = bool(config.get("setup_terminado")) or (
        negocio_listo and ia is not None and datos_listo and ayudantes_listo
    )

    return {
        # Lo primero que se pregunta: cómo se llama el negocio.
        "negocio": {"nombre": tenant.name, "listo": negocio_listo},
        # La IA: si hay un modelo local corriendo, es el camino sin fricción.
        "ia": {
            "conectada": ia is not None,
            "proveedor": ia.name if ia else None,
            "ollama_corriendo": modelos is not None,
            "modelos_locales": modelos or [],
            "modelo_sugerido": _sugerir(modelos or []),
            "base_url_local": DEFAULT_BASE_URL,
            "env_key": bool(settings.anthropic_api_key),
        },
        # Tus datos: una fuente conectada o un archivo importado, lo que sea.
        "datos": {
            "fuentes": fuentes,
            "clientes": int(clientes or 0),
            "facturas": int(facturas or 0),
            "listo": datos_listo,
        },
        "ayudantes": {"total": int(ayudantes or 0), "listo": ayudantes_listo},
        # Extras que aiuda detecta pero no exige.
        "extras": {"wacli": shutil.which(settings.wacli_bin) is not None},
        "terminado": terminado,
    }


@router.get("/v1/setup/maquina")
def maquina() -> dict:
    """Qué computadora es esta y qué IA local le cabe.

    No toca la base ni el workspace: es una foto del equipo del dueño (chip,
    memoria, Ollama, modelos bajados, CLIs de IA). Por eso puede contestar antes
    de que exista un solo dato en aiuda.
    """
    return detectar_maquina()


class ModeloBody(BaseModel):
    modelo: str


@router.post("/v1/setup/modelo/descargar", status_code=202)
def descargar_modelo_local(body: ModeloBody) -> dict:
    """Baja un modelo con `ollama pull` en segundo plano. 202 y a preguntar el progreso."""
    try:
        return descargar_modelo(body.modelo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/v1/setup/modelo/progreso")
def progreso_modelo_local(modelo: str = Query(...)) -> dict:
    """Cómo va esa descarga: descargando | listo | error | desconocido."""
    return progreso_descarga(modelo)


@router.post("/v1/setup/red/buscar")
def buscar_ia_en_la_red() -> dict:
    """Busca una IA compartida en la red local (la Mac buena de la oficina).

    Es POST y no GET a propósito: barrer la red del usuario es una ACCIÓN que él
    pide, no algo que aiuda haga sola al abrir. En macOS además dispara el
    permiso de red local, y eso debe pasar cuando él lo entiende.

    Tarda unos segundos (barrido de la subred). Devuelve lo encontrado con el
    nombre del equipo y sus modelos, listo para conectar de un clic.
    """
    from aiuda_core.engine.red import buscar, ip_local

    propia = ip_local()
    if propia is None:
        return {"mi_ip": None, "encontrados": [], "aviso": "Esta computadora no está en una red."}
    servidores = buscar()
    return {
        "mi_ip": propia,
        "encontrados": [s.como_dict() for s in servidores],
        # Honestidad: usar la IA de otra computadora significa que los datos del
        # negocio salen de esta máquina hacia esa. Se dice antes de conectar.
        "aviso": (
            "Si usas la IA de otra computadora, lo que tus ayudantes lean y redacten "
            "viaja a ese equipo por tu red. Se queda en tu oficina, pero ya no es solo "
            "esta máquina."
        ),
    }


class NegocioBody(BaseModel):
    nombre: str
    telefono: str | None = None


@router.put("/v1/setup/negocio")
def guardar_negocio(
    body: NegocioBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
) -> dict:
    """Paso 1: el nombre del negocio (y opcionalmente el WhatsApp del dueño)."""
    nombre = (body.nombre or "").strip()
    if nombre:
        tenant.name = nombre
    if body.telefono is not None:
        tenant.owner_phone = body.telefono.strip()
    tenant.config = {**(tenant.config or {}), "setup_negocio": True}
    db.add(tenant)
    db.flush()
    return {"nombre": tenant.name}


@router.post("/v1/setup/terminar")
def terminar(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    """El dueño cerró el asistente: no vuelve a salir de arranque."""
    tenant.config = {**(tenant.config or {}), "setup_terminado": True}
    db.add(tenant)
    db.flush()
    return {"terminado": True}
