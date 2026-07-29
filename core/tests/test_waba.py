"""Contrato del conector oficial de WhatsApp Business (Cloud API de Meta).

HONESTO: las respuestas de este archivo son fixtures GRABADOS DE LA DOCUMENTACIÓN
pública de la Graph API (v23.0) — /PHONE_NUMBER_ID/messages y el webhook de
messages —, no de una cuenta real. El conector queda "pendiente de verificar en
vivo" hasta pegar con credenciales reales de Meta. Estos tests fijan el contrato:
qué mandamos (URL, auth, payload) y cómo interpretamos lo que responde.
"""

import json

import httpx
import pytest

from aiuda_core.connectors import waba as waba_mod
from aiuda_core.connectors.waba import WabaClient, WabaError, parse_webhook

BASE = "https://graph.facebook.com/v23.0"

# Respuesta de éxito de POST /{phone_number_id}/messages, tal cual la documenta Meta.
SEND_OK = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": "5215587654321", "wa_id": "5215587654321"}],
    "messages": [{"id": "wamid.HBgNNTIxNTU4NzY1NDMyMRUCABEYEjVGQTM2RkVDMUE5RkI2OTBCNwA="}],
}

# Error 131047 (re-engagement): texto libre fuera de la ventana de 24 h.
ERROR_24H = {
    "error": {
        "message": "(#131047) Re-engagement message",
        "type": "OAuthException",
        "code": 131047,
        "error_data": {
            "messaging_product": "whatsapp",
            "details": "Message failed to send because more than 24 hours have passed "
            "since the customer last replied to this number.",
        },
        "fbtrace_id": "Az8or2yhqkZfEZ-_bVIt0Bo",
    }
}

# Token inválido (190): credenciales mal capturadas o vencidas.
ERROR_TOKEN = {
    "error": {
        "message": "Invalid OAuth access token - Cannot parse access token",
        "type": "OAuthException",
        "code": 190,
        "fbtrace_id": "AbCdEfGh",
    }
}

# GET /{phone_number_id}?fields=... — verificación de credenciales.
PHONE_INFO = {
    "verified_name": "Hanova Consulting",
    "display_phone_number": "+52 1 55 1234 5678",
    "id": "111222333",
}

# Webhook entrante (object=whatsapp_business_account) con un mensaje de texto.
WEBHOOK_TEXT = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA-ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "5215512345678",
                            "phone_number_id": "111222333",
                        },
                        "contacts": [
                            {"profile": {"name": "Cliente Demo"}, "wa_id": "5215587654321"}
                        ],
                        "messages": [
                            {
                                "from": "5215587654321",
                                "id": "wamid.ID1",
                                "timestamp": "1750000000",
                                "text": {"body": "hola, ¿cuánto debo?"},
                                "type": "text",
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}

# Webhook de statuses (sent/delivered/read): se ignora sin error.
WEBHOOK_STATUS = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "WABA-ID",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "111222333"},
                        "statuses": [{"id": "wamid.ID1", "status": "delivered"}],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}


def _capture_post(monkeypatch, status=200, body=SEND_OK):
    calls: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers or {}
        calls["json"] = json
        return httpx.Response(status, json=body)

    monkeypatch.setattr(waba_mod.httpx, "post", fake_post)
    return calls


def test_send_text_contrato(monkeypatch):
    calls = _capture_post(monkeypatch)
    client = WabaClient("EAAG-token", "111222333", base_url=BASE)
    out = client.send_text("55 8765 4321", "Hola, su factura F-001.")
    assert calls["url"] == f"{BASE}/111222333/messages"
    assert calls["headers"]["Authorization"] == "Bearer EAAG-token"
    assert calls["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5215587654321",  # 10 dígitos locales → 521 canónico
        "type": "text",
        "text": {"preview_url": False, "body": "Hola, su factura F-001."},
    }
    assert out["messages"][0]["id"].startswith("wamid.")


def test_send_template_contrato(monkeypatch):
    calls = _capture_post(monkeypatch)
    client = WabaClient("EAAG-token", "111222333", base_url=BASE)
    client.send_template(
        "5215587654321", "recordatorio_pago", lang="es_MX", body_params=("F-001", "$1,200")
    )
    assert calls["json"]["type"] == "template"
    assert calls["json"]["template"]["name"] == "recordatorio_pago"
    assert calls["json"]["template"]["language"] == {"code": "es_MX"}
    assert calls["json"]["template"]["components"] == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "F-001"},
                {"type": "text", "text": "$1,200"},
            ],
        }
    ]


def test_error_131047_se_traduce_a_mensaje_accionable(monkeypatch):
    _capture_post(monkeypatch, status=400, body=ERROR_24H)
    client = WabaClient("EAAG-token", "111222333", base_url=BASE)
    with pytest.raises(WabaError, match="24 horas") as exc:
        client.send_text("5215587654321", "Hola")
    assert exc.value.code == 131047


def test_error_de_token_reporta_el_detalle(monkeypatch):
    _capture_post(monkeypatch, status=401, body=ERROR_TOKEN)
    client = WabaClient("mal-token", "111222333", base_url=BASE)
    with pytest.raises(WabaError, match="401") as exc:
        client.send_text("5215587654321", "Hola")
    assert exc.value.code == 190


def test_sin_credenciales_no_pega_a_la_red():
    client = WabaClient("", "", base_url=BASE)
    with pytest.raises(WabaError, match="credenciales"):
        client.send_text("5215587654321", "Hola")


def test_check_credentials_contrato(monkeypatch):
    calls: dict = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["url"] = url
        calls["params"] = params
        calls["headers"] = headers or {}
        return httpx.Response(200, json=PHONE_INFO)

    monkeypatch.setattr(waba_mod.httpx, "get", fake_get)
    client = WabaClient("EAAG-token", "111222333", base_url=BASE)
    info = client.check_credentials()
    assert calls["url"] == f"{BASE}/111222333"
    assert calls["params"] == {"fields": "display_phone_number,verified_name"}
    assert calls["headers"]["Authorization"] == "Bearer EAAG-token"
    assert info["verified_name"] == "Hanova Consulting"


# ---------- webhook entrante ----------

def test_parse_webhook_normaliza_mensaje_de_texto():
    msgs = parse_webhook(WEBHOOK_TEXT)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.phone_number_id == "111222333"  # rutea al tenant dueño del número
    assert m.remote_phone == "5215587654321"
    assert m.body == "hola, ¿cuánto debo?"
    assert m.wa_message_id == "wamid.ID1"
    assert m.profile_name == "Cliente Demo"


def test_parse_webhook_ignora_statuses_y_objetos_ajenos():
    assert parse_webhook(WEBHOOK_STATUS) == []
    assert parse_webhook({"object": "page", "entry": []}) == []
    assert parse_webhook({}) == []


def test_parse_webhook_ignora_tipos_no_texto():
    payload = json.loads(json.dumps(WEBHOOK_TEXT))
    payload["entry"][0]["changes"][0]["value"]["messages"][0] = {
        "from": "5215587654321",
        "id": "wamid.IMG",
        "type": "image",
        "image": {"id": "MEDIA-ID"},
    }
    assert parse_webhook(payload) == []
