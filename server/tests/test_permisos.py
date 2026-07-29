"""El registro de permisos está completo y cerrado por default.

Si agregaste un endpoint y esta prueba truena: decide quién entra y decláralo en
``server/aiuda_server/api/permisos.py`` (INVITADO o DUENO). No hay tercera
opción a propósito — así ningún router nuevo queda accesible a un aparato
invitado por accidente, ni "protegido" solo de palabra.
"""

from fastapi.routing import APIRoute

from aiuda_server.api import permisos
from aiuda_server.api.main import app


def _rutas_reales() -> set[tuple[str, str]]:
    rutas = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/v1"):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                rutas.add((m, r.path))
    return rutas


def test_toda_ruta_del_api_declara_quien_entra():
    sin_declarar = _rutas_reales() - permisos.PERMISOS
    assert not sin_declarar, (
        "Endpoints sin declarar permiso (decide si es trabajo de INVITADO o del "
        f"DUENO en api/permisos.py): {sorted(sin_declarar)}"
    )


def test_no_hay_permisos_fantasma():
    """Un permiso declarado de una ruta que ya no existe es mentira acumulada."""
    fantasmas = permisos.PERMISOS - _rutas_reales()
    assert not fantasmas, f"Declarados sin ruta viva: {sorted(fantasmas)}"


def test_nada_esta_en_las_dos_listas():
    assert not (permisos.INVITADO & permisos.DUENO)
