"""Conector Slack — avisos internos al equipo del negocio.

Para qué lo usa aiuda: los avisos que el producto YA genera salen también al
canal de Slack del negocio si está conectado (ver `aviso_al_equipo`): hoy el
resumen diario de cartera y el aviso de corte de IA por tope. Nada nuevo se
inventa: es el mismo texto, por un canal más.

Auth: bot token (xoxb-…) instalado por el admin del workspace + canal destino,
cifrados por tenant (connectors/credentials.py). Contrato: chat.postMessage y
auth.test documentados. PENDIENTE de verificar en vivo: no hay workspace real.
Docs: https://api.slack.com/methods
"""

import logging
from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://slack.com/api"

log = logging.getLogger("aiuda.slack")


@dataclass
class MensajeSlack:
    ts: str
    channel: str


class SlackClient:
    def __init__(
        self,
        bot_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.bot_token = bot_token or settings.slack_bot_token
        if not self.bot_token:
            raise RuntimeError("SLACK_BOT_TOKEN no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.bot_token}"},
            timeout=30,
            transport=transport,
        )

    def post_message(self, channel: str, text: str) -> str:
        """Envía un mensaje de texto a un canal o usuario de Slack.

        Devuelve el timestamp (ts) del mensaje enviado, que sirve como
        identificador único para crear hilos o actualizar el mensaje después.
        Si Slack regresa ok=false (canal inexistente, bot sin permisos, etc.)
        levanta RuntimeError con el código de error de la API.
        """
        response = self._http.post(
            "/chat.postMessage",
            json={"channel": channel, "text": text},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "slack_error_desconocido"))
        return data["ts"]

    def test_connection(self) -> dict:
        """Verifica el bot token contra la API real: auth.test (documentado).
        Devuelve workspace y usuario del bot para el semáforo. No publica nada."""
        response = self._http.post("/auth.test")
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "slack_error_desconocido"))
        return {"team": data.get("team") or "", "user": data.get("user") or ""}


def aviso_al_equipo(
    session,
    tenant_id: str,
    texto: str,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """Publica un aviso interno en el Slack del tenant, si lo conectó.

    Punto de uso de la capacidad `avisos_equipo`: el que avisa (worker/motor) llama
    aquí con el MISMO texto que ya genera. Resuelve bot token + canal de la
    credencial cifrada por tenant (con sus fallbacks) y publica. No-op honesto y
    silencioso hacia el flujo: sin credencial o sin canal devuelve False; un error
    de red/API se registra y devuelve False — un aviso caído nunca tumba la corrida.
    """
    from aiuda_core.connectors.credentials import get_credential

    try:
        creds = get_credential(session, tenant_id, "slack")
    except Exception as exc:  # noqa: BLE001 — credencial ilegible = aviso, no crash
        log.warning("aviso a Slack omitido (credencial ilegible): %s", exc)
        return False
    if not creds or not creds.get("bot_token") or not creds.get("channel"):
        return False  # no conectado o sin canal: el aviso simplemente no sale por aquí
    try:
        SlackClient(bot_token=creds["bot_token"], transport=transport).post_message(
            creds["channel"], texto
        )
        return True
    except Exception as exc:  # noqa: BLE001 — canal caído no debe abortar el flujo
        log.warning("aviso a Slack falló: %s", exc)
        return False
