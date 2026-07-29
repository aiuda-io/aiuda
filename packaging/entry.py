"""Punto de entrada del binario empaquetado: el mismo CLI de siempre.

Sin argumentos hace `aiuda start` — así el .app de escritorio y el doble clic
en el ejecutable hacen lo obvio, y `aiuda doctor`/`daily` siguen disponibles
desde la terminal.
"""

import multiprocessing
import sys

from aiuda_server.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    argv = sys.argv[1:] or ["start"]
    raise SystemExit(main(argv))
