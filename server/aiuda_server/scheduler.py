"""Scheduler local: reemplaza la cola y el cron externos.

Un hilo daemon dentro del MISMO proceso del API despierta cada minuto y, al
minuto 0 de cada hora, dispara ``run_daily_blocking()`` — la misma corrida
idempotente de siempre (cada negocio recibe su resumen a SU hora; los
cooldowns evitan duplicados, así que correr cada hora es seguro).

Sin Redis, sin cola, sin proceso aparte: si la computadora está prendida y
aiuda corriendo, el trabajo sale. Si estaba apagada, la corrida de la
siguiente hora se pone al día (idempotencia mediante).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("aiuda.scheduler")
MX_TZ = ZoneInfo("America/Mexico_City")

_started = threading.Event()
_stop = threading.Event()

# Cada cuánto sondear WhatsApp entrante (wacli no empuja). 20s se siente "en
# vivo" sin pelear por el lock del store con los envíos.
INBOUND_POLL_S = 20


def _loop() -> None:
    last_hour: int | None = None
    while not _stop.wait(30):
        now = datetime.now(MX_TZ)
        if now.minute != 0 or now.hour == last_hour:
            continue
        last_hour = now.hour
        try:
            from aiuda_server.worker.main import run_daily_blocking

            log.info("corrida horaria: arranca (%s)", now.isoformat(timespec="minutes"))
            run_daily_blocking()
            log.info("corrida horaria: termina")
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
        "scheduler local activo (corrida horaria al minuto 0; WhatsApp entrante cada %ds)",
        INBOUND_POLL_S,
    )
    return True


def stop() -> None:
    _stop.set()
