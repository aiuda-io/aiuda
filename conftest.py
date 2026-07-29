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
"""

import os
import tempfile

# Clave Fernet válida, solo para pruebas. Se define ANTES de cualquier import de
# crypto para que el primer acceso al keyring la lea.
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
