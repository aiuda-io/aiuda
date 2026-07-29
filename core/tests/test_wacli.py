"""wacli: construcción del comando + manejo de error, sin tocar el binario real.

Monkeypatcheamos subprocess.run para capturar el argv EXACTO que se ejecutaría.
Esto fija el contrato con wacli 0.8.x (`send text --to/--message --lock-wait`).
"""

import pytest

from aiuda_core.config import Settings
from aiuda_core.connectors import wacli as wacli_mod
from aiuda_core.connectors.wacli import WacliClient, WacliError

DEFAULT_TEMPLATE = "{bin} send text --to {phone} --message {message} --lock-wait 30s"


class _Result:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def _capture(monkeypatch, result=None):
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return result or _Result()

    monkeypatch.setattr(wacli_mod.subprocess, "run", fake_run)
    return calls


def test_config_default_template_is_v08():
    # El default de config DEBE ser la sintaxis válida de wacli 0.8.x (no `send {phone}`).
    s = Settings(_env_file=None)
    assert s.wacli_send_template == DEFAULT_TEMPLATE
    assert s.wacli_bin == "wacli"


def test_send_text_builds_v08_command(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient(send_template=DEFAULT_TEMPLATE)
    client.bin = "wacli"
    client.send_text("+5213314872210", "Hola, su factura M-107.")
    assert calls["command"] == [
        "wacli", "send", "text",
        "--to", "5213314872210@s.whatsapp.net",
        "--message", "Hola, su factura M-107.",
        "--lock-wait", "30s",
    ]


def test_send_text_normalizes_10_digit_local(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient(send_template=DEFAULT_TEMPLATE)
    client.bin = "wacli"
    client.send_text("3314872210", "x")
    cmd = calls["command"]
    # Número local de 10 dígitos → 521… y JID de usuario explícito (evita ambigüedad).
    assert cmd[cmd.index("--to") + 1] == "5213314872210@s.whatsapp.net"


def test_message_with_spaces_stays_single_arg(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient(send_template=DEFAULT_TEMPLATE)
    client.bin = "wacli"
    client.send_text("5213314872210", "Hola mundo con espacios")
    assert "Hola mundo con espacios" in calls["command"]


def test_send_text_respects_custom_bin(monkeypatch):
    monkeypatch.setattr(wacli_mod.settings, "wacli_bin", "/opt/wacli")
    calls = _capture(monkeypatch)
    WacliClient(send_template=DEFAULT_TEMPLATE).send_text("5213314872210", "x")
    assert calls["command"][0] == "/opt/wacli"


def test_send_text_raises_on_nonzero(monkeypatch):
    _capture(monkeypatch, result=_Result(returncode=1, stderr="not authenticated"))
    with pytest.raises(WacliError, match="not authenticated"):
        WacliClient(send_template=DEFAULT_TEMPLATE).send_text("5213314872210", "x")


def test_send_file_builds_command(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient()
    client.bin = "wacli"
    client.send_file("3314872210", "/tmp/factura.pdf", caption="Tu factura", filename="factura.pdf")
    assert calls["command"] == [
        "wacli", "send", "file",
        "--to", "5213314872210@s.whatsapp.net",
        "--file", "/tmp/factura.pdf",
        "--lock-wait", "30s",
        "--caption", "Tu factura",
        "--filename", "factura.pdf",
    ]


def test_send_file_sin_caption_ni_filename(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient()
    client.bin = "wacli"
    client.send_file("5213314872210", "/tmp/x.png")
    cmd = calls["command"]
    assert "--caption" not in cmd and "--filename" not in cmd
    assert cmd[cmd.index("--file") + 1] == "/tmp/x.png"


def test_send_file_raises_on_nonzero(monkeypatch):
    _capture(monkeypatch, result=_Result(returncode=1, stderr="boom"))
    with pytest.raises(WacliError, match="boom"):
        WacliClient().send_file("5213314872210", "/tmp/x.pdf")


# ---------- aislamiento por tenant: --store (flag global de wacli 0.8.x) ----------

def test_send_text_con_store_propio_agrega_el_flag(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient(send_template=DEFAULT_TEMPLATE, store_dir="/stores/inst-a")
    client.bin = "wacli"
    client.send_text("5213314872210", "hola")
    cmd = calls["command"]
    assert cmd[cmd.index("--store") + 1] == "/stores/inst-a"


def test_send_text_sin_store_no_toca_el_default(monkeypatch):
    """Modo clásico (self-host de un solo número): sin store_dir el comando queda
    idéntico al de siempre, contra el store default del host."""
    calls = _capture(monkeypatch)
    client = WacliClient(send_template=DEFAULT_TEMPLATE)
    client.bin = "wacli"
    client.send_text("5213314872210", "hola")
    assert "--store" not in calls["command"]


def test_send_file_y_lecturas_llevan_el_mismo_store(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient(store_dir="/stores/inst-b")
    client.bin = "wacli"
    client.send_file("5213314872210", "/tmp/x.pdf")
    assert calls["command"][calls["command"].index("--store") + 1] == "/stores/inst-b"

    class _JsonResult:
        returncode = 0
        stderr = ""
        stdout = '{"data": []}'

    monkeypatch.setattr(wacli_mod.subprocess, "run", lambda cmd, **kw: calls.update(command=cmd) or _JsonResult())
    client.list_chats()
    assert calls["command"][calls["command"].index("--store") + 1] == "/stores/inst-b"
