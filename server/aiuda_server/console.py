"""Sirve la consola (export estático de Next) desde el MISMO proceso y origen
que el API: un solo puerto, cero CORS, cero Node en la máquina del usuario.

De dónde salen los archivos, en orden:
1. ``AIUDA_CONSOLE_DIR`` (override explícito).
2. ``aiuda_server/static/`` — el export empaquetado dentro del wheel.
3. ``web/out/`` del repo — desarrollo, tras ``NEXT_EXPORT=1 npm run build``.

Si no hay consola, el API sigue sirviendo y ``/`` lo dice honesto.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse


def console_dir() -> Path | None:
    candidates: list[Path] = []
    env = os.environ.get("AIUDA_CONSOLE_DIR", "")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).parent / "static")
    # server/aiuda_server/console.py -> server/ -> raíz del repo -> web/out
    candidates.append(Path(__file__).resolve().parents[2] / "web" / "out")
    for cand in candidates:
        if (cand / "index.html").is_file():
            return cand
    return None


def _resolve(root: Path, full_path: str) -> Path | None:
    """El archivo que corresponde a la ruta pedida, sin salirse de root."""
    clean = full_path.strip("/")
    base = (root / clean).resolve() if clean else root.resolve()
    if root.resolve() not in [base, *base.parents]:
        return None  # traversal
    if base.is_file():
        return base
    for option in (base / "index.html", base.with_suffix(".html")):
        if option.is_file():
            return option
    return None


def mount_console(app: FastAPI) -> None:
    root = console_dir()

    if root is None:

        @app.get("/", include_in_schema=False)
        def _sin_consola():
            return JSONResponse(
                {
                    "detail": (
                        "API de aiuda corriendo. Esta instalación no trae la consola "
                        "empaquetada; para desarrollo: cd web && NEXT_EXPORT=1 npm run build"
                    )
                }
            )

        return

    # Catch-all al FINAL: las rutas /v1, /health y /docs ya están registradas y
    # ganan; todo lo demás es la consola (páginas, /_next/*, .txt de RSC, media).
    #
    # HEAD además de GET: Next.js prefetchea los links con HEAD, y sin esto TODOS los
    # prefetch contestaban 405. La consola seguía funcionando, pero cada navegación
    # empezaba de cero en vez de estar ya traída. Es la diferencia entre que se sienta
    # instantánea y que no. Starlette contesta HEAD sin cuerpo a partir del mismo
    # handler.
    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def _consola(full_path: str):
        target = _resolve(root, full_path)
        if target is not None:
            return FileResponse(target)
        not_found = root / "404.html"
        if not_found.is_file():
            return FileResponse(not_found, status_code=404)
        return JSONResponse({"detail": "No encontrado"}, status_code=404)
