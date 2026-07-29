"""Fallback a CUA: cuando una capacidad no tiene conector API, un Computer Use Agent
opera el portal web como lo haría un humano. El dueño lo elige como cualquier otra
fuente ("de dónde lee" = CUA) y el motor de sync enruta aquí. Solo-lectura, con evidencia.

El runner corre de verdad con un Chromium local (extra `cua`, Playwright) y la IA del
tenant. Honesto en cada faltante: sin el extra instalado, sin credencial de IA o sin la
URL del portal, el recado queda `failed` con la razón exacta — nunca inventa datos. La
URL del portal la aporta el tenant (`tenant.config["cua_portales"]`, por capacidad),
porque la banca o el juzgado de cada negocio son suyos. Ver docs/CUA.md.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import replace
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from aiuda_core.cua.mission import Mission, MissionResult
from aiuda_core.cua.runner import PLANTILLAS
from aiuda_core.engine.sync import SyncReport, _parse_date
from aiuda_core.models import CuaMission, Payment, Tenant

logger = logging.getLogger("aiuda.cua")

# Capturas guardadas por recado (base64). Acotado: la evidencia es para revisar, no un video.
_MAX_EVIDENCIA = 8

# La clave de fuente que el dueño elige en "de dónde lee" para caer en un CUA.
CUA_FUENTE = "cua"

# capacidad -> plantilla de misión CUA (el portal que opera el agente de cómputo).
CUA_TEMPLATES: dict[str, str] = {
    "cfdi": "sat_cfdi_recibidos",
    "confirmacion_pago": "banca_movimientos",
    "expedientes": "tribunal_acuerdos",
}

# Llave en tenant.config con la URL del portal de cada capacidad (sin migración):
# {"confirmacion_pago": "https://…"}. La banca/el juzgado de cada negocio son suyos;
# la plantilla solo trae URL cuando el portal es único (el del SAT).
CUA_PORTALES_KEY = "cua_portales"

# Portales a la medida que el dueño registra por URL (lista de {id, nombre, url, notas}).
# No están atados a las 3 capacidades built-in: son cualquier sitio suyo (su banco, un
# proveedor, un municipio). Se referencian como capacidad "portal:<id>".
CUA_PORTALES_URL_KEY = "cua_portales_url"
PORTAL_PREFIX = "portal:"

# Sesiones autenticadas guardadas por capacidad (del handoff de login), CIFRADAS:
# {capacidad: {cifrada, version, guardada_en}}. El asistente las reusa para arrancar
# ya logueado sin que nadie más que el dueño toque su contraseña.
CUA_SESIONES_KEY = "cua_sesiones"


def portales_url(tenant: Tenant) -> list[dict]:
    """Los portales a la medida que el dueño registró (lista de dicts)."""
    return list((tenant.config or {}).get(CUA_PORTALES_URL_KEY) or [])


def portal_por_id(tenant: Tenant, portal_id: str) -> dict | None:
    return next((p for p in portales_url(tenant) if p.get("id") == portal_id), None)


def portal_efectivo(tenant: Tenant, capacidad: str) -> dict | None:
    """El portal detrás de una capacidad, unificando los dos tipos que hay:
      - built-in (cfdi/confirmacion_pago/expedientes): plantilla + URL del tenant.
      - a la medida ("portal:<id>"): el que el dueño registró por URL.
    Devuelve {sistema, url, notas, plantilla} o None si la capacidad no existe. Es la
    fuente única de verdad para encolar, armar la misión y el handoff."""
    if capacidad.startswith(PORTAL_PREFIX):
        p = portal_por_id(tenant, capacidad[len(PORTAL_PREFIX):])
        if not p:
            return None
        return {
            "sistema": p.get("nombre") or "Portal",
            "url": p.get("url") or "",
            "notas": p.get("notas") or "",
            "plantilla": None,
        }
    tmpl = CUA_TEMPLATES.get(capacidad)
    if not tmpl:
        return None
    m = PLANTILLAS[tmpl]
    url = ((tenant.config or {}).get(CUA_PORTALES_KEY) or {}).get(capacidad) or m.url_inicio
    return {"sistema": m.sistema, "url": str(url or ""), "notas": m.notas, "plantilla": m}


def mission_para_recado(tenant: Tenant, recado: CuaMission) -> Mission | None:
    """La misión efectiva de un recado: el portal (built-in o a la medida) + su URL +
    la instrucción del dueño (si la dio) añadida a las notas, que el prompt del agente sí
    lee. Devuelve None si la capacidad ya no existe (portal a la medida borrado)."""
    portal = portal_efectivo(tenant, recado.capacidad)
    if portal is None:
        return None
    instruccion = (recado.data or {}).get("_instruccion")
    plantilla = portal["plantilla"]
    if plantilla is not None:
        mission = plantilla
        if portal["url"]:
            mission = replace(mission, url_inicio=portal["url"])
        if instruccion:
            extra = f"Instrucción específica del dueño: {instruccion}"
            mission = replace(
                mission, notas=f"{mission.notas}\n{extra}".strip() if mission.notas else extra
            )
        return mission
    # Portal a la medida: misión genérica de lo que el dueño registró + su instrucción.
    notas = portal["notas"]
    if instruccion:
        extra = f"Instrucción específica del dueño: {instruccion}"
        notas = f"{notas}\n{extra}".strip() if notas else extra
    return Mission(
        objetivo=instruccion
        or "Entra al portal y tráeme, resumida, la información relevante que encuentres.",
        sistema=portal["sistema"],
        url_inicio=portal["url"],
        datos_a_extraer={
            "resultado": "lo que encontraste, resumido y estructurado (usa null si no hay)"
        },
        notas=notas,
    )


def capacidad_tiene_cua(capacidad: str) -> bool:
    """¿Esa capacidad puede leerse por CUA cuando no hay conector API? (solo built-in;
    los portales a la medida no entran a la gráfica de integraciones)."""
    return capacidad in CUA_TEMPLATES


# ---------- Sesiones autenticadas guardadas (handoff de login) ----------
#
# El dueño entra UNA vez al portal en una vista del navegador; se guarda su sesión
# (cookies + localStorage) CIFRADA por tenant. El asistente la reusa para arrancar ya
# logueado. Nadie más que el dueño ve su contraseña — solo persistimos la sesión ya
# autenticada. Vive en tenant.config[CUA_SESIONES_KEY], por capacidad, sin migración.


def _sesiones(tenant: Tenant) -> dict:
    return dict((tenant.config or {}).get(CUA_SESIONES_KEY) or {})


def tiene_sesion(tenant: Tenant, capacidad: str) -> bool:
    return capacidad in _sesiones(tenant)


def sesion_guardada_en(tenant: Tenant, capacidad: str) -> str | None:
    entry = _sesiones(tenant).get(capacidad)
    return entry.get("guardada_en") if isinstance(entry, dict) else None


def sesion_de_capacidad(tenant: Tenant, capacidad: str) -> dict | None:
    """La sesión autenticada guardada para un portal (descifrada) o None. Honesta: si no
    se puede descifrar (clave rotada, dato corrupto), devuelve None y el asistente
    arranca sin sesión (chocará con el login) — no revienta ni inventa."""
    entry = _sesiones(tenant).get(capacidad)
    if not isinstance(entry, dict) or not entry.get("cifrada"):
        return None
    try:
        from aiuda_core.security.crypto import decrypt

        raw = decrypt(str(entry["cifrada"]).encode("ascii"), int(entry["version"]))
        return json.loads(raw)
    except Exception:
        logger.warning("CUA: no se pudo descifrar la sesión guardada de %s", capacidad)
        return None


def guardar_sesion(session: Session, tenant: Tenant, capacidad: str, state: dict) -> None:
    """Cifra y persiste la sesión autenticada de un portal por capacidad."""
    from aiuda_core.security.crypto import encrypt

    token, version = encrypt(json.dumps(state))
    sesiones = _sesiones(tenant)
    sesiones[capacidad] = {
        "cifrada": token.decode("ascii"),
        "version": version,
        "guardada_en": datetime.now(timezone.utc).isoformat(),
    }
    tenant.config = {**(tenant.config or {}), CUA_SESIONES_KEY: sesiones}
    flag_modified(tenant, "config")
    session.add(tenant)


def borrar_sesion(session: Session, tenant: Tenant, capacidad: str) -> bool:
    sesiones = _sesiones(tenant)
    if capacidad not in sesiones:
        return False
    del sesiones[capacidad]
    tenant.config = {**(tenant.config or {}), CUA_SESIONES_KEY: sesiones}
    flag_modified(tenant, "config")
    session.add(tenant)
    return True


def _runner_para_tenant(session: Session, tenant: Tenant, storage_state: dict | None = None):
    """CuaRunner que corre con la PROPIA IA del tenant (suscripción o API key), resuelta
    igual que la redacción. Con la suscripción combina la beta OAuth con la de computer-use
    en un solo header `anthropic-beta`. Sin credencial del tenant, cae al CuaRunner por
    defecto (env/settings), que es no-op honesto si tampoco hay ninguna. `storage_state`:
    sesión ya autenticada del portal (del handoff) para arrancar logueado."""
    import anthropic

    from aiuda_core.config import settings
    from aiuda_core.cua.runner import _COMPUTER_BETA, CuaRunner
    from aiuda_core.engine.provider import CLAUDE_CODE_IDENTITY, OAUTH_BETA, resolve_credential

    cred = resolve_credential(session=session, tenant_id=tenant.id)
    if cred is None:
        return CuaRunner(storage_state=storage_state)
    if cred.mode == "subscription":
        # La suscripción topa sonnet con 429: el CUA corre con el modelo que su token deja
        # pasar (haiku), la beta OAuth junto a computer-use, y el prefijo de identidad que
        # OAuth exige en `system`.
        client = anthropic.AsyncAnthropic(auth_token=cred.secret, max_retries=0)
        return CuaRunner(
            client=client,
            model=settings.model_redaccion_suscripcion,
            betas=[OAUTH_BETA, _COMPUTER_BETA],
            system=CLAUDE_CODE_IDENTITY,
            storage_state=storage_state,
        )
    return CuaRunner(
        client=anthropic.AsyncAnthropic(api_key=cred.secret),
        betas=[_COMPUTER_BETA],
        storage_state=storage_state,
    )


def _run(runner, mission: Mission) -> MissionResult:
    """Puente async->sync: los lectores de sync son síncronos (endpoint def / worker)."""
    return asyncio.run(runner.run(mission))


def _evidencia_b64(paths: list[str]) -> list[str]:
    """Lee las capturas de la misión y las guarda en base64 (acotadas) para el recado."""
    out: list[str] = []
    for p in paths[-_MAX_EVIDENCIA:]:
        try:
            with open(p, "rb") as f:
                out.append(base64.b64encode(f.read()).decode("ascii"))
        except OSError:
            continue
    return out


def enqueue_cua_mission(
    session: Session, tenant: Tenant, capacidad: str, instruccion: str | None = None
) -> CuaMission:
    """Encola un trabajo (queued) y lo devuelve al instante, para que aparezca en el log
    antes de correr. `ejecutar_recado` lo corre después (en segundo plano). La instrucción
    del dueño (si la hay) se guarda en `data['_instruccion']`: sin migración, y desde ahí
    se inyecta al objetivo del agente y se preserva para mostrarla en el log."""
    portal = portal_efectivo(tenant, capacidad)
    sistema = portal["sistema"] if portal else ""
    recado = CuaMission(
        tenant_id=tenant.id,
        capacidad=capacidad,
        sistema=sistema,
        status="queued",
        data={"_instruccion": instruccion} if instruccion else {},
    )
    session.add(recado)
    session.flush()
    return recado


def ejecutar_recado(
    session: Session, recado: CuaMission, runner=None, now: datetime | None = None
) -> CuaMission:
    """Corre un recado encolado y registra estado, datos, bitácora y evidencia. Honesto:
    sin credencial/backend queda 'failed' con la razón, nunca inventa datos."""
    tenant = session.get(Tenant, recado.tenant_id)
    mission = mission_para_recado(tenant, recado)
    if mission is None:
        # La capacidad no existe (portal a la medida borrado, o built-in inválida).
        recado.status = "failed"
        recado.error = "Ese portal ya no está disponible."
        session.flush()
        return recado
    if not mission.url_inicio:
        # Sin URL no hay a dónde entrar: corte honesto ANTES de abrir navegador o
        # gastar IA. El dueño la configura por capacidad en tenant.config["cua_portales"].
        recado.status = "failed"
        recado.error = (
            f"El portal de «{mission.sistema}» no tiene dirección configurada. "
            "Falta la URL del portal de tu negocio para esta capacidad (llave "
            f"{CUA_PORTALES_KEY!r} en la configuración del negocio)."
        )
        session.flush()
        return recado
    if runner is None:
        # Reusa la sesión autenticada guardada del handoff (si la hay): el asistente
        # arranca ya logueado en vez de chocar contra la pantalla de acceso.
        storage_state = sesion_de_capacidad(tenant, recado.capacidad)
        runner = _runner_para_tenant(session, tenant, storage_state=storage_state)
    recado.status = "running"
    recado.started_at = now or datetime.now(timezone.utc)
    session.flush()

    instruccion = (recado.data or {}).get("_instruccion")
    result = _run(runner, mission)
    recado.finished_at = now or datetime.now(timezone.utc)
    recado.evidence = _evidencia_b64(result.evidence)
    if result.success:
        recado.status = "done"
        # Preserva la instrucción junto a lo extraído, para que el log siga mostrándola.
        recado.data = {**({"_instruccion": instruccion} if instruccion else {}), **result.data}
        recado.steps = [s for s in result.steps_log[:-1] if s][:40]
        recado.resumen = (result.steps_log[-1] if result.steps_log else "") or None
    else:
        recado.status = "failed"
        recado.steps = [s for s in result.steps_log if s][:40]
        recado.error = result.error or "La misión no extrajo datos."
        logger.info("CUA (%s) no ejecutó: %s", recado.capacidad, recado.error)
    session.flush()
    return recado


def run_cua_mission(
    session: Session,
    tenant: Tenant,
    capacidad: str,
    runner=None,
    now: datetime | None = None,
) -> CuaMission:
    """Encola y corre un recado en una llamada (camino del sync diario y de tests). Es lo
    que el dueño ve en el log; nunca mira el navegador."""
    recado = enqueue_cua_mission(session, tenant, capacidad)
    return ejecutar_recado(session, recado, runner=runner, now=now)


def sync_cua(
    session: Session,
    tenant: Tenant,
    capacidad: str,
    runner=None,
    today: date | None = None,
) -> SyncReport:
    """Corre la misión CUA de una capacidad (registrando el recado) y mapea lo extraído a
    la cartera, con procedencia `cua:<sistema>` y evidencia. Sin credencial/backend es
    no-op honesto: el recado queda 'failed' y no se inventa nada."""
    report = SyncReport()
    if capacidad not in CUA_TEMPLATES:
        return report
    recado = run_cua_mission(session, tenant, capacidad, runner=runner)
    if recado.status != "done":
        return report
    report.fuentes.append(f"{CUA_FUENTE}:{recado.sistema}")
    if capacidad == "confirmacion_pago":
        _mapear_pagos(session, tenant, recado.data, recado.evidence, today or date.today(), report)
    return report


def _mapear_pagos(
    session: Session,
    tenant: Tenant,
    data: dict,
    evidencia: list,
    today: date,
    report: SyncReport,
) -> None:
    """Depósitos extraídos del portal bancario -> pagos pendientes de conciliación. Diego
    PROPONE; el humano concilia (igual que detectar_pagos: un depósito no cierra una
    factura solo). Dedup por monto+fuente para no duplicar en re-corridas."""
    for dep in data.get("depositos") or []:
        try:
            monto = float(dep.get("monto"))
        except (TypeError, ValueError, AttributeError):
            continue
        existing = session.scalar(
            select(Payment).where(
                Payment.tenant_id == tenant.id,
                Payment.source == "cua:banca",
                Payment.amount == monto,
                Payment.status != "ignorado",
            )
        )
        if existing:
            continue
        session.add(
            Payment(
                tenant_id=tenant.id,
                amount=monto,
                currency="MXN",
                paid_at=_parse_date(str(dep.get("fecha") or "")) or today,
                source="cua:banca",
                status="pendiente",
                counterparty=(str(dep.get("concepto") or "")[:255] or None),
                meta={"origen": "cua", "evidencia_capturas": len(evidencia)},
            )
        )
        report.pagos_por_conciliar += 1
    session.flush()
