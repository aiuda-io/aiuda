"""Dónde está wacli y cómo se instala con un clic.

wacli NO viaja dentro de la app. El binario que publica su autor enlaza
libsignal (GPL-3.0): repartirlo dentro del .dmg nos obligaría a ofrecer su
código fuente por cada versión, y aiuda se reparte en Apache-2.0 sin esa carga.
Además sus binarios piden macOS 15 y la app corre desde macOS 11. Por eso lo
baja la computadora del dueño, directo del release oficial, con la versión
fijada aquí y su sha256 verificado antes de guardarlo.

Nunca se llama por nombre pelón: la app de escritorio arranca con el PATH mínimo
de macOS, sin Homebrew (misma lección que los CLIs de IA en
``engine/cli_runner.py``). ``resolver()`` devuelve SIEMPRE una ruta absoluta.
"""

import hashlib
import io
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

import httpx

from aiuda_core.config import settings
from aiuda_core.db import default_data_dir

# Versión fijada. Los sha256 son los de checksums.txt de ese release
# (github.com/openclaw/wacli/releases/tag/v0.20.0). Subir de versión = cambiar
# las tres líneas juntas.
WACLI_VERSION = "0.20.0"
WACLI_SHA256 = {
    "arm64": "109db7f8f9f6033d948c3c61aed46a2e69944fbc96e154867df0d706df188da4",
    "amd64": "fd5ec9df7b281d02f9b433deb718c1ebe4b1f410ebdb89b8a076bfd7f1263d95",
}
WACLI_URL = (
    "https://github.com/openclaw/wacli/releases/download/"
    "v{version}/wacli_{version}_darwin_{arch}.tar.gz"
)
# Los binarios oficiales de macOS se compilan para esta versión en adelante.
MACOS_MINIMO = 15

SIN_INSTALAR = (
    "Falta instalar el conector de WhatsApp en esta computadora. Ve a "
    "Integraciones, abre WhatsApp y presiona Instalar."
)
MACOS_VIEJO = (
    "WhatsApp con tu número necesita macOS 15 o más nuevo. Actualiza tu Mac para usarlo."
)
DESCARGA_FALLO = (
    "No se pudo descargar el conector de WhatsApp. Revisa tu internet e intenta de nuevo."
)


class WacliInstallError(RuntimeError):
    """La instalación no se pudo hacer; el mensaje ya va en español para el dueño."""


def ruta_instalada() -> Path:
    """Donde queda el wacli que instala aiuda: <carpeta de datos>/bin/wacli."""
    return default_data_dir() / "bin" / "wacli"


def _del_sistema() -> str | None:
    """Un wacli que el dueño ya tenía (Homebrew, o el PATH al correr desde el repo)."""
    del_path = shutil.which("wacli")
    if del_path:
        return del_path
    for carpeta in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidato = Path(carpeta) / "wacli"
        if candidato.is_file() and os.access(candidato, os.X_OK):
            return str(candidato)
    return None


def resolver() -> str | None:
    """Ruta absoluta del wacli a usar, o None si no hay ninguno.

    Orden: el que fijó quien opera (WACLI_BIN distinto del default), el que
    instaló aiuda, y al final el del sistema."""
    explicito = (settings.wacli_bin or "").strip()
    if explicito and explicito != "wacli":
        return shutil.which(explicito) or (explicito if os.path.isabs(explicito) else None)
    propio = ruta_instalada()
    if propio.is_file() and os.access(propio, os.X_OK):
        return str(propio)
    return _del_sistema()


def version(binario: str) -> str | None:
    """`wacli --version` → "0.20.0", o None si no respondió."""
    try:
        out = subprocess.run([binario, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    partes = (out.stdout or "").split()
    return partes[-1] if out.returncode == 0 and partes else None


def _macos_mayor() -> int | None:
    """Versión mayor de macOS (15, 26...), o None si esto no es una Mac."""
    if platform.system() != "Darwin":
        return None
    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return None


def _arquitectura() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"


def puede_instalarse() -> str | None:
    """None si esta computadora puede instalarlo; si no, el motivo para el dueño."""
    mayor = _macos_mayor()
    if mayor is None:
        return "La instalación con un clic solo existe para Mac."
    if mayor < MACOS_MINIMO:
        return MACOS_VIEJO
    return None


def _descargar(url: str) -> bytes:
    with httpx.Client(follow_redirects=True, timeout=120) as http:
        resp = http.get(url)
        resp.raise_for_status()
        return resp.content


def instalar(descargar=_descargar) -> str:
    """Baja el wacli fijado, verifica su sha256 y lo deja ejecutable en
    ``ruta_instalada()``. Devuelve la ruta. Idempotente: reinstalar reemplaza.

    Nada se escribe en su lugar definitivo hasta que la suma coincide; un
    archivo alterado o a medias se descarta."""
    motivo = puede_instalarse()
    if motivo:
        raise WacliInstallError(motivo)
    arch = _arquitectura()
    url = WACLI_URL.format(version=WACLI_VERSION, arch=arch)
    try:
        contenido = descargar(url)
    except Exception as exc:  # noqa: BLE001 — red caída, 404, tiempo agotado: mismo consejo
        raise WacliInstallError(DESCARGA_FALLO) from exc
    if hashlib.sha256(contenido).hexdigest() != WACLI_SHA256[arch]:
        raise WacliInstallError(DESCARGA_FALLO)
    try:
        with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
            # Solo el binario (en el release viene como "./wacli"), leído a memoria:
            # nada del archivo decide dónde cae en disco.
            miembro = next(
                (m for m in tar if m.isfile() and m.name.removeprefix("./") == "wacli"), None
            )
            if miembro is None:
                raise WacliInstallError(DESCARGA_FALLO)
            binario = tar.extractfile(miembro).read()
    except tarfile.TarError as exc:
        raise WacliInstallError(DESCARGA_FALLO) from exc
    destino = ruta_instalada()
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name("wacli.descargando")
    temporal.write_bytes(binario)
    temporal.chmod(0o755)
    os.replace(temporal, destino)  # atómico: nunca queda un binario a medias
    return str(destino)
