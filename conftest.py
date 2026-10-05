"""Configuración global de pruebas.

Las credenciales de conectores se cifran en reposo (IntegrationCredential vía
aiuda_core.security.crypto). El cifrado exige AIUDA_ENCRYPTION_KEYS; aquí fijamos
una clave Fernet de PRUEBA para toda la corrida, así el camino cifrado (API de
integraciones, resolver, backfill) se ejercita de verdad en vez de saltarse.

No es un secreto de producción. Los tests que necesiten otra clave (rotación,
fallo de descifrado) la sobrescriben con monkeypatch + crypto.reset_cache().

Aquí también se blinda la base del dueño: casi todos los tests arman su propia
base en memoria, pero los que levantan la app entera (TestClient corre el
lifespan) caían al default —``~/.aiuda/aiuda.db``— y le escribían al negocio de
verdad. Correr `uv run pytest` nunca debe tocar los datos de nadie.

Por lo mismo la corrida entera vive en un HOME desechable: la carpeta de datos
(``~/.aiuda``) y el store default de wacli (``~/.wacli``) salen de ahí, así que
ni un descuido de una prueba llega a los del dueño.
"""

import os
import tempfile

# Clave Fernet válida, solo para pruebas. Se define ANTES de cualquier import de
# crypto para que el primer acceso al keyring la lea.
# El Chromium de Playwright sí es el de la máquina (vive en el HOME de verdad y
# solo se lee): sin esto las pruebas del CUA se saltarían.
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/Library/Caches/ms-playwright")
)
_HOME_PRUEBAS = tempfile.mkdtemp(prefix="aiuda-pruebas-home-")
os.environ["HOME"] = _HOME_PRUEBAS
# El wacli de quien desarrolla tampoco entra por su entorno (lo que venga de un
# .env lo neutraliza el fixture de abajo).
for _var in ("WACLI_BIN", "WACLI_STORE_ROOT"):
    os.environ.pop(_var, None)

os.environ.setdefault("AIUDA_ENCRYPTION_KEYS", "wSx0BOg9oU_8IgSyWCAAsA12q0gWwYFGGrW3ABK34UU=")

# Base desechable para lo que no traiga la suya. Sin esto, levantar la app en un
# test corría create_all() y get_workspace() sobre la base real del dueño.
os.environ.setdefault(
    "AIUDA_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp(prefix='aiuda-pruebas-')}/pruebas.db"
)

# Y sin trabajos de fondo: el lifespan arranca los hilos del scheduler, que a los
# 30 segundos dispararían una corrida de cobranza de verdad (con sus envíos)
# desde adentro de la suite.
os.environ.setdefault("AIUDA_SCHEDULER_ENABLED", "false")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_wacli_del_dueno(monkeypatch, tmp_path_factory):
    """Ninguna prueba encuentra el wacli de esta computadora ni el que instala
    aiuda: en la máquina de quien desarrolla hay uno con su sesión de WhatsApp
    de verdad. Tampoco vale el WACLI_BIN ni el WACLI_STORE_ROOT de su entorno o
    de su .env. Las pruebas que necesitan un binario ponen el suyo."""
    from aiuda_core.config import settings
    from aiuda_core.connectors import wacli_bin

    monkeypatch.setattr(settings, "wacli_bin", "wacli")
    monkeypatch.setattr(settings, "wacli_store_root", "")
    vacio = tmp_path_factory.getbasetemp() / "sin-wacli" / "wacli"
    monkeypatch.setattr(wacli_bin, "_del_sistema", lambda: None)
    monkeypatch.setattr(wacli_bin, "ruta_instalada", lambda: vacio)
