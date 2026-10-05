"""Fallback a CUA: cuando una capacidad no tiene conector API, un Computer Use Agent
opera el portal web como lo haría un humano. El dueño lo elige como cualquier otra
fuente ("de dónde lee" = CUA) y el motor de sync enruta aquí. Solo-lectura, con evidencia.

El runner corre de verdad con un Chromium local (extra `cua`, Playwright) y la IA del
tenant, que hoy tiene que ser una llave de Anthropic (ver `ia_para_cua`). Honesto en cada
faltante: sin el extra instalado, sin una IA que sirva para esto o sin la URL del portal,
el recado queda `failed` con la razón exacta y nunca inventa datos. La
URL del portal la aporta el tenant (`tenant.config["cua_portales"]`, por capacidad),
porque la banca o el juzgado de cada negocio son suyos. Ver docs/CUA.md.

Aparte están las rutinas DETERMINISTAS (`RUTINAS_DETERMINISTAS`): un guion fijo, sin IA,
que corre por el mismo recado. No pasan por el CuaRunner ni piden credencial de IA.
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

# capacidad -> rutina DETERMINISTA: un guion fijo de Playwright, sin IA en el camino.
# Corren con cualquier vía de IA conectada y sin ninguna. Las dos entran al SAT con la
# e.firma que el dueño ya guardó para la Descarga Masiva (`sat_efirma:<RFC>`), así que
# el recado lleva el RFC en `data["_rfc"]`. `documento` es el de
# `cua/deterministas/sat_documentos.py` y el `tipo` con que se guarda el Documento.
RUTINAS_DETERMINISTAS: dict[str, dict] = {
    "sat_opinion_32d": {
        "sistema": "SAT · Opinión de cumplimiento",
        "nombre": "Opinión de cumplimiento (32-D)",
        "documento": "opinion_32d",
    },
    "sat_constancia": {
        "sistema": "SAT · Constancia de situación fiscal",
        "nombre": "Constancia de situación fiscal",
        "documento": "constancia",
    },
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


class CuaSinIA(Exception):
    """La IA conectada no sirve para operar portales. El mensaje es para el dueño."""


# Qué le pide el CUA al modelo: VER una captura de pantalla y contestar una acción de
# ratón o teclado, decenas de veces seguidas. Hoy eso solo lo da la herramienta de
# computer-use de Anthropic, que se llama con la llave del dueño. Las demás vías de
# aiuda intercambian texto (`complete` y `run_tool_loop`): no reciben la captura. Por
# eso aquí no se intenta "a ver si sale": se dice por qué no, en palabras del dueño.
_PORQUE_NO = {
    "codex": (
        "Tu IA conectada es una llave de OpenAI. aiuda todavía no sabe operar un "
        "portal con OpenAI"
    ),
    "claude_cli": (
        "Tu IA conectada es el Claude Code instalado en esta computadora, que con "
        "aiuda solo intercambia texto y no puede ver la pantalla del portal"
    ),
    "codex_cli": (
        "Tu IA conectada es el Codex instalado en esta computadora, que con aiuda "
        "solo intercambia texto y no puede ver la pantalla del portal"
    ),
    "chatgpt": (
        "Tu IA conectada es tu plan de ChatGPT, que con aiuda solo intercambia texto "
        "y no puede ver la pantalla del portal"
    ),
    "local": (
        "Tu IA conectada es un modelo local, que no puede ver la pantalla del portal "
        "ni moverse en ella"
    ),
}
_QUE_HACER = (
    "Para las rutinas de portales hace falta una llave de Anthropic (Claude); "
    "conéctala en Proveedor de IA. El resto de aiuda sigue funcionando igual."
)


def ia_para_cua(session: Session, tenant: Tenant) -> tuple[bool, str]:
    """¿La IA que conectó el dueño puede operar portales? (sí/no, razón para él).
    Una sola regla para el aviso de la consola y para el corte del recado."""
    from aiuda_core.cua.runner import MSG_SIN_IA
    from aiuda_core.engine.provider import resolve_credential

    cred = resolve_credential(session=session, tenant_id=tenant.id)
    if cred is None:
        return False, MSG_SIN_IA
    if cred.name != "claude":
        porque = _PORQUE_NO.get(cred.name, "Tu IA conectada no puede ver la pantalla del portal")
        return False, f"{porque}. {_QUE_HACER}"
    return True, "Tu llave de Anthropic puede operar portales."


def _runner_para_tenant(
    session: Session, tenant: Tenant, storage_state: dict | None = None, ia=None
):
    """CuaRunner que corre con la IA del dueño por la misma vía que todo lo demás:
    la credencial de `resolve_credential` y el runner de `make_runner`.

    `ia`: fábrica del runner ya armado (en la capa HTTP/worker es `tenant_runner`,
    que trae el tope de gasto y el registro de uso). Sin ella se arma con
    `make_runner` a secas, que es lo que hay cuando no existe capa de servidor.
    `storage_state`: sesión ya autenticada del portal (del handoff).

    Lanza CuaSinIA, con el motivo en palabras del dueño, si la IA conectada no puede
    operar portales. Se corta ANTES de abrir el navegador."""
    from aiuda_core.cua.runner import ClienteDelMotor, CuaRunner
    from aiuda_core.engine.provider import resolve_credential
    from aiuda_core.engine.runner import make_runner

    sirve, detalle = ia_para_cua(session, tenant)
    if not sirve:
        raise CuaSinIA(detalle)
    motor = ia() if ia is not None else make_runner(
        resolve_credential(session=session, tenant_id=tenant.id)
    )
    if not hasattr(motor, "computer_use"):
        # Red de seguridad: un runner envuelto o nuevo que no trae computer-use no
        # debe llegar al loop y tronar a media misión con un AttributeError.
        raise CuaSinIA(f"Tu IA conectada no puede ver la pantalla del portal. {_QUE_HACER}")
    return CuaRunner(client=ClienteDelMotor(motor), storage_state=storage_state)


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
    session: Session,
    tenant: Tenant,
    capacidad: str,
    instruccion: str | None = None,
    rfc: str | None = None,
) -> CuaMission:
    """Encola un trabajo (queued) y lo devuelve al instante, para que aparezca en el log
    antes de correr. `ejecutar_recado` lo corre después (en segundo plano). La instrucción
    del dueño (si la hay) se guarda en `data['_instruccion']`: sin migración, y desde ahí
    se inyecta al objetivo del agente y se preserva para mostrarla en el log. Una rutina
    determinista no lleva instrucción: lleva el RFC en `data['_rfc']`."""
    if capacidad in RUTINAS_DETERMINISTAS:
        sistema = RUTINAS_DETERMINISTAS[capacidad]["sistema"]
        data = {"_rfc": (rfc or "").upper()}
    else:
        portal = portal_efectivo(tenant, capacidad)
        sistema = portal["sistema"] if portal else ""
        data = {"_instruccion": instruccion} if instruccion else {}
    recado = CuaMission(
        tenant_id=tenant.id,
        capacidad=capacidad,
        sistema=sistema,
        status="queued",
        data=data,
    )
    session.add(recado)
    session.flush()
    return recado


def ejecutar_recado(
    session: Session,
    recado: CuaMission,
    runner=None,
    now: datetime | None = None,
    ia=None,
) -> CuaMission:
    """Corre un recado encolado y registra estado, datos, bitácora y evidencia. Honesto:
    sin credencial/backend queda 'failed' con la razón, nunca inventa datos.

    `ia`: fábrica del runner de IA con tope y registro de uso (`tenant_runner` en la
    capa HTTP/worker). `runner`: un CuaRunner ya armado (tests y el guion sin IA)."""
    tenant = session.get(Tenant, recado.tenant_id)
    if recado.capacidad in RUTINAS_DETERMINISTAS:
        # Guion fijo: ni CuaRunner ni credencial de IA.
        return _ejecutar_determinista(session, tenant, recado, now)
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
        try:
            runner = _runner_para_tenant(session, tenant, storage_state=storage_state, ia=ia)
        except CuaSinIA as exc:
            # La IA conectada no puede operar portales: el recado lo dice tal cual y
            # no se abre navegador ni se gasta nada.
            recado.status = "failed"
            recado.error = str(exc)
            session.flush()
            return recado
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


# El permiso del dueño para que aiuda escriba la contraseña de su e.firma en el portal
# del SAT. Se pide UNA vez por RFC, antes de la primera corrida, y se guarda con fecha y
# con el texto exacto que aceptó: tenant.config[CONSENTIMIENTO_SAT_KEY][rfc]. Sin él,
# ninguna rutina determinista del SAT corre (se revisa al despachar y otra vez al correr).
CONSENTIMIENTO_SAT_KEY = "sat_rutinas_consentimiento"
CONSENTIMIENTO_SAT_TEXTO = (
    "Para bajar estos documentos aiuda entra al portal del SAT con la e.firma que ya "
    "guardaste y escribe su contraseña por ti. La firma se hace en esta computadora; "
    "la llave y la contraseña no se mandan a nadie. aiuda solo consulta y descarga: no "
    "presenta, no firma ni acepta nada."
)
MSG_FALTA_CONSENTIMIENTO = (
    "Falta tu permiso para que aiuda entre al portal del SAT con tu e.firma. "
    "Dalo una vez en Rutinas, en el bloque de ese RFC."
)


def consentimiento_sat(tenant: Tenant, rfc: str) -> str | None:
    """Cuándo aceptó el dueño (ISO) para ese RFC, o None si no ha aceptado."""
    dado = ((tenant.config or {}).get(CONSENTIMIENTO_SAT_KEY) or {}).get(rfc.upper())
    return dado.get("aceptado_en") if isinstance(dado, dict) else None


def aceptar_consentimiento_sat(session: Session, tenant: Tenant, rfc: str) -> str:
    """Guarda el permiso del dueño para ese RFC. Una vez: si ya estaba, no se mueve."""
    ya = consentimiento_sat(tenant, rfc)
    if ya:
        return ya
    ahora = datetime.now(timezone.utc).isoformat()
    dados = dict((tenant.config or {}).get(CONSENTIMIENTO_SAT_KEY) or {})
    dados[rfc.upper()] = {"aceptado_en": ahora, "texto": CONSENTIMIENTO_SAT_TEXTO}
    tenant.config = {**(tenant.config or {}), CONSENTIMIENTO_SAT_KEY: dados}
    flag_modified(tenant, "config")
    session.add(tenant)
    return ahora


def olvidar_consentimiento_sat(session: Session, tenant: Tenant, rfc: str) -> None:
    """Al borrar la e.firma: el permiso era para ESA e.firma guardada."""
    dados = dict((tenant.config or {}).get(CONSENTIMIENTO_SAT_KEY) or {})
    if dados.pop(rfc.upper(), None) is not None:
        tenant.config = {**(tenant.config or {}), CONSENTIMIENTO_SAT_KEY: dados}
        flag_modified(tenant, "config")
        session.add(tenant)


def efirmas_guardadas(session: Session, tenant: Tenant) -> list[str]:
    """Los RFC del negocio que tienen e.firma guardada (los que pueden correr las
    rutinas deterministas del SAT)."""
    from aiuda_core.engine.sync import sat_empresas

    return [e["rfc"] for e in sat_empresas(session, tenant) if e.get("efirma")]


def _ejecutar_determinista(
    session: Session, tenant: Tenant, recado: CuaMission, now: datetime | None
) -> CuaMission:
    """Corre una rutina determinista del SAT: abre la e.firma guardada EN MEMORIA, baja
    el documento con el guion fijo y lo guarda como `Documento`. La contraseña vive solo
    en esta función y en el guion; nunca llega al recado."""
    from aiuda_core.connectors import credentials as cred
    from aiuda_core.connectors.sat_descarga import SatCredencialInvalida, validar_efirma
    from aiuda_core.cua.computer import estado_navegador
    from aiuda_core.cua.deterministas import sat_documentos
    from aiuda_core.engine.sync import SAT_EFIRMA_PREFIX
    from aiuda_core.models import Documento

    spec = RUTINAS_DETERMINISTAS[recado.capacidad]
    rfc = str((recado.data or {}).get("_rfc") or "").upper()

    def no_pudo(motivo: str) -> CuaMission:
        recado.status = "failed"
        recado.error = motivo
        recado.finished_at = now or datetime.now(timezone.utc)
        session.flush()
        logger.info("Rutina %s no corrió: %s", recado.capacidad, motivo)
        return recado

    if not rfc or not consentimiento_sat(tenant, rfc):
        return no_pudo(MSG_FALTA_CONSENTIMIENTO)
    try:
        datos = cred.get_credential(session, tenant.id, f"{SAT_EFIRMA_PREFIX}{rfc}") if rfc else None
        cer = base64.b64decode(datos["cer"])
        key = base64.b64decode(datos["key"])
        password = datos["password"]
    except Exception:
        return no_pudo(
            f"No hay una e.firma guardada que se pueda abrir para {rfc or 'ese RFC'}. "
            "Cárgala en SAT · Bóveda fiscal."
        )
    # Antes de tocar el SAT: que la e.firma siga vigente y que haya navegador.
    try:
        validar_efirma(cer, key, password)
    except (SatCredencialInvalida, RuntimeError) as exc:
        return no_pudo(str(exc))
    if not estado_navegador()[0]:
        return no_pudo(sat_documentos.MSG_SIN_NAVEGADOR)

    recado.status = "running"
    recado.started_at = now or datetime.now(timezone.utc)
    # Se confirma ya: la corrida tarda cerca de un minuto y no debe tener la base
    # tomada ni esconderle a la consola que está adentro del portal.
    session.commit()

    try:
        resultado = sat_documentos.bajar_documento(cer, key, password, rfc, spec["documento"])
    except Exception as exc:  # el guion no debe lanzar; si lo hace, el recado no se queda colgado
        logger.warning("Rutina %s falló fuera del guion: %s", recado.capacidad, type(exc).__name__)
        return no_pudo("La rutina se detuvo por un error interno y no bajó nada.")
    recado.finished_at = now or datetime.now(timezone.utc)
    recado.steps = resultado.pasos[:40]
    recado.evidence = [
        base64.b64encode(png).decode("ascii") for png in resultado.capturas[-_MAX_EVIDENCIA:]
    ]
    if not resultado.ok or not resultado.pdf:
        return no_pudo(resultado.error or "El SAT no entregó el documento.")

    meta = {k: v for k, v in resultado.meta.items() if v}
    documento = Documento(
        tenant_id=tenant.id,
        rfc=rfc,
        tipo=spec["documento"],
        folio=meta.get("folio"),
        sentido=meta.get("sentido"),
        fecha=recado.finished_at,
        pdf=resultado.pdf,
        mission_id=recado.id,
    )
    session.add(documento)
    session.flush()
    recado.status = "done"
    recado.data = {"_rfc": rfc, "documento_id": documento.id, "tipo": documento.tipo, **meta}
    sentido = f": {documento.sentido}" if documento.sentido else ""
    recado.resumen = f"{spec['nombre']} de {rfc}{sentido}. PDF guardado."
    session.flush()
    return recado


def run_cua_mission(
    session: Session,
    tenant: Tenant,
    capacidad: str,
    runner=None,
    now: datetime | None = None,
    ia=None,
) -> CuaMission:
    """Encola y corre un recado en una llamada (camino del sync diario y de tests). Es lo
    que el dueño ve en el log; nunca mira el navegador."""
    recado = enqueue_cua_mission(session, tenant, capacidad)
    return ejecutar_recado(session, recado, runner=runner, now=now, ia=ia)


def sync_cua(
    session: Session,
    tenant: Tenant,
    capacidad: str,
    runner=None,
    today: date | None = None,
    ia=None,
) -> SyncReport:
    """Corre la misión CUA de una capacidad (registrando el recado) y mapea lo extraído a
    la cartera, con procedencia `cua:<sistema>` y evidencia. Sin credencial/backend es
    no-op honesto: el recado queda 'failed' y no se inventa nada."""
    report = SyncReport()
    if capacidad not in CUA_TEMPLATES:
        return report
    recado = run_cua_mission(session, tenant, capacidad, runner=runner, ia=ia)
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
