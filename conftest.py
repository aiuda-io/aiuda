"""Configuración global de pruebas.

Las credenciales de conectores se cifran en reposo (IntegrationCredential vía
aiuda_core.security.crypto). El cifrado exige AIUDA_ENCRYPTION_KEYS; aquí fijamos
una clave Fernet de PRUEBA para toda la corrida, así el camino cifrado (API de
integraciones, resolver, backfill) se ejercita de verdad en vez de saltarse.

No es un secreto de producción. Los tests que necesiten otra clave (rotación,
fallo de descifrado) la sobrescriben con monkeypatch + crypto.reset_cache().
"""

import os

# Clave Fernet válida, solo para pruebas. Se define ANTES de cualquier import de
# crypto para que el primer acceso al keyring la lea.
os.environ.setdefault("AIUDA_ENCRYPTION_KEYS", "wSx0BOg9oU_8IgSyWCAAsA12q0gWwYFGGrW3ABK34UU=")
