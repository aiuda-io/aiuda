"""Exporta las imágenes que se arman desde HTML: la vista previa del sitio y el
diagrama de "cómo funciona".

    uv run python scripts/og.py            # las dos
    uv run python scripts/og.py diagrama   # solo una

La fuente es HTML, no un PNG suelto: cambiar el texto o el color es editar el
.html y volver a correr esto. Salen en `landing/assets/`.

Necesita el extra del CUA, que es el que trae Chromium:

    uv sync --extra cua && .venv/bin/playwright install chromium
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# nombre -> (archivo fuente, ancho, alto). El tamaño de og es el que piden
# WhatsApp, LinkedIn y X; el del diagrama es para que se lea en un README.
IMAGENES = {
    "og": ("og.html", 1200, 630),
    "diagrama": ("como-funciona.html", 1400, 720),
}


def main() -> int:
    cuales = sys.argv[1:] or list(IMAGENES)
    desconocidas = [c for c in cuales if c not in IMAGENES]
    if desconocidas:
        print(f"No sé hacer: {', '.join(desconocidas)}. Hay: {', '.join(IMAGENES)}", file=sys.stderr)
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Falta Playwright. Instálalo con:\n"
            "  uv sync --extra cua && .venv/bin/playwright install chromium",
            file=sys.stderr,
        )
        return 1

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for nombre in cuales:
            archivo, ancho, alto = IMAGENES[nombre]
            fuente = RAIZ / "landing" / archivo
            destino = RAIZ / "landing" / "assets" / f"{nombre}.png"
            pagina = navegador.new_page(
                viewport={"width": ancho, "height": alto}, device_scale_factor=2
            )
            pagina.goto(fuente.as_uri(), wait_until="networkidle")
            pagina.wait_for_timeout(900)  # que bajen las tipografías
            pagina.screenshot(path=str(destino))
            pagina.close()
            print(f"{destino.relative_to(RAIZ)}  ({destino.stat().st_size // 1024} KB)")
        navegador.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
