"""Capturas reales de la consola, para la landing y para promoción.

    uv run python scripts/capturas.py                    # a /tmp/aiuda-capturas
    uv run python scripts/capturas.py --salida ~/Desktop/capturas

Levanta un aiuda aparte, con su propia carpeta de datos y el dataset de
demostración de `scripts/seed.py`. **No toca ~/.aiuda ni la base de nadie**: al
terminar borra la carpeta temporal completa.

Son capturas de la consola de verdad, no maquetas: lo que sale aquí es lo que
ve quien la abre. Necesita el extra del CUA (trae Chromium):

    uv sync --extra cua && .venv/bin/playwright install chromium
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

RAIZ = Path(__file__).resolve().parent.parent

# Qué vale la pena enseñar, en el orden en que se cuenta la historia.
PANTALLAS = [
    ("bienvenida", "/", "El primer arranque: lo primero que se ve"),
    ("aprobaciones", "/aprobaciones", "Lo que el ayudante propone y tú apruebas"),
    ("cartera", "/facturas", "Tu cartera, con quién debe y desde cuándo"),
    ("cliente", "/clientes/detalle", "Un cliente: su historia y sus promesas"),
    ("ayudantes", "/ayudantes", "Los ayudantes del negocio"),
    ("conversaciones", "/conversaciones", "Las conversaciones, con su procedencia"),
    ("proveedor", "/proveedor", "Tu propia IA, conectada en un clic"),
    ("centro", "/centro", "El centro: qué pasó hoy"),
]


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar(url: str, segundos: int = 60) -> bool:
    for _ in range(segundos):
        try:
            with urlopen(url, timeout=1.5):
                return True
        except Exception:  # noqa: BLE001 — todavía no levanta
            time.sleep(1)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", default="/tmp/aiuda-capturas")
    ap.add_argument("--ancho", type=int, default=1440)
    ap.add_argument("--alto", type=int, default=900)
    ap.add_argument(
        "--completa",
        action="store_true",
        help="la página entera y no solo lo que cabe en pantalla",
    )
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Falta Playwright. Instálalo con:\n"
            "  uv sync --extra cua && .venv/bin/playwright install chromium",
            file=sys.stderr,
        )
        return 1

    salida = Path(args.salida).expanduser()
    salida.mkdir(parents=True, exist_ok=True)

    casa = Path(tempfile.mkdtemp(prefix="aiuda-capturas-"))
    entorno = {**os.environ, "HOME": str(casa), "AIUDA_SCHEDULER_ENABLED": "0"}
    puerto = puerto_libre()
    servidor = None

    try:
        print(f"Datos de demostración en {casa}/.aiuda (no se toca el tuyo)")
        sembrado = subprocess.run(
            [sys.executable, str(RAIZ / "scripts" / "seed.py")],
            env=entorno,
            cwd=RAIZ,
            capture_output=True,
            text=True,
        )
        if sembrado.returncode != 0:
            print(sembrado.stderr[-1500:], file=sys.stderr)
            return 1

        servidor = subprocess.Popen(
            [sys.executable, "-m", "aiuda_server.cli", "start",
             "--no-token", "--no-browser", "--quiet", "--port", str(puerto)],
            env=entorno,
            cwd=RAIZ,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{puerto}"
        if not esperar(f"{base}/health"):
            print("La consola no levantó.", file=sys.stderr)
            return 1

        cerrado = [False]
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page(
                viewport={"width": args.ancho, "height": args.alto},
                device_scale_factor=2,  # nítidas en pantallas retina
            )
            for nombre, ruta, descripcion in PANTALLAS:
                # La bienvenida se captura primero y luego se cierra: mientras el
                # asistente de primer arranque siga pendiente, tapa toda la
                # consola y las demás pantallas saldrían siendo esa misma.
                if nombre != "bienvenida" and not cerrado[0]:
                    pagina.request.post(f"{base}/v1/setup/terminar")
                    cerrado[0] = True
                pagina.goto(f"{base}{ruta}", wait_until="networkidle")
                pagina.wait_for_timeout(700)  # que terminen las animaciones
                destino = salida / f"{nombre}.png"
                pagina.screenshot(path=str(destino), full_page=args.completa)
                print(f"  {destino.name:22} {descripcion}")
            navegador.close()

        print(f"\nListas en {salida}")
        return 0
    finally:
        if servidor is not None:
            servidor.terminate()
            try:
                servidor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                servidor.kill()
        shutil.rmtree(casa, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
