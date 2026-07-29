"""El CLI respeta el token que le pasa quien lo lanza (la app de escritorio).

Si `aiuda start` generara siempre uno nuevo, la app abriría su ventana con un
token que el server no reconoce: consola inaccesible en el primer arranque.
"""

import argparse

from aiuda_core.config import settings
from aiuda_server import cli


def _args(**extra):
    base = dict(port=4747, no_browser=True, no_token=False, quiet=True, exit_with_parent=False)
    base.update(extra)
    return argparse.Namespace(**base)


def test_start_respeta_el_token_del_entorno(monkeypatch):
    monkeypatch.setenv("AIUDA_SESSION_TOKEN", "token-de-la-app")
    monkeypatch.setattr(settings, "session_token", "")
    monkeypatch.setattr(cli, "uvicorn", __import__("types").SimpleNamespace(run=lambda *a, **k: None), raising=False)
    import sys
    import types

    fake = types.ModuleType("uvicorn")
    fake.run = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "uvicorn", fake)

    cli.cmd_start(_args())
    assert settings.session_token == "token-de-la-app"


def test_start_genera_token_si_no_hay(monkeypatch):
    monkeypatch.delenv("AIUDA_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(settings, "session_token", "")
    import sys
    import types

    fake = types.ModuleType("uvicorn")
    fake.run = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "uvicorn", fake)

    cli.cmd_start(_args())
    assert len(settings.session_token) > 20
