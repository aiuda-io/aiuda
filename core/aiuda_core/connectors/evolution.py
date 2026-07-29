"""Conector a Evolution API (WhatsApp). Desacoplado: si Meta cambia reglas,
sólo se toca este módulo (alternativa futura: WhatsApp Cloud API oficial)."""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings
from aiuda_core.phones import normalize_mx


@dataclass
class IncomingMessage:
    instance: str
    remote_phone: str
    body: str
    wa_message_id: str
    from_me: bool


def parse_webhook(payload: dict) -> IncomingMessage | None:
    """Normaliza el evento messages.upsert de Evolution API. Devuelve None si no es
    un mensaje de texto procesable."""
    if payload.get("event") not in ("messages.upsert", "MESSAGES_UPSERT"):
        return None
    data = payload.get("data") or {}
    key = data.get("key") or {}
    message = data.get("message") or {}
    body = message.get("conversation") or (message.get("extendedTextMessage") or {}).get("text")
    if not body:
        return None
    remote_jid = key.get("remoteJid", "")
    if "@g.us" in remote_jid:  # grupos fuera de alcance v1
        return None
    return IncomingMessage(
        instance=payload.get("instance", ""),
        remote_phone=remote_jid.split("@")[0],
        body=body,
        wa_message_id=key.get("id", ""),
        from_me=bool(key.get("fromMe")),
    )


class EvolutionClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or settings.evolution_base_url).rstrip("/")
        self.api_key = api_key or settings.evolution_api_key

    def send_text(self, instance: str, phone: str, text: str) -> dict:
        if not self.base_url:
            raise RuntimeError(
                "EVOLUTION_BASE_URL no configurado — ver .env.example"
            )
        response = httpx.post(
            f"{self.base_url}/message/sendText/{instance}",
            headers={"apikey": self.api_key},
            json={"number": normalize_mx(phone), "text": text},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
