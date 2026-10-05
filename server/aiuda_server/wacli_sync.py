"""El server es dueño de los procesos largos de wacli.

Dos procesos de wacli viven más que un comando: `sync --follow` (mantiene la
sesión conectada y llena el espejo local que el sondeo de entrada lee) y `auth`
(el emparejamiento por QR). Antes el primero lo tenía que correr el dueño en una
terminal y el segundo se quedaba vivo, con el candado del store, si cerraba la
ventana sin escanear. Aquí los dos tienen un solo dueño:

- se arranca el sync de cada negocio con WhatsApp vinculado, y después de emparejar;
- no se detiene para enviar: con un sync vivo, `wacli send` le pasa el mensaje
  por su socket y sale en 2 o 3 segundos sin soltar la conexión;
- si muere, se relanza con espera creciente; si WhatsApp cerró la sesión, no;
- al apagar aiuda se detiene todo, por las tres salidas del proceso;
- nunca hay dos: uno por instancia, y un archivo de pid delata al que haya
  quedado huérfano de un aiuda que murió de golpe.

El candado de wacli es un flock: el sistema lo suelta cuando su proceso muere.
Por eso el archivo LOCK nunca se toca; un candado "pegado" siempre es un proceso
vivo, y lo que se hace es reconocerlo (nuestro huérfano se termina, uno ajeno se
respeta).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.channel import wacli_store_dir
from aiuda_core.db import default_data_dir

log = logging.getLogger("aiuda.wacli")

# Estados que ve la consola.
SIN_INSTALAR = "sin_instalar"  # no hay conector en esta computadora
SIN_VINCULAR = "sin_vincular"  # no hay sesión: falta escanear el QR
VINCULANDO = "vinculando"  # QR en pantalla, esperando el teléfono
CONECTANDO = "conectando"  # sesión vinculada, el sync está entrando
CONECTADO = "conectado"  # el sync dijo `connected`
SIN_CONEXION = "sin_conexion"  # vinculada pero sin red, o el sync se cayó (se reintenta)
SESION_CERRADA = "sesion_cerrada"  # WhatsApp la cerró: hay que volver a escanear
DESACTUALIZADO = "desactualizado"  # WhatsApp pide un wacli más nuevo
EXTERNO = "externo"  # otro programa tiene abierta la sesión (no es de este aiuda)

# Con estos la sesión está vinculada: se puede intentar un envío.
VINCULADOS = frozenset({CONECTANDO, CONECTADO, SIN_CONEXION, EXTERNO})

# Espera antes de relanzar un sync que murió solo: 5 s, 15 s, 1 min y tope 5 min.
_ESPERAS = (5.0, 15.0, 60.0, 300.0)
# Cada cuánto se vuelve a mirar si el programa ajeno ya soltó la sesión.
_ESPERA_EXTERNO = 60.0
# Un QR que nadie escanea no se queda con el candado para siempre.
_VINCULACION_MAX_S = 180.0
_TICK_S = 0.5


@dataclass
class _Canal:
    """Lo que se sabe del WhatsApp de UNA instancia."""

    instance: str
    store_dir: str | None
    estado: str = SIN_VINCULAR
    desde: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    proc: subprocess.Popen | None = None
    tipo: str = ""  # "sync" | "auth": qué es `proc`
    qr: str | None = None  # el QR vigente (wacli lo rota)
    telefono: str | None = None
    ultimo_error: str = ""  # texto crudo de wacli; a la consola llega traducido
    deseado: bool = False  # el server quiere un sync vivo para esta instancia
    proximo: float = 0.0  # monotonic: no relanzar antes
    caidas: int = 0
    vence: float = 0.0  # monotonic: hasta cuándo se espera el escaneo
    cerro_sesion: bool = False
    prorrogado: bool = False  # el plazo del QR venció ya escaneado y se le dio otro


_canales: dict[str, _Canal] = {}
_lock = threading.RLock()
_parar = threading.Event()
_vigia: threading.Thread | None = None
# aiuda se está apagando: ya no se lanza nada, aunque llegue tarde una consulta
# de estado o el hilo de arranque.
_apagando = False


def _fijar(canal: _Canal, estado: str) -> None:
    if canal.estado != estado:
        canal.estado = estado
        canal.desde = datetime.now(timezone.utc)
        log.info("WhatsApp %s: %s", canal.instance, estado)


def _args_store(store_dir: str | None) -> list[str]:
    # La regla vive en un solo lugar: con una base que no es la del dueño, wacli
    # nunca cae a ~/.wacli (ver wacli_bin.store_del_host).
    return wacli_bin.args_store(store_dir)


def sesion(binario: str, store_dir: str | None) -> dict | None:
    """`auth status`: {"authenticated": bool, "phone"?}. No toma el candado, así
    que se puede preguntar con un sync o un emparejamiento corriendo. None si
    wacli no contestó (tardó, no corrió, respondió basura): eso NO es "sin
    sesión", y quien pregunta no debe tratarlo como tal."""
    try:
        out = subprocess.run(
            [binario, "auth", "status", *_args_store(store_dir), "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(out.stdout).get("data")
        return data if isinstance(data, dict) else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


# ---------- archivo de pid: reconocer al huérfano ----------


def _pidfile(instance: str) -> Path:
    return default_data_dir() / f"wacli.{instance or 'default'}.pid"


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _es_wacli(pid: int) -> bool:
    """Un pid se recicla: antes de terminar nada se confirma que sigue siendo wacli."""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "wacli" in out.stdout


def _terminar_pid(pid: int, espera_s: float = 5.0) -> None:
    for señal in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, señal)
        except (ProcessLookupError, PermissionError):
            return
        fin = time.monotonic() + espera_s
        while time.monotonic() < fin:
            if not _vivo(pid):
                return
            time.sleep(0.1)


def _limpiar_huerfano(instance: str) -> bool:
    """Qué hacer con el wacli que anotó un aiuda anterior. Devuelve False si ese
    proceso es de OTRO aiuda que sigue vivo: entonces no se toca y no se lanza nada."""
    ruta = _pidfile(instance)
    try:
        nota = json.loads(ruta.read_text())
        pid, server = int(nota["pid"]), int(nota["server"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    if server != os.getpid() and _vivo(server):
        return not (_vivo(pid) and _es_wacli(pid))
    if _vivo(pid) and _es_wacli(pid):
        log.warning("WhatsApp %s: quedó un wacli huérfano (pid %d); se termina", instance, pid)
        _terminar_pid(pid)
    ruta.unlink(missing_ok=True)
    return True


# ---------- lanzar, leer y detener ----------


def _lanzar(canal: _Canal, tipo: str) -> bool:
    """Arranca `sync --follow` o `auth` para el canal. Con `_lock` tomado."""
    if _apagando:
        return False
    binario = wacli_bin.resolver()
    if binario is None:
        _fijar(canal, SIN_INSTALAR)
        return False
    if canal.proc is not None and canal.proc.poll() is None:
        return canal.tipo == tipo  # ya hay uno: jamás dos por instancia
    if not _limpiar_huerfano(canal.instance):
        _fijar(canal, EXTERNO)
        canal.proximo = time.monotonic() + _ESPERA_EXTERNO
        return False
    if tipo == "sync":
        # --max-reconnect 0: sin red, wacli reintenta él mismo en vez de rendirse.
        # --presence-mode quiet: el sync no anuncia al dueño como "en línea" ante
        # sus contactos solo porque aiuda está abierto (existe en wacli 0.18.2).
        args = ["sync", "--follow", "--events", "--max-reconnect", "0",
                "--presence-mode", "quiet"]
    else:
        args = ["auth", "--qr-format", "text", "--events", "--idle-exit", "10s"]
    try:
        proc = subprocess.Popen(
            [binario, *args, *_args_store(canal.store_dir)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # Ctrl+C en la terminal no lo mata antes de tiempo
        )
    except OSError as exc:
        log.warning("WhatsApp %s: no se pudo lanzar wacli: %s", canal.instance, exc)
        _fijar(canal, SIN_INSTALAR)
        return False
    canal.proc, canal.tipo = proc, tipo
    canal.ultimo_error = ""
    canal.cerro_sesion = False
    canal.qr = None
    if tipo == "auth":
        canal.vence = time.monotonic() + _VINCULACION_MAX_S
        canal.prorrogado = False
    _fijar(canal, CONECTANDO if tipo == "sync" else VINCULANDO)
    try:
        _pidfile(canal.instance).write_text(json.dumps({"pid": proc.pid, "server": os.getpid()}))
    except OSError:
        log.warning("WhatsApp %s: no se pudo anotar el pid", canal.instance)
    threading.Thread(
        target=_leer, args=(canal, proc), name=f"aiuda-wacli-{tipo}", daemon=True
    ).start()
    _asegurar_vigia()
    return True


def _leer(canal: _Canal, proc: subprocess.Popen) -> None:
    """Drena el stderr del proceso (eventos NDJSON) hasta que termina. Sin esto el
    pipe se llena y wacli se queda trabado escribiendo."""
    assert proc.stderr is not None
    for linea in proc.stderr:
        linea = linea.strip()
        if not linea:
            continue
        try:
            evt = json.loads(linea)
        except json.JSONDecodeError:
            evt = None
        with _lock:
            if canal.proc is not proc:
                continue  # ya lo detuvimos nosotros: lo que diga no cambia el estado
            if not isinstance(evt, dict):
                canal.ultimo_error = linea[:500]
                continue
            _evento(canal, evt)
    proc.wait()
    # Tras un emparejamiento se pregunta si quedó sesión; es un subproceso, así
    # que va fuera del lock.
    datos: dict = {}
    if canal.tipo == "auth" and canal.proc is proc:
        binario = wacli_bin.resolver()
        datos = (sesion(binario, canal.store_dir) if binario else None) or {}
    with _lock:
        if canal.proc is proc:
            _termino(canal, datos)


def _evento(canal: _Canal, evt: dict) -> None:
    nombre = evt.get("event")
    data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
    if nombre == "error":
        canal.ultimo_error = str(data.get("message") or "")[:500]
    elif nombre == "qr_code":
        canal.qr = data.get("code") or canal.qr
    elif canal.tipo != "sync":
        return  # el bootstrap del emparejamiento no decide el estado del canal
    elif nombre == "connected":
        canal.caidas = 0
        _fijar(canal, CONECTADO)
    elif nombre in ("disconnected", "reconnecting", "stale", "stream_replaced"):
        _fijar(canal, SIN_CONEXION)
    elif nombre == "logged_out":
        canal.cerro_sesion = True


def _termino(canal: _Canal, datos: dict) -> None:
    """El proceso terminó SOLO (no lo detuvimos). Con `_lock` tomado. `datos` es
    el `auth status` de después de un emparejamiento."""
    tipo, error = canal.tipo, canal.ultimo_error.lower()
    canal.proc, canal.tipo, canal.qr = None, "", None
    _pidfile(canal.instance).unlink(missing_ok=True)
    ahora = time.monotonic()
    if tipo == "auth":
        if datos.get("authenticated"):
            # Emparejado y con el arranque inicial terminado: ahora sí, el sync.
            canal.telefono = datos.get("phone") or canal.telefono
            canal.deseado, canal.caidas, canal.proximo = True, 0, 0.0
            _lanzar(canal, "sync")
        else:
            _fijar(canal, SIN_VINCULAR)
        return
    if canal.cerro_sesion or "session was revoked" in error or "login failed" in error:
        canal.deseado = False
        _fijar(canal, SESION_CERRADA)
    elif "client outdated" in error:
        canal.deseado = False
        _fijar(canal, DESACTUALIZADO)
    elif "not authenticated" in error:
        canal.deseado = False
        _fijar(canal, SIN_VINCULAR)
    elif "store is locked" in error or "waiting for store lock" in error:
        # Otro programa tiene la sesión (una terminal del dueño, por ejemplo). No
        # se le quita: se vuelve a mirar cada minuto.
        _fijar(canal, EXTERNO)
        canal.proximo = ahora + _ESPERA_EXTERNO
    else:
        espera = _ESPERAS[min(canal.caidas, len(_ESPERAS) - 1)]
        canal.caidas += 1
        canal.proximo = ahora + espera
        log.warning(
            "WhatsApp %s: el sync terminó solo (%s); se relanza en %ds",
            canal.instance, canal.ultimo_error or "sin detalle", espera,
        )
        _fijar(canal, SIN_CONEXION)


def _detener_proc(canal: _Canal) -> None:
    """Termina el proceso del canal y espera a que suelte el candado."""
    with _lock:
        proc = canal.proc
        canal.proc, canal.tipo, canal.qr = None, "", None  # _leer ya no lo tomará por caída
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    _pidfile(canal.instance).unlink(missing_ok=True)


def _asegurar_vigia() -> None:
    global _vigia
    if _apagando:
        return
    if _vigia is None or not _vigia.is_alive():
        _parar.clear()
        _vigia = threading.Thread(target=_vigilar, name="aiuda-wacli-vigia", daemon=True)
        _vigia.start()


def _vigilar() -> None:
    """Relanza el sync que falta y corta el emparejamiento que nadie terminó."""
    while not _parar.wait(_TICK_S):
        vencidos: list[_Canal] = []
        with _lock:
            ahora = time.monotonic()
            for canal in _canales.values():
                if canal.proc is None:
                    if canal.deseado and ahora >= canal.proximo:
                        _lanzar(canal, "sync")
                elif canal.tipo == "auth" and ahora >= canal.vence:
                    vencidos.append(canal)
        for canal in vencidos:
            _vencio(canal)


def _escaneado(canal: _Canal) -> bool:
    """¿El teléfono ya escaneó el QR de este emparejamiento? (Subproceso: sin lock.)"""
    binario = wacli_bin.resolver()
    return bool(binario and (sesion(binario, canal.store_dir) or {}).get("authenticated"))


def _vencio(canal: _Canal) -> None:
    """Se acabó el plazo del emparejamiento. Sin escanear, se cancela. Ya
    escaneado, wacli está en su arranque inicial (bajar el historial tarda): se le
    da un plazo más y, si tampoco termina, se corta y sigue el sync, que retoma."""
    if not _escaneado(canal):
        log.info("WhatsApp %s: nadie escaneó el QR; se cancela", canal.instance)
        _cancelar(canal)
        canal.ultimo_error = "QR code timed out"
        return
    with _lock:
        if canal.tipo != "auth":
            return  # terminó solo mientras se preguntaba
        if not canal.prorrogado:
            canal.prorrogado = True
            canal.vence = time.monotonic() + _VINCULACION_MAX_S
            return
    log.warning("WhatsApp %s: el arranque inicial no terminó; sigue el sync", canal.instance)
    _detener_proc(canal)
    with _lock:
        if canal.proc is None:
            canal.deseado, canal.caidas, canal.proximo = True, 0, 0.0
            _lanzar(canal, "sync")


def _canal(instance: str, store_dir: str | None) -> _Canal:
    canal = _canales.get(instance)
    if canal is None:
        canal = _canales[instance] = _Canal(instance=instance, store_dir=store_dir)
    canal.store_dir = store_dir
    return canal


# ---------- lo que usa el resto del server ----------


def arrancar(instance: str, store_dir: str | None) -> str:
    """Deja corriendo el sync de esta instancia si su sesión está vinculada.
    Idempotente. Devuelve el estado."""
    with _lock:
        canal = _canal(instance, store_dir)
        if canal.proc is not None and canal.proc.poll() is None:
            return canal.estado
        binario = wacli_bin.resolver()
        if binario is None:
            _fijar(canal, SIN_INSTALAR)
            return canal.estado
    datos = sesion(binario, store_dir)  # subproceso: fuera del lock
    with _lock:
        if canal.proc is not None and canal.proc.poll() is None:
            return canal.estado
        if datos is None:
            return canal.estado  # wacli no contestó: no se concluye nada; se vuelve a preguntar
        if not datos.get("authenticated"):
            canal.deseado = False
            if canal.estado != SESION_CERRADA:
                _fijar(canal, SIN_VINCULAR)
            return canal.estado
        canal.telefono = datos.get("phone") or canal.telefono
        if not canal.deseado:
            canal.deseado, canal.caidas, canal.proximo = True, 0, 0.0
        if time.monotonic() >= canal.proximo:
            _lanzar(canal, "sync")
        return canal.estado


def arrancar_conectados() -> None:
    """Al abrir aiuda: el sync de cada negocio con WhatsApp por wacli."""
    from aiuda_core.db import session_scope
    from aiuda_server.inbound import _wacli_tenants

    try:
        with session_scope() as db:
            objetivos = _wacli_tenants(db)
        for _tenant_id, instance in objetivos:
            arrancar(instance, wacli_store_dir(instance))
    except Exception:  # noqa: BLE001 — WhatsApp caído no impide abrir aiuda
        log.exception("no se pudo arrancar el sync de WhatsApp")


def asegurar(instance: str, store_dir: str | None) -> None:
    """Lo llama el sondeo de entrada en cada vuelta: un negocio vinculado siempre
    termina con su sync corriendo, aunque `auth status` no haya contestado al
    abrir aiuda o el emparejamiento se haya cerrado a medias. Con un proceso vivo
    o un relanzado ya programado no hace nada; tampoco insiste donde hace falta
    el dueño (volver a escanear, actualizar)."""
    with _lock:
        canal = _canal(instance, store_dir)
        if (
            canal.deseado
            or canal.proc is not None
            or canal.estado in (SESION_CERRADA, DESACTUALIZADO)
        ):
            return
    arrancar(instance, store_dir)


def vincular(instance: str, store_dir: str | None, espera_s: float = 15.0) -> str | None:
    """Empieza el emparejamiento y devuelve el primer QR (o None si wacli no dio
    uno). El QR vigente después se lee con ``estado()``: wacli lo va rotando."""
    with _lock:
        canal = _canal(instance, store_dir)
        canal.deseado = False
    _detener_proc(canal)  # `auth` necesita el candado: fuera el sync o el QR anterior
    with _lock:
        if not _lanzar(canal, "auth"):
            return None
        proc = canal.proc
    fin = time.monotonic() + espera_s
    while time.monotonic() < fin:
        with _lock:
            if canal.proc is not proc:
                return None  # terminó sin dar QR
            if canal.qr:
                return canal.qr
        time.sleep(0.1)
    _cancelar(canal)
    return None


def _cancelar(canal: _Canal) -> None:
    """Termina el emparejamiento del canal y suelta el candado."""
    with _lock:
        if canal.tipo != "auth":
            return
    _detener_proc(canal)
    with _lock:
        if canal.proc is None:
            _fijar(canal, SIN_VINCULAR)


def cancelar_vinculacion(instance: str) -> None:
    """El dueño cerró la ventana sin escanear: el proceso de emparejamiento se
    termina y suelta el candado. Si ya había escaneado no se toca: wacli termina
    su arranque inicial y el sync arranca solo (matarlo ahí dejaría el teléfono
    vinculado y a aiuda sin recibir nada)."""
    with _lock:
        canal = _canales.get(instance)
        if canal is None or canal.tipo != "auth":
            return
    if not _escaneado(canal):
        _cancelar(canal)


def desvincular(instance: str, store_dir: str | None) -> str | None:
    """Cierra la sesión de WhatsApp de esta computadora. Devuelve None si salió
    bien, o el error crudo de wacli si no (para decirlo, no para tragárselo)."""
    with _lock:
        canal = _canal(instance, store_dir)
        canal.deseado = False
    _detener_proc(canal)
    binario = wacli_bin.resolver()
    if binario is None:
        with _lock:
            _fijar(canal, SIN_INSTALAR)
        return None
    datos = sesion(binario, store_dir)
    if datos is not None and not datos.get("authenticated"):
        with _lock:
            _fijar(canal, SIN_VINCULAR)
        return None  # ya no había sesión que cerrar
    try:
        out = subprocess.run(
            [binario, "auth", "logout", *_args_store(store_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        error = None if out.returncode == 0 else (out.stderr.strip() or "wacli auth logout falló")
    except (OSError, subprocess.SubprocessError) as exc:
        error = str(exc)
    with _lock:
        canal.telefono = None if error is None else canal.telefono
        _fijar(canal, SIN_VINCULAR if error is None else SIN_CONEXION)
    return error


def estado(instance: str, store_dir: str | None) -> dict:
    """El estado EN VIVO del WhatsApp de la instancia. Con un proceso nuestro
    corriendo es lo que él reporta; sin proceso se le pregunta a wacli (barato,
    no toma el candado), así una sesión vinculada desde fuera también se ve."""
    with _lock:
        canal = _canal(instance, store_dir)
        corriendo = canal.proc is not None and canal.proc.poll() is None
        tipo = canal.tipo
    binario = wacli_bin.resolver()
    if binario is None:
        with _lock:
            if not corriendo:
                _fijar(canal, SIN_INSTALAR)
    elif not corriendo or tipo == "auth":
        datos = sesion(binario, store_dir)
        if datos is None:
            with _lock:
                return _foto(canal)  # wacli no contestó: se queda lo que ya se sabía
        with _lock:
            canal.telefono = datos.get("phone") if datos.get("authenticated") else None
            if tipo == "auth" and corriendo:
                # Ya escaneó y wacli termina su arranque inicial: se dice "conectando"
                # y el QR deja de mostrarse.
                if datos.get("authenticated"):
                    return _foto(canal, estado=CONECTANDO, qr=None)
            elif canal.proc is None:
                if not datos.get("authenticated"):
                    if canal.estado not in (SESION_CERRADA, DESACTUALIZADO):
                        _fijar(canal, SIN_VINCULAR)
                elif canal.estado in (SIN_INSTALAR, SIN_VINCULAR, VINCULANDO, SESION_CERRADA):
                    # Vinculada y sin proceso nuestro todavía (recién abierta, o
                    # emparejada desde fuera): se ve como entrando.
                    _fijar(canal, CONECTANDO)
    with _lock:
        return _foto(canal)


def _foto(canal: _Canal, **cambios) -> dict:
    foto = {
        "estado": canal.estado,
        "desde": canal.desde.isoformat(),
        "qr": canal.qr,
        "telefono": canal.telefono,
        "error": canal.ultimo_error,
    }
    foto.update(cambios)
    return foto


def tras_instalar() -> None:
    """Hay conector nuevo: lo que estaba detenido por falta de conector o por
    viejo se vuelve a evaluar en la siguiente consulta de estado."""
    with _lock:
        for canal in _canales.values():
            if canal.proc is None and canal.estado in (SIN_INSTALAR, DESACTUALIZADO):
                _fijar(canal, SIN_VINCULAR)


def detener_todo() -> None:
    """Al apagar aiuda: ningún wacli se queda vivo a espaldas del dueño. Se llama
    desde las tres salidas del proceso; llamarlo de más no hace daño. Es
    definitivo: lo que pida arrancar después ya no lanza nada."""
    global _apagando
    _parar.set()
    with _lock:
        _apagando = True
        canales = list(_canales.values())
        for canal in canales:
            canal.deseado = False
    for canal in canales:
        _detener_proc(canal)
