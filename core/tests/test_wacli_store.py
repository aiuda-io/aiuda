"""Una base que no es la del dueño nunca toca ``~/.wacli``.

El 5 de octubre de 2026 un proceso tomó durante 28 segundos el candado del WhatsApp
de verdad del dueño (``~/.wacli/LOCK``). El camino: levantar aiuda con
``AIUDA_DATABASE_URL`` apuntando a una base desechable pero con el HOME real (un
``export HOME=...`` que no llegó al proceso, o los scripts de prueba que conservan
el HOME a propósito). Sin ``WACLI_STORE_ROOT``, aiuda no le pasaba ``--store`` a
wacli, wacli caía a su store por defecto, encontraba la sesión del dueño, aiuda se
la adjudicaba al negocio de prueba y dejaba un ``wacli sync`` corriendo encima.

La regla que lo cierra vive en ``wacli_bin.args_store`` y la usan TODAS las
llamadas a wacli: solo sobre la base del dueño se permite el store por defecto.
"""

from pathlib import Path

import pytest

from aiuda_core.config import settings
from aiuda_core.connectors import wacli as wacli_mod
from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.wacli import WacliClient, WacliError


class _Ok:
    returncode = 0
    stderr = ""
    stdout = '{"data": []}'


@pytest.fixture()
def comandos(monkeypatch):
    """subprocess.run interceptado: aquí no se ejecuta ningún wacli."""
    vistos: list[list[str]] = []
    monkeypatch.setattr(
        wacli_mod.subprocess, "run", lambda cmd, **kw: vistos.append(cmd) or _Ok()
    )
    monkeypatch.setattr(wacli_bin, "_del_sistema", lambda: "/sin-wacli/wacli")
    return vistos


def _store(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--store") + 1] if "--store" in cmd else None


def test_con_una_base_desechable_el_store_vive_junto_a_esa_base(tmp_path, monkeypatch, comandos):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/prueba.db")
    monkeypatch.setattr(settings, "wacli_store_root", "")

    cliente = WacliClient()  # sin store propio: antes esto era "el default del host"
    cliente.send_text("5215511110001", "hola")
    cliente.send_file("5215511110001", "/tmp/x.pdf")
    cliente.list_chats()

    assert len(comandos) == 3
    for cmd in comandos:
        assert _store(cmd) == str(tmp_path.resolve() / "wacli")


def test_el_sync_y_el_estado_del_servidor_siguen_la_misma_regla(tmp_path, monkeypatch):
    """`auth status`, `sync --follow`, emparejar y cerrar sesión arman su ``--store``
    con la misma función: no hay un segundo lugar donde olvidarlo."""
    wacli_sync = pytest.importorskip("aiuda_server.wacli_sync")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/prueba.db")
    monkeypatch.setattr(settings, "wacli_store_root", "")

    assert wacli_sync._args_store(None) == ["--store", str(tmp_path.resolve() / "wacli")]
    # El store propio de un negocio se respeta tal cual.
    assert wacli_sync._args_store("/stores/inst-a") == ["--store", "/stores/inst-a"]


def test_una_base_en_memoria_tampoco_cae_al_store_del_dueno(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite://")
    monkeypatch.setattr(settings, "wacli_store_root", "")

    store = wacli_bin.store_del_host()

    assert store is not None
    assert Path.home() / ".wacli" != Path(store)
    assert not str(store).startswith(str(Path.home() / ".wacli"))


def test_solo_la_base_del_dueno_usa_el_store_por_defecto_de_wacli(monkeypatch):
    # Sin AIUDA_DATABASE_URL: la base default del dueño.
    monkeypatch.setattr(settings, "database_url", "")
    assert wacli_bin.store_del_host() is None
    assert wacli_bin.args_store(None) == []
    # La misma base, dicha explícitamente, también es la del dueño.
    propia = Path.home() / ".aiuda" / "aiuda.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{propia}")
    assert wacli_bin.store_del_host() is None
    # Otra base dentro de la misma carpeta NO lo es.
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{propia.parent}/copia.db")
    assert wacli_bin.store_del_host() == str(propia.parent.resolve() / "wacli")


def test_sin_ningun_wacli_resuelto_no_se_ejecuta_nada(monkeypatch):
    """Antes caía al nombre pelón "wacli" y el sistema corría el primero del PATH,
    aunque aiuda hubiera decidido que no había ninguno que usar."""
    llamadas: list = []
    monkeypatch.setattr(
        wacli_mod.subprocess, "run", lambda cmd, **kw: llamadas.append(cmd) or _Ok()
    )
    monkeypatch.setattr(wacli_bin, "resolver", lambda: None)
    monkeypatch.setattr(settings, "wacli_bin", "wacli")

    with pytest.raises(WacliError, match="Falta instalar"):
        WacliClient().send_text("5215511110001", "hola")
    with pytest.raises(WacliError, match="Falta instalar"):
        WacliClient().list_chats()

    assert llamadas == []
