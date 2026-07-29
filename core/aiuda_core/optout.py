"""Opt-out de mensajes automatizados: el cliente escribe BAJA/STOP y no se le envía más.

El registro vive en ``Tenant.config["optouts"]`` (sin migración): la llave es
``contact_key`` del destinatario — ``match_key(teléfono)`` (últimos 10 dígitos,
estable ante 52 vs 521) para WhatsApp/SMS, o el correo normalizado (minúsculas)
para el canal de correo — y el valor ``{"at": iso, "via": "whatsapp"|"correo"}``.
La baja es POR MEDIO de contacto: quien pide BAJA por correo deja de recibir
correos automatizados; su WhatsApp es otra llave.

Alcance honesto:
- Bloquea los envíos AUTOMATIZADOS (recordatorios y seguimientos del agente).
- El dueño humano puede seguir escribiendo desde la consola (soberanía humana);
  la ficha del cliente muestra el aviso para que decida con contexto.
- Si el cliente escribe de nuevo, el agente puede responderle (conversación que
  él inició); lo que no regresa son los recordatorios, hasta que el dueño lo
  reactive desde la ficha.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

from aiuda_core.phones import match_key


class OptedOut(Exception):
    """El destinatario pidió no recibir mensajes (BAJA/STOP). No es un fallo del
    canal: es una decisión del cliente que se respeta. El recordatorio se marca
    'failed' con el motivo visible, nunca se reintenta solo."""


# El mensaje completo (normalizado) debe SER una de estas frases. Igualdad exacta,
# no contención: "no quiero darme de baja" NO debe marcar opt-out.
OPT_OUT_PHRASES = {
    "baja",
    "stop",
    "alto",
    "unsubscribe",
    "no molestar",
    "no me molesten",
    "no mas mensajes",
    "ya no me manden mensajes",
    "ya no quiero mensajes",
}

# Confirmación determinista (sin LLM): cortés, una sola vez, y honesta sobre qué
# se detiene. El dueño sigue pudiendo escribir en persona desde la consola.
OPT_OUT_CONFIRMATION = (
    "Entendido, ya no te enviaremos recordatorios por este medio. "
    "Si cambias de opinión, escríbenos cuando quieras."
)


def contact_key(value) -> str:
    """Llave estable del destinatario para el registro de bajas: un correo (trae
    ``@``) se normaliza a minúsculas; un teléfono pasa por ``match_key``. Cadena
    vacía si no da una llave usable (no se arriesga un match con basura)."""
    text = str(value or "").strip()
    if "@" in text:
        return text.lower()
    return match_key(text)


def _normalize(text: str) -> str:
    """minúsculas, sin acentos, sin puntuación en los bordes, espacios colapsados."""
    lowered = unicodedata.normalize("NFKD", str(text or "").lower())
    stripped = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in stripped)
    return " ".join(cleaned.split())


def is_opt_out(body: str) -> bool:
    """¿El mensaje es una solicitud de baja? Igualdad exacta tras normalizar."""
    return _normalize(body) in OPT_OUT_PHRASES


def opted_out(config: dict | None, phone: str) -> dict | None:
    """El registro de opt-out del destinatario (teléfono o correo) — ({"at", "via"})
    o None si puede recibir."""
    key = contact_key(phone)
    if not key:
        return None
    entry = ((config or {}).get("optouts") or {}).get(key)
    return dict(entry) if isinstance(entry, dict) else None


def mark_opt_out(tenant, phone: str, via: str = "whatsapp") -> bool:
    """Registra la baja en tenant.config (reasigna el dict para que SQLAlchemy la
    persista). Devuelve False si el destinatario no da una llave usable."""
    key = contact_key(phone)
    if not key:
        return False
    cfg = dict(tenant.config or {})
    optouts = dict(cfg.get("optouts") or {})
    optouts[key] = {"at": datetime.now(timezone.utc).isoformat(), "via": via}
    cfg["optouts"] = optouts
    tenant.config = cfg
    return True


def clear_opt_out(tenant, phone: str) -> bool:
    """Quita la baja (el dueño reactiva desde la ficha, p.ej. si el cliente se lo
    pidió). Devuelve True si había registro que quitar."""
    key = contact_key(phone)
    cfg = dict(tenant.config or {})
    optouts = dict(cfg.get("optouts") or {})
    if key not in optouts:
        return False
    optouts.pop(key)
    cfg["optouts"] = optouts
    tenant.config = cfg
    return True
