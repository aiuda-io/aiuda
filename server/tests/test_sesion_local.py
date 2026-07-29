"""Dos ventanas de aiuda no pueden pelearse el puerto.

Pasó de verdad: la app quedó corriendo, el dueño la abrió otra vez, el segundo
server no pudo escuchar y la ventana nueva le habló al viejo con un token que
ese no conocía. En pantalla salió el JSON del 401. Aquí se cubren las tres
piezas del arreglo.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aiuda_core.config import settings
from aiuda_server import cli
from aiuda_server.api.main import app


@pytest.fixture()
def casa(tmp_path, monkeypatch):
    from aiuda_core import db

    monkeypatch.setattr(db, "default_data_dir", lambda: tmp_path)
    return tmp_path


def test_la_sesion_queda_anotada_solo_para_ti(casa):
    cli._anotar_sesion("t0k3n", 4747)
    ruta = casa / "sesion.json"
    assert json.loads(ruta.read_text())["token"] == "t0k3n"
    assert oct(ruta.stat().st_mode)[-3:] == "600"


def test_sin_server_vivo_no_hay_sesion_que_reusar(casa):
    # Un puerto que nadie va a estar usando: si el test tomara el 4747 de siempre,
    # fallaría en cualquier máquina que tenga aiuda abierto, y eso ya pasó.
    puerto = 47_999
    cli._anotar_sesion("t0k3n", puerto)
    # El puerto anotado no responde: la nota está vieja y no se usa.
    assert cli.sesion_viva(puerto) is None


def test_otro_puerto_no_cuenta(casa, monkeypatch):
    cli._anotar_sesion("t0k3n", 4747)
    assert cli.sesion_viva(9999) is None


def test_start_no_levanta_un_segundo_server(casa, monkeypatch):
    """Si ya hay uno vivo, `aiuda start` abre ESE y se sale sin servir nada."""
    # cmd_start fija el token del proceso; se restaura para no ensuciar al resto.
    monkeypatch.setattr(settings, "session_token", "")
    monkeypatch.delenv("AIUDA_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(cli, "sesion_viva", lambda port: {"token": "vivo", "port": port})
    abiertos = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: abiertos.append(url))

    def no_debe_correr(*a, **k):  # pragma: no cover
        raise AssertionError("levantó un segundo server")

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", no_debe_correr)
    args = SimpleNamespace(
        port=4747, no_token=False, no_browser=False, quiet=True, exit_with_parent=False
    )
    assert cli.cmd_start(args) == 0
    assert abiertos == ["http://127.0.0.1:4747/?token=vivo"]


def test_al_cerrar_la_ventana_no_queda_sesion_tirada(tmp_path):
    """El camino de todos los días: la app cierra y el server se va con
    os._exit, que se salta atexit. Si no se borra a mano, sesion.json se queda
    apuntando a un puerto muerto. Corre de verdad, en otro proceso, porque
    os._exit mataría al de pytest."""
    import subprocess
    import sys
    import textwrap

    guion = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from aiuda_core import db
        from aiuda_server import cli

        db.default_data_dir = lambda: Path({str(tmp_path)!r})
        cli._anotar_sesion("t0k3n", 4747)
        assert (Path({str(tmp_path)!r}) / "sesion.json").exists()
        cli._apagar_con_el_padre()   # vigila stdin, que ya viene cerrado
        import time; time.sleep(5)   # si no se apaga solo, el test lo caza
        sys.exit(99)
    """)
    fin = subprocess.run(
        [sys.executable, "-c", guion], stdin=subprocess.DEVNULL, capture_output=True, timeout=30
    )
    assert fin.returncode == 0, fin.stderr.decode()[-800:]
    assert not (tmp_path / "sesion.json").exists()


def test_la_ventana_ve_una_explicacion_no_un_json(monkeypatch):
    """Una persona llega por la raíz: se le explica en su idioma."""
    monkeypatch.setattr(settings, "session_token", "el-bueno")
    with TestClient(app) as c:
        r = c.get("/", headers={"accept": "*/*"})
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]
    assert "llave de tu sesión" in r.text
    assert "detail" not in r.text


def test_la_consola_si_recibe_json(monkeypatch):
    """El código que llama al API sí necesita JSON para reaccionar."""
    monkeypatch.setattr(settings, "session_token", "el-bueno")
    with TestClient(app) as c:
        r = c.get("/v1/settings", headers={"accept": "*/*"})
    assert r.status_code == 401
    assert r.json()["detail"].startswith("Falta el token")
