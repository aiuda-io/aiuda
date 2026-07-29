"""Portales de PRUEBA locales para misiones CUA.

Tres HTML estáticos (en `cua/portales/`) que simulan los portales de las misiones
plantilla en chiquito: login + tabla (banca, SAT) y buscador + lista (tribunal). Sirven
para probar el ciclo completo del CUA — instrucción → acciones en un Chromium real →
evidencia — sin operar portales reales de terceros ni usar credenciales reales.

Todos los datos son ficticios y cada página lo dice en pantalla ("Portal de prueba
local"). Las credenciales de prueba están aquí y en el HTML; no son secretos.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORTALES_DIR = Path(__file__).parent / "portales"

# plantilla de misión -> (archivo del portal de prueba, notas de acceso para el agente).
# Las notas son lo que en un portal real aportaría la configuración del tenant
# (credenciales/cómo entrar); aquí son las de prueba, públicas por diseño.
PORTAL_DEMO: dict[str, tuple[str, str]] = {
    "banca_movimientos": (
        "banca.html",
        "Entra con usuario «demo» y contrasena «aiuda123»; los depositos estan en la tabla.",
    ),
    "sat_cfdi_recibidos": (
        "sat.html",
        "Entra con RFC «LABO860415XY1» y contrasena «aiuda123»; los CFDI estan en la tabla.",
    ),
    "tribunal_acuerdos": (
        "tribunal.html",
        "No pide login: escribe el numero de expediente en el buscador y presiona Buscar.",
    ),
}


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silencioso: no ensucia la salida de tests
        pass


@contextmanager
def servir_portales(host: str = "127.0.0.1", port: int = 0):
    """Sirve `cua/portales/` por HTTP local y entrega la URL base. Puerto 0 = efímero
    (no colisiona). Uso: `with servir_portales() as base: url = f"{base}/banca.html"`."""
    handler = partial(_Handler, directory=str(PORTALES_DIR))
    server = ThreadingHTTPServer((host, port), handler)
    hilo = threading.Thread(target=server.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://{server.server_address[0]}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        hilo.join(timeout=5)


def url_portal_demo(base: str, plantilla: str) -> str:
    """URL del portal de prueba de una plantilla, sobre una base ya servida."""
    archivo, _ = PORTAL_DEMO[plantilla]
    return f"{base}/{archivo}"


def notas_portal_demo(plantilla: str) -> str:
    """Cómo entrar al portal de prueba (equivale a las notas que daría el dueño)."""
    _, notas = PORTAL_DEMO[plantilla]
    return notas
