"""Contrato del conector de LLAMADAS DE VOZ (Twilio) y su canal por tenant.

HONESTO: las respuestas son fixtures del contrato documentado de la API REST de
Twilio (2010-04-01), servidas por un transporte fake (MockTransport), NO de una
cuenta real. El conector queda 'pendiente de verificar en vivo' hasta pegar con
credenciales reales. Estos tests fijan qué mandamos (URL, auth básica, TwiML) y cómo
interpretamos lo que responde, más el canal por tenant (resolve con/sin credencial).
"""

from urllib.parse import parse_qsl

import httpx
import pytest

from aiuda_core.connectors import channel as channel_mod
from aiuda_core.connectors.channel import (
    TwilioVozInstance,
    get_channel_sender,
    get_voz_sender,
    live_channels,
    resolve_voz,
)
from aiuda_core.connectors.credentials import set_credential
from aiuda_core.connectors.twilio_voz import (
    STATUS_OK,
    TwilioVozClient,
    TwilioVozError,
    e164_mx,
    parse_status_webhook,
    twiml_say,
)
from aiuda_core.models import Tenant

ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
AUTH_TOKEN = "tok-secreto"

CALL_CREATED = {"sid": "CA111", "status": "queued", "to": "+5215587654321"}
ACCOUNT_INFO = {"friendly_name": "Hanova Consulting", "status": "active", "sid": ACCOUNT_SID}
NUMBERS_INFO = {"incoming_phone_numbers": [{"phone_number": "+5215512345678", "sid": "PN1"}]}


def _client(handler, status_default=201) -> TwilioVozClient:
    return TwilioVozClient(
        account_sid=ACCOUNT_SID, auth_token=AUTH_TOKEN,
        transport=httpx.MockTransport(handler),
    )


# ---------- e164 y TwiML ----------

def test_e164_mx_normaliza_las_formas_de_la_base():
    assert e164_mx("55 8765 4321") == "+525587654321"  # 10 dígitos locales
    assert e164_mx("525587654321") == "+525587654321"  # 52 + 10 (Odoo/Excel)
    assert e164_mx("5215587654321") == "+525587654321"  # 521 + 10 (WhatsApp): sin el '1'
    assert e164_mx("+52 1 55 8765 4321") == "+525587654321"
    assert e164_mx("") == ""


def test_twiml_dice_en_es_mx_y_escapa_el_texto():
    xml = twiml_say('Debe $1,200 a García & Cía. <urge>')
    assert '<Say language="es-MX"' in xml
    assert "García &amp; Cía. &lt;urge&gt;" in xml  # XML-escapado: no rompe el TwiML
    assert xml.startswith("<Response>") and xml.endswith("</Response>")


# ---------- crear la llamada (POST /Calls.json) ----------

def test_llamar_recordatorio_crea_call_con_twiml_correcto():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = dict(parse_qsl(request.content.decode()))
        return httpx.Response(201, json=CALL_CREATED)

    sid = _client(handler).llamar_recordatorio(
        "55 8765 4321", "Su factura F-001 vence mañana.", "+5215512345678"
    )
    assert sid == "CA111"
    assert captured["method"] == "POST"
    assert captured["path"] == f"/2010-04-01/Accounts/{ACCOUNT_SID}/Calls.json"
    assert captured["auth"].startswith("Basic ")  # auth básica account_sid:auth_token
    body = captured["body"]
    assert body["To"] == "+525587654321"  # E.164 de voz (sin el '1' de WhatsApp)
    assert body["From"] == "+5215512345678"
    assert body["Twiml"] == twiml_say("Su factura F-001 vence mañana.")
    assert 'language="es-MX"' in body["Twiml"]
    assert "StatusCallback" not in body  # sin URL: no se pide callback


def test_llamar_recordatorio_incluye_status_callback_cuando_se_da():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = dict(parse_qsl(request.content.decode()))
        return httpx.Response(201, json=CALL_CREATED)

    _client(handler).llamar_recordatorio(
        "5215587654321", "Hola", "+5215512345678",
        status_callback="https://api.aiuda.mx/v1/webhooks/twilio-voz",
    )
    assert captured["body"]["StatusCallback"] == "https://api.aiuda.mx/v1/webhooks/twilio-voz"
    assert captured["body"]["StatusCallbackEvent"] == "completed"
    assert captured["body"]["StatusCallbackMethod"] == "POST"


def test_error_de_twilio_reporta_el_detalle():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 21211, "message": "Invalid 'To' Phone Number"})

    with pytest.raises(TwilioVozError, match="400") as exc:
        _client(handler).llamar_recordatorio("5215587654321", "Hola", "+5215512345678")
    assert exc.value.code == 21211  # el código de Twilio queda accesible


def test_sin_credenciales_no_pega_a_la_red():
    client = TwilioVozClient("", "", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(TwilioVozError, match="credenciales"):
        client.llamar_recordatorio("5215587654321", "Hola", "+5215512345678")


def test_sin_numero_de_origen_falla_honesto():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=CALL_CREATED)

    with pytest.raises(TwilioVozError, match="origen"):
        _client(handler).llamar_recordatorio("5215587654321", "Hola", "")


# ---------- probar conexión (GET cuenta + números) ----------

def test_test_connection_lee_cuenta_y_numeros():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/IncomingPhoneNumbers.json"):
            return httpx.Response(200, json=NUMBERS_INFO)
        return httpx.Response(200, json=ACCOUNT_INFO)

    info = _client(handler).test_connection()
    assert info["friendly_name"] == "Hanova Consulting"
    assert info["status"] == "active"
    assert info["numeros"] == 1
    assert info["primer_numero"] == "+5215512345678"


def test_test_connection_para_la_ui_falta_datos():
    from aiuda_core.connectors.twilio_voz import test_connection

    r = test_connection({"account_sid": "", "auth_token": ""})
    assert r["ok"] is False and "Faltan datos" in r["message"]


def test_test_connection_para_la_ui_avisa_si_no_hay_from(monkeypatch):
    from aiuda_core.connectors import twilio_voz as tv

    monkeypatch.setattr(
        tv.TwilioVozClient, "test_connection",
        lambda self: {"friendly_name": "Hanova", "status": "active", "numeros": 1, "primer_numero": "+521"},
    )
    r = tv.test_connection({"account_sid": ACCOUNT_SID, "auth_token": AUTH_TOKEN})
    assert r["ok"] is True and "Aviso" in r["details"]  # tiene número pero falta capturar from


# ---------- StatusCallback (webhook de estado) ----------

def test_parse_status_webhook_normaliza_el_resultado():
    estado = parse_status_webhook(
        {"CallSid": "CA111", "CallStatus": STATUS_OK, "AccountSid": ACCOUNT_SID,
         "To": "+521", "From": "+1", "CallDuration": "42"}
    )
    assert estado.call_sid == "CA111"
    assert estado.ok is True
    assert estado.motivo_falla is None
    assert estado.duration == "42"


def test_parse_status_webhook_traduce_las_fallas():
    for status, motivo in (("no-answer", "no contestó"), ("busy", "ocupado"), ("failed", "la llamada falló")):
        estado = parse_status_webhook({"CallSid": "CA1", "CallStatus": status})
        assert estado.ok is False
        assert estado.motivo_falla == motivo


def test_parse_status_webhook_ignora_payloads_sin_estado():
    assert parse_status_webhook({"CallSid": "CA1"}) is None
    assert parse_status_webhook({}) is None


# ---------- canal por tenant: resolve con/sin credencial ----------

def _tenant(session, name="Voz S.A.") -> Tenant:
    t = Tenant(name=name, owner_phone="5215500000000", evolution_instance="inst-v", config={})
    session.add(t)
    session.flush()
    return t


def test_resolve_voz_sin_credencial_es_none(session):
    t = _tenant(session)
    assert resolve_voz(session, t) is None
    assert "voz" not in live_channels(session, t)


def test_resolve_voz_incompleta_es_none(session):
    t = _tenant(session)
    # Falta from_number: canal honesto en None (no promete una llamada sin origen).
    set_credential(session, t.id, "twilio_voz", {"account_sid": ACCOUNT_SID, "auth_token": AUTH_TOKEN})
    assert resolve_voz(session, t) is None


def test_resolve_voz_completa_da_instancia_y_canal_vivo(session):
    t = _tenant(session)
    set_credential(session, t.id, "twilio_voz", {
        "account_sid": ACCOUNT_SID, "auth_token": AUTH_TOKEN, "from_number": "+5215512345678",
    })
    voz = resolve_voz(session, t)
    assert isinstance(voz, TwilioVozInstance)
    assert voz.from_number == "+5215512345678"
    assert "voz" in live_channels(session, t)


def test_get_voz_sender_llama_y_reporta_el_call_sid(monkeypatch):
    llamadas: list = []
    monkeypatch.setattr(
        channel_mod, "resolve_voz", lambda *a: None
    )  # no usado aquí; el sender se arma directo
    voz = TwilioVozInstance(creds={
        "account_sid": ACCOUNT_SID, "auth_token": AUTH_TOKEN, "from_number": "+5215512345678",
    })
    from aiuda_core.connectors import twilio_voz as tv

    monkeypatch.setattr(
        tv.TwilioVozClient, "llamar_recordatorio",
        lambda self, to, mensaje, from_number, status_callback=None: llamadas.append(
            (to, mensaje, from_number, status_callback)
        ) or "CA-XYZ",
    )
    sids: list = []
    sender = get_voz_sender(voz, status_callback="https://cb", on_call=sids.append)
    sender("5215587654321", "Su recordatorio")
    assert llamadas == [("5215587654321", "Su recordatorio", "+5215512345678", "https://cb")]
    assert sids == ["CA-XYZ"]  # el Call SID vuelve al caller para ligarlo al recordatorio


def test_get_channel_sender_voz_none_sin_instancia():
    assert get_channel_sender("voz", None, voz=None) is None
