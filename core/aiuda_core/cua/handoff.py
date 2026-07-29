"""Handoff de login: el dueño entra al portal, no nosotros.

El muro para operar un portal real (el SAT, tu banco, tribunales) es el LOGIN. aiuda
nunca toca tu contraseña. En vez de eso hace un handoff: abre el portal en una ventana
VISIBLE del navegador en la máquina donde corre aiuda, TÚ entras como siempre (usuario,
e.firma, 2FA — lo que sea), y cuando ya estás dentro le dices "listo". En ese momento se
guarda tu SESIÓN ya autenticada (cookies + localStorage), cifrada por tenant, y el
asistente la reusa para arrancar logueado. Tu contraseña jamás se guarda ni se ve.

Arquitectura (robusta y honesta):
- Una sola corrutina (`_correr`) es dueña del navegador de principio a fin: lo abre,
  espera a que confirmes (o a que canceles / se agote el tiempo), captura la sesión y la
  persiste. Coordinar entre peticiones HTTP es solo prender un `asyncio.Event` — sin
  malabares de navegadores vivos entre requests.
- La ventana visible SOLO puede abrirse donde hay navegador y pantalla: la máquina del
  dueño. Sin el extra `cua` ni display esto es un no-op honesto; la
  UI lo dice y no ofrece el botón. El opener es inyectable para poder probar la máquina de
  estados sin abrir un Chromium de verdad.

Estado del proceso, en memoria (es local y de un proceso; en la nube ni aplica). No hay
tabla nueva ni migración: lo único que se PERSISTE es la sesión cifrada, vía
`fallback.guardar_sesion`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("aiuda.cua.handoff")

# Cuánto esperamos a que el dueño entre antes de rendirnos y cerrar la ventana.
TIMEOUT_LOGIN_S = 480  # 8 minutos: da aire para usuario + e.firma + 2FA.

# Estados terminales: la sesión ya no está viva, la ventana se cerró.
_TERMINALES = {"guardado", "cancelado", "expirado", "error"}


@dataclass
class SesionHandoff:
    """Una sesión de handoff viva (o recién terminada), en memoria."""

    id: str
    tenant_id: str
    capacidad: str
    sistema: str
    url: str
    estado: str = "abriendo"
    detalle: str = ""
    _confirmar: asyncio.Event = field(default_factory=asyncio.Event)
    _cancelar: asyncio.Event = field(default_factory=asyncio.Event)
    _task: object = None

    @property
    def terminal(self) -> bool:
        return self.estado in _TERMINALES

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "capacidad": self.capacidad,
            "sistema": self.sistema,
            "url": self.url,
            "estado": self.estado,
            "detalle": self.detalle,
        }


# id -> sesión. Un solo proceso; en la nube no se usa (el gate corta antes).
_SESIONES: dict[str, SesionHandoff] = {}


def estado_handoff_posible() -> tuple[bool, str]:
    """(posible, detalle): ¿esta máquina puede abrir una ventana para que el dueño entre?
    Requiere el navegador del asistente (extra `cua` + Chromium). La ventana visible se
    abre en la máquina que corre aiuda; por eso solo aplica cuando corre en la tuya."""
    from aiuda_core.cua.computer import estado_navegador

    listo, detalle = estado_navegador()
    if not listo:
        return False, detalle
    return True, "Se abrirá una ventana del navegador en esta máquina para que entres."


def _abrir_navegador_visible():
    """El opener por defecto: un Chromium VISIBLE (headless=False) en esta máquina."""
    from aiuda_core.cua.computer import LocalComputer

    return LocalComputer(headless=False)


def sesion_activa_de(tenant_id: str, capacidad: str) -> SesionHandoff | None:
    """La sesión de handoff viva (no terminal) de un portal, si la hay."""
    for s in _SESIONES.values():
        if s.tenant_id == tenant_id and s.capacidad == capacidad and not s.terminal:
            return s
    return None


def obtener(session_id: str, tenant_id: str) -> SesionHandoff | None:
    """La sesión por id, solo si es de este tenant (aislamiento)."""
    s = _SESIONES.get(session_id)
    return s if s and s.tenant_id == tenant_id else None


async def _esperar(sesion: SesionHandoff) -> str:
    """Espera a confirmar / cancelar / timeout. Devuelve cuál ganó."""
    confirmar = asyncio.ensure_future(sesion._confirmar.wait())
    cancelar = asyncio.ensure_future(sesion._cancelar.wait())
    try:
        done, pending = await asyncio.wait(
            {confirmar, cancelar},
            timeout=TIMEOUT_LOGIN_S,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        for t in (confirmar, cancelar):
            if not t.done():
                t.cancel()
    if sesion._cancelar.is_set():
        return "cancelar"
    if sesion._confirmar.is_set():
        return "confirmar"
    return "timeout"


def _persistir_sesion(tenant_id: str, capacidad: str, state: dict) -> None:
    """Guarda la sesión cifrada en su propio scope de DB (como run_recado_blocking)."""
    from aiuda_core.cua.fallback import guardar_sesion
    from aiuda_core.db import session_scope
    from aiuda_core.models import Tenant

    with session_scope() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is not None:
            guardar_sesion(db, tenant, capacidad, state)


async def _correr(sesion: SesionHandoff, abrir) -> None:
    """El ciclo completo del handoff, dueño único del navegador: abre la ventana, espera a
    que el dueño entre y confirme, captura su sesión autenticada y la persiste cifrada."""
    try:
        async with abrir() as comp:
            await comp.goto(sesion.url)
            sesion.estado = "esperando"
            resultado = await _esperar(sesion)
            if resultado == "cancelar":
                sesion.estado = "cancelado"
                sesion.detalle = "Cancelaste el acceso."
                return
            if resultado == "timeout":
                sesion.estado = "expirado"
                sesion.detalle = "Se agotó el tiempo para entrar; la ventana se cerró."
                return
            sesion.estado = "guardando"
            state = await comp.capturar_storage_state()
        # Persistir FUERA del navegador (ya cerrado): una escritura corta y cifrada.
        _persistir_sesion(sesion.tenant_id, sesion.capacidad, state)
        sesion.estado = "guardado"
        sesion.detalle = "Sesión guardada. El asistente ya puede entrar por su cuenta."
    except Exception as exc:  # navegador no abre, sin display, captura falla…
        logger.warning("Handoff de login (%s) falló: %s", sesion.capacidad, exc)
        sesion.estado = "error"
        sesion.detalle = str(exc)


def iniciar_handoff(
    tenant_id: str, capacidad: str, sistema: str, url: str, abrir=None
) -> SesionHandoff:
    """Arranca (o reusa) el handoff de un portal y agenda su corrida en el loop actual.
    Debe llamarse desde un contexto async (endpoint async): usa el event loop vivo."""
    existente = sesion_activa_de(tenant_id, capacidad)
    if existente is not None:
        return existente
    sesion = SesionHandoff(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        capacidad=capacidad,
        sistema=sistema,
        url=url,
    )
    _SESIONES[sesion.id] = sesion
    _limpiar_terminadas()
    sesion._task = asyncio.ensure_future(_correr(sesion, abrir or _abrir_navegador_visible))
    return sesion


def confirmar_handoff(sesion: SesionHandoff) -> None:
    """El dueño ya entró: dispara la captura y el guardado de su sesión."""
    sesion._confirmar.set()


def cancelar_handoff(sesion: SesionHandoff) -> None:
    """El dueño desistió: cierra la ventana sin guardar nada."""
    sesion._cancelar.set()


def _limpiar_terminadas(tope: int = 40) -> None:
    """Poda sesiones terminadas viejas para que el dict no crezca sin fin."""
    terminadas = [k for k, s in _SESIONES.items() if s.terminal]
    if len(terminadas) > tope:
        for k in terminadas[: len(terminadas) - tope]:
            _SESIONES.pop(k, None)
