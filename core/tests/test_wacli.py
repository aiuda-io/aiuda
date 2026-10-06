"""wacli: construcción del comando + manejo de error, sin tocar el binario real.

Monkeypatcheamos subprocess.run para capturar el argv EXACTO que se ejecutaría.
Esto fija el contrato con wacli 0.8.x en adelante (`send text --to/--message`).
"""

import pytest

from aiuda_core.config import Settings
from aiuda_core.connectors import wacli as wacli_mod
from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.wacli import WacliClient, WacliError, explicar_fallo_wacli

DEFAULT_TEMPLATE = "{bin} send text --to {phone} --message {message}"
# Una ruta que no existe: si alguna prueba olvidara interceptar subprocess.run, el
# sistema no encontraría nada que ejecutar.
BIN_DE_PRUEBA = "/sin-wacli/wacli"


@pytest.fixture(autouse=True)
def _como_en_la_computadora_del_dueno(monkeypatch):
    """Estas pruebas fijan el argv del modo de siempre: hay un wacli instalado y
    aiuda corre sobre la base del dueño, así que sin store propio no se pasa
    ``--store``. La corrida de pruebas usa una base desechable, donde la regla es
    la contraria (ver ``test_wacli_store.py``); aquí se simula la del dueño."""
    monkeypatch.setattr(wacli_bin, "_del_sistema", lambda: BIN_DE_PRUEBA)
    monkeypatch.setattr(wacli_bin, "store_del_host", lambda: None)


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
    ]


def _en_orden(monkeypatch, resultados):
    """subprocess.run que contesta lo de `resultados`, uno por llamada."""
    comandos: list[list[str]] = []
    pendientes = list(resultados)

    def fake_run(command, **kwargs):
        comandos.append(command)
        return pendientes.pop(0)

    monkeypatch.setattr(wacli_mod.subprocess, "run", fake_run)
    return comandos


OCUPADO = "store is locked (another wacli is running?): store locked: /x/LOCK (pid=1)"


def test_el_envio_va_sin_espera_para_que_el_sync_vivo_lo_despache(monkeypatch):
    """Con --lock-wait wacli espera el plazo completo antes de delegarle el envío
    al sync (32 s, visto con 0.18.2); sin él sale en 2 o 3."""
    comandos = _en_orden(monkeypatch, [_Result(), _Result()])
    client = WacliClient()
    client.send_text("5213314872210", "hola")
    client.send_file("5213314872210", "/tmp/x.pdf")
    assert all("--lock-wait" not in c for c in comandos)


@pytest.mark.parametrize("envio", ["texto", "archivo"])
def test_con_el_store_ocupado_se_repite_esperando_el_candado(monkeypatch, envio):
    comandos = _en_orden(monkeypatch, [_Result(returncode=1, stderr=OCUPADO), _Result()])
    client = WacliClient()
    if envio == "texto":
        client.send_text("5213314872210", "hola")
    else:
        client.send_file("5213314872210", "/tmp/x.pdf")
    assert len(comandos) == 2
    assert comandos[1] == [*comandos[0], "--lock-wait", "30s"]


def test_si_esperando_tampoco_sale_ya_no_se_insiste(monkeypatch):
    tarde = "timed out waiting for store lock after 30s: store locked"
    comandos = _en_orden(
        monkeypatch, [_Result(returncode=1, stderr=OCUPADO), _Result(returncode=1, stderr=tarde)]
    )
    with pytest.raises(WacliError, match="timed out waiting"):
        WacliClient().send_text("5213314872210", "hola")
    assert len(comandos) == 2


A_SI_MISMO = (
    "send text to the linked account itself is not supported: WhatsApp can acknowledge "
    "self-messages without delivering them; use the official Message Yourself chat"
)


def test_al_numero_vinculado_se_repite_con_allow_self(monkeypatch):
    """El resumen y las respuestas al dueño, cuando el número conectado es el suyo."""
    comandos = _en_orden(monkeypatch, [_Result(returncode=1, stderr=A_SI_MISMO), _Result()])
    WacliClient().send_text("5213314872210", "hola")
    assert "--allow-self" not in comandos[0]
    assert comandos[1] == [*comandos[0], "--allow-self"]


def test_a_cualquier_otro_numero_no_va_allow_self(monkeypatch):
    comandos = _en_orden(monkeypatch, [_Result()])
    WacliClient().send_text("5213314872210", "hola")
    assert len(comandos) == 1 and "--allow-self" not in comandos[0]


def test_si_con_allow_self_tampoco_sale_se_dice_en_espanol(monkeypatch):
    comandos = _en_orden(monkeypatch, [_Result(returncode=1, stderr=A_SI_MISMO)] * 2)
    with pytest.raises(WacliError) as fallo:
        WacliClient().send_text("5213314872210", "hola")
    assert len(comandos) == 2
    assert explicar_fallo_wacli(fallo.value) == "No se puede enviar un mensaje a tu propio número."


def test_otra_falla_no_se_reintenta(monkeypatch):
    comandos = _en_orden(monkeypatch, [_Result(returncode=1, stderr="not connected")])
    with pytest.raises(WacliError, match="not connected"):
        WacliClient().send_text("5213314872210", "hola")
    assert len(comandos) == 1


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


@pytest.mark.parametrize(
    ("crudo", "empieza"),
    [
        ("not authenticated; run `wacli auth`", "Tu WhatsApp no está vinculado."),
        ("WhatsApp session was revoked: device_removed", "WhatsApp cerró la sesión"),
        (
            "store is locked (another wacli is running?): store locked: /x/LOCK (pid=1)",
            "WhatsApp está ocupado",
        ),
        ("timed out waiting for store lock after 30s: store locked", "WhatsApp está ocupado"),
        (
            "no reply from the running sync process before the timeout; the text may still "
            "have gone through, so check before retrying",
            "No supimos si el mensaje salió.",
        ),
        ("request deadline passed before dispatch; it was not sent", "El mensaje no salió"),
        ("send timed out after 30s", "El mensaje no salió"),
        ("not connected", "No hay conexión con WhatsApp."),
        ("reconnect failed: websocket: close 1006", "No hay conexión con WhatsApp."),
        ("WhatsApp client outdated; update wacli and try again", "WhatsApp pidió una versión"),
        ("QR code timed out; run `wacli auth` again to get a new code", "El código QR caducó."),
        ("QR scanned, but multi-device is not enabled on the phone", "Tu WhatsApp no tiene"),
        ("WhatsApp requires passkey verification", "Tu WhatsApp pide una llave de acceso"),
        ("send text to the linked account itself is not supported", "No se puede enviar"),
        ("file too large (9 bytes); maximum size is 1 bytes", "El archivo es demasiado grande"),
        ("no LID found for 5215500000000", "Ese número no parece tener WhatsApp."),
        ("panic: algo que nadie previó", "WhatsApp no pudo enviar el mensaje."),
    ],
)
def test_explicar_fallo_dice_en_espanol_lo_que_wacli_dice_en_ingles(crudo, empieza):
    dicho = explicar_fallo_wacli(WacliError(crudo))
    assert dicho.startswith(empieza)
    # Nunca se cuela el texto crudo ni el nombre de la herramienta.
    assert crudo not in dicho and "wacli" not in dicho


def test_explicar_fallo_por_tipo_de_excepcion():
    import subprocess

    corte = subprocess.TimeoutExpired(cmd="wacli", timeout=60)
    assert explicar_fallo_wacli(corte).startswith("No supimos si el mensaje salió.")
    assert "presiona Instalar" in explicar_fallo_wacli(FileNotFoundError("wacli"))


def test_send_file_builds_command(monkeypatch):
    calls = _capture(monkeypatch)
    client = WacliClient()
    client.bin = "wacli"
    client.send_file("3314872210", "/tmp/factura.pdf", caption="Tu factura", filename="factura.pdf")
    assert calls["command"] == [
        "wacli", "send", "file",
        "--to", "5213314872210@s.whatsapp.net",
        "--file", "/tmp/factura.pdf",
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
