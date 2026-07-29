"""Cifrado en reposo de secretos de tenant (credenciales de conectores, etc.).

Por qué existe: la auditoría encontró que las credenciales de banca (Belvo), SAT
(PAC), Odoo, Shopify y la API key de IA se guardaban en TEXTO PLANO en
tenant.config. Un solo dump de la base comprometía las cuentas de todos los
clientes. Este módulo cifra cada secreto antes de persistirlo en
IntegrationCredential.secret_ciphertext.

Modelo de claves (envelope encryption simplificado):
- La clave de cifrado vive FUERA de la base de datos, en una variable de entorno
  o secret manager (AIUDA_ENCRYPTION_KEYS), nunca en la tabla.
- Se soportan varias claves a la vez para rotación: cada credencial guarda con
  qué key_version se cifró; al leer se usa esa versión.
- Hoy usa Fernet (AES-128-CBC + HMAC-SHA256, de la librería `cryptography`). El
  import es perezoso para que importar los modelos no requiera la librería.

Formato de la variable de entorno (la primera es la activa para cifrar):
    AIUDA_ENCRYPTION_KEYS="2:<fernet_key_v2>,1:<fernet_key_v1>"
o, para un solo valor, se asume versión 1:
    AIUDA_ENCRYPTION_KEYS="<fernet_key>"

Generar una clave nueva:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os
from functools import lru_cache


class EncryptionError(RuntimeError):
    """No hay clave configurada o el secreto no se pudo cifrar/descifrar."""


_ENV_VAR = "AIUDA_ENCRYPTION_KEYS"


def _parse_keys(raw: str) -> dict[int, str]:
    """'2:keyB,1:keyA' -> {2: 'keyB', 1: 'keyA'}. Un valor solo -> {1: valor}."""
    keys: dict[int, str] = {}
    raw = raw.strip()
    if not raw:
        return keys
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1 and ":" not in parts[0]:
        return {1: parts[0]}
    for part in parts:
        version_str, _, key = part.partition(":")
        keys[int(version_str)] = key.strip()
    return keys


@lru_cache(maxsize=1)
def _keyring() -> dict[int, object]:
    """version -> Fernet. Cacheado. Import perezoso de `cryptography`."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise EncryptionError(
            "Falta la librería 'cryptography'. Agrégala a las dependencias."
        ) from exc

    # Variable de entorno real primero; si no, el valor cargado del .env vía
    # settings; si tampoco, el keystore local (Keychain de macOS o ~/.aiuda/key),
    # que GENERA una llave en el primer arranque. El dueño no administra secretos.
    raw = os.environ.get(_ENV_VAR, "")
    if not raw:
        from aiuda_core.config import settings

        raw = settings.aiuda_encryption_keys
    if not raw:
        from aiuda_core.security.keystore import get_or_create_keys

        try:
            raw = get_or_create_keys()
        except Exception as exc:  # noqa: BLE001 — sin keystore el error es claro
            raise EncryptionError(
                f"No hay clave de cifrado y el keystore local falló: {exc}"
            ) from exc
    parsed = _parse_keys(raw)
    if not parsed:
        raise EncryptionError(
            f"No hay clave de cifrado. Define {_ENV_VAR} con al menos una clave Fernet."
        )
    return {ver: Fernet(key.encode()) for ver, key in parsed.items()}


def active_key_version() -> int:
    """La versión más alta configurada; es la que se usa para cifrar."""
    return max(_keyring())


def encrypt(plaintext: str) -> tuple[bytes, int]:
    """Cifra un secreto. Devuelve (ciphertext, key_version) para guardar en
    IntegrationCredential.secret_ciphertext y .key_version."""
    if plaintext is None:
        raise EncryptionError("No se puede cifrar None.")
    version = active_key_version()
    fernet = _keyring()[version]
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token, version


def decrypt(ciphertext: bytes, key_version: int) -> str:
    """Descifra un secreto usando la versión con la que se cifró."""
    keyring = _keyring()
    fernet = keyring.get(key_version)
    if fernet is None:
        raise EncryptionError(
            f"No hay clave para la versión {key_version}; ¿se retiró del keyring?"
        )
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except Exception as exc:  # InvalidToken u otros
        raise EncryptionError("No se pudo descifrar el secreto.") from exc


def reset_cache() -> None:
    """Limpia el cache del keyring (tests, o tras rotar claves en runtime)."""
    _keyring.cache_clear()
