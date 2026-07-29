"""Demo de CUA real y local: un Computer Use Agent extrae datos de un portal, en tu máquina.

Corre una misión contra un portal LOCAL de prueba (aiuda_core/cua/demo_portal.html, un
estado de cuenta bancario falso) para no necesitar credenciales de un portal real. El
agente abre un Chromium local (Playwright), lo lee por capturas y devuelve el JSON de
depositos con evidencia (capturas por paso).

Uso:
    uv sync --extra cua && uv run playwright install chromium   # una vez
    ANTHROPIC_API_KEY=sk-... uv run python scripts/cua_demo.py   # ejecuta de verdad
    uv run python scripts/cua_demo.py --ver                      # con navegador visible

Sin ANTHROPIC_API_KEY (con acceso a computer-use), imprime la razon y no inventa datos.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from aiuda_core.cua.mission import Mission
from aiuda_core.cua.runner import CuaRunner

PORTAL = Path(__file__).resolve().parents[1] / "core" / "aiuda_core" / "cua" / "demo_portal.html"


def _mission() -> Mission:
    return Mission(
        objetivo="Extrae TODOS los depositos de la tabla de movimientos: fecha, concepto y monto",
        sistema="Banca Empresarial (portal de prueba local)",
        url_inicio=PORTAL.as_uri(),
        datos_a_extraer={
            "depositos": "lista de objetos {fecha (YYYY-MM-DD), concepto, monto (numero)}"
        },
        notas="Es una sola pagina; los datos estan en la tabla visible. No necesitas login.",
        max_pasos=12,
    )


async def _run(headless: bool) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Sin ANTHROPIC_API_KEY. Exporta una llave con acceso a computer-use para "
            "ejecutar la mision de verdad:\n"
            "    ANTHROPIC_API_KEY=sk-... uv run python scripts/cua_demo.py",
            file=sys.stderr,
        )
        return 2
    model = os.environ.get("CUA_MODEL")  # opcional: fija un modelo con computer-use
    runner = CuaRunner(model=model, headless=headless)
    print(f"Abriendo {PORTAL.name} en Chromium local y extrayendo con CUA...\n")
    result = await runner.run(_mission())
    if not result.success:
        print(f"La mision no extrajo datos: {result.error or 'sin datos'}", file=sys.stderr)
        return 1
    import json

    print("Depositos extraidos por el agente:")
    print(json.dumps(result.data, ensure_ascii=False, indent=2))
    print(f"\nPasos: {len(result.steps_log)} · Evidencia (capturas):")
    for p in result.evidence:
        print(f"  {p}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo de CUA local")
    ap.add_argument("--ver", action="store_true", help="Muestra el navegador (no headless)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(headless=not args.ver)))


if __name__ == "__main__":
    main()
