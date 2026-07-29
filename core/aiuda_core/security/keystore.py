"""Llave de cifrado local: el dueño no administra secretos.

UNA fuente predecible: el archivo ``~/.aiuda/key`` (permisos 0600, junto a tus
datos). Se genera sola en el primer arranque y no cambia nunca.

Por qué no el Keychain como fuente primaria: una app sin firmar, un `launchd`,
una terminal y un doble clic tienen identidades distintas frente al llavero de
macOS. En unos casos lee, en otros lanza un diálogo o falla en silencio — y una
llave que a veces aparece y a veces no significa credenciales que un día ya no
abren ("no se pudo descifrar"). El archivo se comporta igual siempre.

Compatibilidad: si una instalación previa dejó la llave en el Keychain, se
migra al archivo la primera vez (nada se pierde). Y quien prefiera administrarla
él mismo sigue mandando con ``AIUDA_ENCRYPTION_KEYS``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SERVICE = "aiuda"
ACCOUNT = "encryption-keys"


def key_file() -> Path:
    from aiuda_core.db import default_data_dir

    return default_data_dir() / "key"


def _keychain_legacy() -> str | None:
    """Llave de una instalación previa que la guardó en el Keychain (macOS)."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 — sin llavero seguimos con el archivo
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _file_get() -> str | None:
    path = key_file()
    if path.exists():
        return path.read_text().strip() or None
    return None


def _file_set(value: str) -> None:
    path = key_file()
    path.write_text(value + "\n")
    path.chmod(0o600)


def _generate() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def get_or_create_keys() -> str:
    """La llave local, generándola la primera vez. Nunca la reemplaza."""
    existing = _file_get()
    if existing:
        return existing
    legacy = _keychain_legacy()
    if legacy:
        # Instalación previa con la llave en el llavero: se migra al archivo
        # para que a partir de ahora sea la misma en cualquier arranque.
        _file_set(legacy)
        return legacy
    fresh = _generate()
    _file_set(fresh)
    return fresh


def describe() -> str:
    """De dónde sale la llave, para `aiuda doctor`."""
    return str(key_file())
