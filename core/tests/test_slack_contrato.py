"""Contrato del conector Slack contra la Web API documentada.

El fixture (``data/slack_contrato.json``) sigue los ejemplos oficiales de
chat.postMessage y auth.test, servido por MockTransport. Honesto: NO es una
respuesta grabada en vivo (no hay workspace conectado); cuando haya bot token
real se graba y reemplaza. Peculiaridad del contrato de Slack que se blinda
aquí: los errores llegan con HTTP 200 y ok=false — raise_for_status NO basta.
"""

import json
from pathlib import Path

import httpx
import pytest

from aiuda_core.connectors.slack import SlackClient

FIXTURE = Path(__file__).parent / "data" / "slack_contrato.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_respeta_el_contrato_documentado():
    """Guardia del contrato: éxito trae ok/channel/ts (+message), el error trae
    ok=false y el campo error; auth.test trae team y user."""
    fx = _fixture()
    assert {"ok", "channel", "ts", "message"} <= set(fx["post_message_ok"].keys())
    assert fx["post_message_ok"]["ok"] is True
    assert fx["post_message_error"] == {"ok": False, "error": "channel_not_found"}
    assert {"ok", "url", "team", "user", "team_id", "user_id"} <= set(fx["auth_test_ok"].keys())
    assert fx["auth_test_error"]["ok"] is False


def test_post_message_contrato_documentado():
    fx = _fixture()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=fx["post_message_ok"])

    client = SlackClient(bot_token="xoxb-test", transport=httpx.MockTransport(handler))
    ts = client.post_message("#cobranza", "aiuda · Resumen de cartera — 07/07/2026")

    assert captured["path"] == "/api/chat.postMessage"
    assert captured["auth"] == "Bearer xoxb-test"
    assert captured["body"] == {
        "channel": "#cobranza",
        "text": "aiuda · Resumen de cartera — 07/07/2026",
    }
    assert ts == "1503435956.000247"


def test_post_message_error_llega_con_http_200():
    """Slack responde 200 con ok=false: el conector debe leer `error`, no confiar
    en el status HTTP."""
    fx = _fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fx["post_message_error"])

    client = SlackClient(bot_token="xoxb-test", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="channel_not_found"):
        client.post_message("#inexistente", "hola")


def test_auth_test_contrato_documentado():
    """auth.test: con qué verifica 'Probar conexión' el bot token (no publica)."""
    fx = _fixture()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=fx["auth_test_ok"])

    client = SlackClient(bot_token="xoxb-test", transport=httpx.MockTransport(handler))
    info = client.test_connection()

    assert captured["path"] == "/api/auth.test"
    assert captured["auth"] == "Bearer xoxb-test"
    assert info == {"team": "Despacho Ejemplo", "user": "aiuda"}


def test_auth_test_token_invalido():
    fx = _fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fx["auth_test_error"])

    client = SlackClient(bot_token="xoxb-revocado", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="invalid_auth"):
        client.test_connection()
