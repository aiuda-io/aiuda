"""Dejar que los aparatos del dueño lleguen a esta computadora, sin instalar nada.

Tres piezas, ninguna opcional para que el emparejamiento sea de un escaneo:

1. **Un certificado propio.** El teléfono habla con la Mac por HTTPS. El
   certificado se lo firma la Mac a sí misma, así que ninguna autoridad lo
   avalaría; en cambio su huella viaja en el QR, y el teléfono acepta ese
   certificado y ningún otro. Es más estricto que un candado del navegador: no
   confía en 200 autoridades, confía en UNA huella que vio con su cámara.

2. **Anunciarse en la red** (Bonjour, `_aiuda._tcp`). macOS y iOS lo traen de
   fábrica. Sirve para que el teléfono vuelva a encontrar la Mac cuando el router
   le cambie la dirección, sin que el dueño escriba una IP.

3. **Saber si macOS nos dejó.** La primera vez el sistema pregunta si aiuda puede
   buscar aparatos en la red local. Si el dueño dice que no (o le da al lado), el
   anuncio se cae en silencio y nadie entiende por qué no funciona. Aquí se
   detecta y se dice, con el atajo para ir a darle permiso.

Nada de esto se prende solo: el dueño lo enciende desde su consola.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SERVICIO = "_aiuda._tcp.local."

# El panel exacto de Ajustes donde se da el permiso. Se lo pasamos a la consola
# para que sea un botón y no unas instrucciones.
AJUSTES_RED_LOCAL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"
)


def carpeta() -> Path:
    from aiuda_core.db import default_data_dir

    return default_data_dir()


# --------------------------------------------------------------------------- #
# El certificado de esta computadora                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Certificado:
    cert: Path
    llave: Path
    huella: str  # SHA-256 en hex, lo que el teléfono va a exigir


def _huella(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def certificado(regenerar: bool = False) -> Certificado:
    """El certificado de esta computadora, creándolo la primera vez.

    Dura 10 años a propósito: no es un certificado público, es la identidad de
    esta máquina para los teléfonos que ya la conocen. Que caduque solo lograría
    romper el emparejamiento un martes cualquiera.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_path = carpeta() / "red-local.crt"
    llave_path = carpeta() / "red-local.key"

    if cert_path.exists() and llave_path.exists() and not regenerar:
        der = x509.load_pem_x509_certificate(cert_path.read_bytes()).public_bytes(
            serialization.Encoding.DER
        )
        return Certificado(cert_path, llave_path, _huella(der))

    llave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aiuda local")])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=3650))
        # Con la IP entre los nombres. El teléfono compara la huella y no la
        # cadena, así que hoy no hace falta; pero si algún día un cliente valida
        # de la forma normal, un certificado sin la IP falla y nadie entiende por
        # qué. Cuesta tres líneas.
        .add_extension(x509.SubjectAlternativeName(_nombres_de_esta_maquina()), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(llave, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    # Nace protegida. Antes se escribía y se hacía chmod después: entre las dos
    # cosas el archivo quedaba con el umask, o sea legible.
    with os.fdopen(os.open(llave_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(llave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    llave_path.chmod(0o600)
    return Certificado(cert_path, llave_path, _huella(cert.public_bytes(serialization.Encoding.DER)))


# --------------------------------------------------------------------------- #
# Dónde estamos en la red                                                      #
# --------------------------------------------------------------------------- #
def _nombres_de_esta_maquina() -> list:
    """Los nombres y direcciones con los que se puede llegar a esta computadora."""
    import ipaddress

    from cryptography import x509

    nombres = [x509.DNSName("aiuda.local"), x509.DNSName(_nombre_equipo())]
    ip = direccion_lan()
    if ip:
        try:
            nombres.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    return nombres


def _nombre_equipo() -> str:
    nombre = socket.gethostname()
    return nombre if nombre.endswith(".local") else f"{nombre}.local"


def direccion_lan() -> str | None:
    """La dirección de esta computadora en la red del changarro.

    No se manda nada: abrir un socket UDP hacia afuera es la forma portátil de
    preguntarle al sistema qué tarjeta usaría, sin depender de nombres de
    interfaz que cambian entre WiFi y cable.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("192.0.2.1", 9))  # rango reservado para documentación
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Anunciarse (Bonjour)                                                         #
# --------------------------------------------------------------------------- #
_anuncio: object | None = None
_zc: object | None = None


def anunciar(puerto: int) -> bool:
    """Publica el servicio en la red local. Devuelve si se pudo."""
    global _anuncio, _zc
    ip = direccion_lan()
    if ip is None:
        return False
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        log.info("sin zeroconf: el teléfono tendrá que usar la dirección del QR")
        return False

    dejar_de_anunciar()
    try:
        _zc = Zeroconf()
        _anuncio = ServiceInfo(
            SERVICIO,
            f"aiuda.{SERVICIO}",
            addresses=[socket.inet_aton(ip)],
            port=puerto,
            # Solo la versión. El nombre de la máquina y la huella no tienen por
            # qué ir gritándose en el WiFi de la plaza: el teléfono ya trae la
            # huella del QR y la vuelve a verificar al conectarse.
            properties={"version": "1"},
            server=f"{socket.gethostname()}.local.",
        )
        _zc.register_service(_anuncio)
        return True
    except Exception:  # noqa: BLE001 — sin anuncio se sigue pudiendo emparejar por QR
        log.warning("no se pudo anunciar en la red local", exc_info=True)
        dejar_de_anunciar()
        return False


def dejar_de_anunciar() -> None:
    global _anuncio, _zc
    try:
        if _zc is not None and _anuncio is not None:
            _zc.unregister_service(_anuncio)
        if _zc is not None:
            _zc.close()
    except Exception:  # noqa: BLE001 — al apagar no hay a quién avisarle
        pass
    _anuncio = None
    _zc = None


# --------------------------------------------------------------------------- #
# La segunda puerta: la que da a la red                                        #
# --------------------------------------------------------------------------- #
PUERTO = 4748


class _YaArrancada:
    """La misma app, pero sin volver a arrancarla.

    Las dos puertas sirven la MISMA aiuda. Si el servidor de la red también
    corriera el arranque, aiuda se levantaría dos veces en el mismo proceso: dos
    scheduler mandando los mismos recordatorios, y el estado de la primera puerta
    pisado por el de la segunda (pasó: prender la red dejaba el QR sin dirección
    a la cual apuntar). Aquí el protocolo de arranque se contesta y ya.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            # Marca de por dónde entró. Lo que llega por la red SIEMPRE tiene que
            # traer el token de su aparato, pase lo que pase: `--no-token` apaga
            # el candado de la consola, que es hablar consigo misma, y no tendría
            # por qué dejar la puerta de la calle abierta de par en par.
            scope["aiuda_puerta"] = "red"
            await self.app(scope, receive, send)
            return
        while True:
            mensaje = await receive()
            if mensaje["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif mensaje["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


class Escucha:
    """La puerta que da a la red de la oficina, aparte de la de siempre.

    La consola sigue entrando por 127.0.0.1 sin cifrar, que es hablar consigo
    misma. Los aparatos entran por esta otra, con el certificado de la casa. Son
    dos puertas del mismo aiuda: la misma base, los mismos ayudantes.

    Se prende y se apaga en caliente, porque el dueño lo decide desde su consola
    y no vamos a pedirle que reinicie nada.
    """

    def __init__(self) -> None:
        self._servidor = None
        self._hilo = None
        self.puerto: int | None = None
        self.anunciado = False

    @property
    def prendida(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def prender(self, app, puerto: int = PUERTO) -> dict:
        import threading

        import uvicorn

        if self.prendida:
            return self.estado()

        cert = certificado()
        config = uvicorn.Config(
            _YaArrancada(app),
            host="0.0.0.0",  # noqa: S104 — es el punto: que la vean los aparatos del dueño
            port=puerto,
            log_level="warning",
            # Sin esto, una petición lenta puede dejar el puerto abierto para
            # siempre mientras la consola jura que ya cerró.
            timeout_graceful_shutdown=3,
            ssl_certfile=str(cert.cert),
            ssl_keyfile=str(cert.llave),
        )
        self._servidor = uvicorn.Server(config)
        self._hilo = threading.Thread(
            target=self._servidor.run, name="aiuda-red-local", daemon=True
        )
        self._hilo.start()
        self.puerto = puerto
        app.state.puerto_red_local = puerto
        self.anunciado = anunciar(puerto)
        return self.estado()

    def apagar(self, app=None) -> dict:
        dejar_de_anunciar()
        self.anunciado = False
        if self._servidor is not None:
            self._servidor.should_exit = True
        if self._hilo is not None:
            self._hilo.join(timeout=5)
            if self._hilo.is_alive() and self._servidor is not None:
                self._servidor.force_exit = True   # se acabó la cortesía
                self._hilo.join(timeout=5)
        if self._hilo is not None and self._hilo.is_alive():
            # No se pudo. Se dice, en vez de reportar "apagada" con el puerto
            # abierto y además perder la manija para volver a intentarlo.
            log.warning("la puerta de la red no cerró; sigue escuchando en %s", self.puerto)
            return self.estado()
        self._servidor = None
        self._hilo = None
        self.puerto = None
        if app is not None:
            app.state.puerto_red_local = None
        return self.estado()

    def estado(self) -> dict:
        return {
            "prendida": self.prendida,
            "puerto": self.puerto,
            "direccion": direccion_lan(),
            "anunciada": self.anunciado,
        }


escucha = Escucha()


_permiso_visto: tuple[float, bool | None] | None = None
_PERMISO_VIGENCIA = 60.0


def permiso_concedido(espera: float = 3.0) -> bool | None:
    """¿macOS nos dejó ver la red local?

    Se pregunta buscando nuestro propio anuncio: si estamos publicando y aun así
    no nos vemos, es que el sistema nos tiene tapados. Devuelve None cuando no se
    puede saber (otro sistema operativo, o sin zeroconf).
    """
    global _permiso_visto
    import sys
    import time as _t

    if sys.platform != "darwin" or _anuncio is None:
        return None
    # Cada consulta levanta un Zeroconf y espera hasta 3 segundos. Sondear esto
    # sin caché ocupa el pool de hilos y congela la consola del dueño.
    if _permiso_visto is not None and _t.monotonic() - _permiso_visto[0] < _PERMISO_VIGENCIA:
        return _permiso_visto[1]
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return None

    vistos: list[str] = []

    class _Escucha:
        def add_service(self, zc, tipo, nombre):  # noqa: ANN001, ARG002
            vistos.append(nombre)

        def update_service(self, zc, tipo, nombre):  # noqa: ANN001, ARG002, D102
            pass

        def remove_service(self, zc, tipo, nombre):  # noqa: ANN001, ARG002, D102
            pass

    import time

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICIO, _Escucha())
        limite = time.monotonic() + espera
        while time.monotonic() < limite and not vistos:
            time.sleep(0.2)
    finally:
        zc.close()
    _permiso_visto = (_t.monotonic(), bool(vistos))
    return _permiso_visto[1]
