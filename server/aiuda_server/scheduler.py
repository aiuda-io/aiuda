"""Scheduler local: reemplaza la cola y el cron externos.

Un hilo daemon dentro del MISMO proceso del API despierta cada 30 segundos y
dispara ``run_daily_blocking()`` una vez por hora de reloj — la misma corrida
idempotente de siempre (cada negocio recibe su resumen a SU hora; los cooldowns
evitan duplicados, así que correr de más no duplica nada).

La hora no se pierde aunque la máquina no esté despierta en el momento justo. El
bucle no pregunta "¿son las en punto?" sino "¿qué horas del reloj del negocio
quedaron sin correr desde la última vez?", y las horas cubiertas viajan a la
corrida para que el resumen diario salga aunque su hora haya pasado dormida. Una
laptop que se cierra a las 7 y se abre a las 11 recibe su resumen de las 8 al
despertar, tarde pero completo; antes simplemente no salía ese día.

Sin Redis, sin cola, sin proceso aparte: si la computadora está prendida y aiuda
corriendo, el trabajo sale.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("aiuda.scheduler")
MX_TZ = ZoneInfo("America/Mexico_City")

_started = threading.Event()
_stop = threading.Event()

# Cada cuánto sondear WhatsApp entrante (wacli no empuja). 20s se siente "en
# vivo" sin pelear por el lock del store con los envíos.
INBOUND_POLL_S = 20

# Cada cuánto revisa el hilo de la corrida si le falta alguna hora.
TICK_S = 30

# Dónde queda la marca de la última hora corrida: en el workspace, no en memoria,
# porque el punto es sobrevivir a que se cierre la laptop. Va en Tenant.config
# (sin migración, como manda ARCHITECTURE.md).
CLAVE_ULTIMA_CORRIDA = "ultima_corrida_horaria"

# Cuántas horas perdidas se cobran de una vez. Con 24 ya está cubierta cualquier
# hora del reloj que el dueño pudiera haber configurado: pedir más solo alargaría
# la lista sin cambiar una sola decisión.
MAX_HORAS_RECUPERADAS = 24

_FORMATO_HORA = "%Y-%m-%dT%H"


def _bucket(momento: datetime) -> str:
    """La hora de reloj del negocio a la que pertenece un momento."""
    return momento.strftime(_FORMATO_HORA)


def horas_pendientes(
    ultimo: str | None, ahora: datetime, max_horas: int = MAX_HORAS_RECUPERADAS
) -> list[int]:
    """Qué horas (0-23) faltan por correr. Función PURA: es toda la decisión del
    scheduler, sin hilos ni base de datos, para poder probarla en frío.

    - sin marca previa (instalación nueva, marca ilegible): solo la hora en curso;
      no se inventa una historia que nadie vivió.
    - misma hora ya corrida: nada.
    - horas perdidas: todas, de la más vieja a la actual, topadas a ``max_horas``.
    - marca en el futuro (ajuste de reloj hacia atrás): nada, para no repetir el
      resumen del día.
    """
    if ultimo == _bucket(ahora):
        return []
    actual = ahora.replace(tzinfo=None, minute=0, second=0, microsecond=0)
    try:
        desde = datetime.strptime(ultimo, _FORMATO_HORA)
    except (TypeError, ValueError):
        return [ahora.hour]
    faltan = int((actual - desde).total_seconds() // 3600)
    if faltan <= 0:
        return []
    faltan = min(faltan, max_horas)
    return [(actual - timedelta(hours=n)).hour for n in range(faltan - 1, -1, -1)]


def latido(ahora: datetime) -> list[int]:
    """Un tick del hilo de la corrida. Devuelve las horas que corrió ([] si no
    tocaba). Separado del bucle para poder probarlo sin esperar 30 segundos.

    La marca se guarda ANTES de correr, a propósito: si la corrida truena, el
    siguiente tick (30 s después) no vuelve a intentar las mismas horas
    inundando al dueño con el mismo error. Se retoma a la hora siguiente, igual
    que hacía el bucle viejo.
    """
    from aiuda_core.db import session_scope
    from aiuda_core.models import Tenant
    from sqlalchemy import select

    with session_scope() as db:
        # El workspace, con el mismo criterio que get_workspace (el más antiguo)
        # pero SIN crearlo: antes del primer arranque de la consola no hay a
        # quién cobrarle y un hilo de fondo no es quién para dar de alta el
        # negocio del dueño.
        tenant = db.scalars(select(Tenant).order_by(Tenant.created_at)).first()
        if tenant is None:
            return []
        horas = horas_pendientes((tenant.config or {}).get(CLAVE_ULTIMA_CORRIDA), ahora)
        if not horas:
            return []
        tenant.config = {**(tenant.config or {}), CLAVE_ULTIMA_CORRIDA: _bucket(ahora)}
        db.add(tenant)

    from aiuda_server.worker.main import run_daily_blocking

    if len(horas) > 1:
        log.info("corrida horaria: se recuperan %d horas perdidas %s", len(horas), horas)
    log.info("corrida horaria: arranca (%s)", ahora.isoformat(timespec="minutes"))
    run_daily_blocking(ahora, horas_cubiertas=horas)
    log.info("corrida horaria: termina")
    return horas


def _loop() -> None:
    while not _stop.wait(TICK_S):
        try:
            latido(datetime.now(MX_TZ))
        except Exception:  # noqa: BLE001 — el scheduler nunca muere por una corrida
            log.exception("corrida horaria falló; se reintenta a la siguiente hora")


def _inbound_loop() -> None:
    from aiuda_server.inbound import poll_wacli_once

    while not _stop.wait(INBOUND_POLL_S):
        try:
            entraron = poll_wacli_once()
            if entraron:
                log.info("wacli entrante: %d mensaje(s) nuevos", entraron)
        except Exception:  # noqa: BLE001 — poll_wacli_once ya aísla por negocio
            log.exception("sondeo de WhatsApp entrante falló; se reintenta")


def start() -> bool:
    """Arranca los hilos (una sola vez por proceso). Devuelve si arrancó ahora."""
    if _started.is_set():
        return False
    _started.set()
    _stop.clear()
    threading.Thread(target=_loop, name="aiuda-scheduler", daemon=True).start()
    threading.Thread(target=_inbound_loop, name="aiuda-inbound", daemon=True).start()
    log.info(
        "scheduler local activo (una corrida por hora, con recuperación de las que "
        "pasaron con la máquina dormida; WhatsApp entrante cada %ds)",
        INBOUND_POLL_S,
    )
    return True


def stop() -> None:
    _stop.set()
