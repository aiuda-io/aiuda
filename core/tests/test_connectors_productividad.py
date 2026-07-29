"""Conectores de productividad: Slack, HubSpot — request correcto + parsing.

Ninguno toca la red real: httpx.MockTransport intercepta todo.
"""

import json

import httpx
import pytest

from aiuda_core.connectors.hubspot import HubSpotClient
from aiuda_core.connectors.slack import SlackClient


def transport(handler):
    return httpx.MockTransport(handler)


# ────────────────────────── Slack ──────────────────────────


def test_slack_post_message_ok():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "ts": "1717900000.000100"})

    client = SlackClient(bot_token="xoxb-test", transport=transport(handler))
    ts = client.post_message("#alertas", "Resumen diario listo")

    assert captured["path"] == "/api/chat.postMessage"
    assert captured["auth"] == "Bearer xoxb-test"
    assert captured["body"]["channel"] == "#alertas"
    assert captured["body"]["text"] == "Resumen diario listo"
    assert ts == "1717900000.000100"


def test_slack_post_message_error_api():
    """Cuando Slack devuelve ok=false se lanza RuntimeError con el campo error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    client = SlackClient(bot_token="xoxb-test", transport=transport(handler))
    with pytest.raises(RuntimeError, match="channel_not_found"):
        client.post_message("#inexistente", "hola")


def test_slack_sin_credenciales_truena():
    with pytest.raises(RuntimeError, match="SLACK_BOT_TOKEN"):
        SlackClient(bot_token="")


# ────────────────────────── HubSpot ──────────────────────────

DEALS_RESPONSE = {
    "results": [
        {
            "id": "deal-001",
            "properties": {
                "dealname": "Proyecto Reforma Fiscal",
                "amount": "85000.50",
                "dealstage": "appointmentscheduled",
            },
        },
        {
            "id": "deal-002",
            "properties": {
                "dealname": "Consultoría IMSS",
                "amount": None,
                "dealstage": "qualifiedtobuy",
            },
        },
    ]
}


def test_hubspot_list_open_deals_params_y_parsing():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=DEALS_RESPONSE)

    client = HubSpotClient(token="pat-test", transport=transport(handler))
    oportunidades = client.list_open_deals(limit=25)

    assert captured["path"] == "/crm/v3/objects/deals"
    assert captured["params"]["limit"] == "25"
    assert "dealname" in captured["params"]["properties"]
    assert captured["auth"] == "Bearer pat-test"

    assert len(oportunidades) == 2

    op1 = oportunidades[0]
    assert op1.id == "deal-001"
    assert op1.nombre == "Proyecto Reforma Fiscal"
    assert op1.monto == 85000.50
    assert op1.etapa == "appointmentscheduled"

    # amount None debe resolverse como 0.0
    op2 = oportunidades[1]
    assert op2.monto == 0.0


def test_hubspot_create_contact_ok():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "contact-555"})

    client = HubSpotClient(token="pat-test", transport=transport(handler))
    contact_id = client.create_contact("carlos@ejemplo.mx", "Carlos López", "5512345678")

    props = captured["body"]["properties"]
    assert props["email"] == "carlos@ejemplo.mx"
    assert props["firstname"] == "Carlos López"
    assert props["phone"] == "5512345678"
    assert contact_id == "contact-555"


def test_hubspot_create_contact_409_truena():
    """Si el contacto ya existe en HubSpot (409) se lanza RuntimeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"status": "error", "message": "Contact already exists"})

    client = HubSpotClient(token="pat-test", transport=transport(handler))
    with pytest.raises(RuntimeError, match="ya existe en HubSpot"):
        client.create_contact("repetido@ejemplo.mx", "Ya Existe")


def test_hubspot_sin_credenciales_truena():
    with pytest.raises(RuntimeError, match="HUBSPOT_TOKEN"):
        HubSpotClient(token="")
