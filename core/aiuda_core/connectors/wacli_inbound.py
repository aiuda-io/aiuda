"""Entrada de WhatsApp por wacli: convierte los mensajes recibidos en posts al webhook.

wacli no empuja los mensajes entrantes: hay que sondearlos. Este módulo sondea las
conversaciones (`chats list` / `messages list`, verificados en 0.8.1) y arma el contrato
que espera `/v1/webhooks/wacli`: {phone, message, id}. La lógica pura (qué es nuevo) está
separada del IO (subprocess wacli + HTTP) para poder probarla sin wacli ni red.

Anti-replay: en la primera vez que ve una conversación NO reenvía el historial (sembraría
al agente con mensajes viejos); solo siembra el punto de partida. De ahí en adelante reenvía
lo que llega después. El webhook además deduplica por `id`, así que un reenvío es inofensivo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import datetime

from aiuda_core.phones import digits_from_jid

# Cuántos ids recientes recordar por conversación (red anti-reenvío para mensajes cuyo
# timestamp no se puede ordenar). Acotado para que el estado no crezca sin control.
_MAX_SEEN_IDS = 50


def _first(msg: dict, *keys: str):
    """Primer valor no vacío entre varias posibles llaves (wacli varía el nombre)."""
    for k in keys:
        if k in msg and msg[k] not in (None, ""):
            return msg[k]
    return None


def _from_me(msg: dict) -> bool:
    return bool(_first(msg, "FromMe", "fromMe", "from_me"))


def _text(msg: dict) -> str:
    return str(_first(msg, "Text", "DisplayText", "Body", "Message", "text") or "").strip()


def _ts(msg: dict) -> float | None:
    """Timestamp como epoch (float) para poder ordenar. Acepta número epoch o ISO-8601.
    None si no se puede interpretar (entonces se ordena por id, no por tiempo)."""
    raw = _first(msg, "Timestamp", "timestamp", "ts", "Time")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _msg_id(msg: dict, jid: str, text: str, ts: float | None) -> str:
    """Id estable del mensaje para la deduplicación del webhook. Usa el id nativo de wacli
    si lo trae; si no, uno determinístico de (jid, ts, texto) para no reenviar el mismo."""
    native = _first(msg, "MsgID", "Id", "ID", "MessageID", "message_id", "key_id")
    if native:
        return str(native)
    seed = f"{jid}|{ts}|{text}".encode()
    return "wacli-" + hashlib.sha1(seed).hexdigest()[:20]


def select_new(messages: Iterable[dict], chat_jid: str, chat_state: dict | None) -> tuple[list[dict], dict]:
    """Mensajes entrantes nuevos de una conversación + el estado actualizado.

    `chat_state` es None la primera vez (conversación no vista): se siembra sin reenviar
    nada. Después, un mensaje es nuevo si su id no se ha visto y su timestamp es posterior
    al último sembrado. Devuelve (posts, nuevo_estado). Cada post = {phone, message, id}.
    """
    seeding = chat_state is None
    last_ts: float | None = (chat_state or {}).get("last_ts")
    seen_ids: list[str] = list((chat_state or {}).get("ids") or [])
    seen = set(seen_ids)
    phone = digits_from_jid(chat_jid)

    posts: list[dict] = []
    max_ts = last_ts
    for msg in messages:
        if _from_me(msg):
            continue
        text = _text(msg)
        if not text:
            continue
        ts = _ts(msg)
        mid = _msg_id(msg, chat_jid, text, ts)
        if ts is not None:
            max_ts = ts if max_ts is None else max(max_ts, ts)
        if mid in seen:
            continue
        seen.add(mid)
        seen_ids.append(mid)
        # Al sembrar (primera vez) no se reenvía nada; solo se registra lo visto. Después,
        # si el mensaje trae timestamp anterior al sembrado, es historia: no reenviar.
        if seeding:
            continue
        if ts is not None and last_ts is not None and ts <= last_ts:
            continue
        posts.append({"phone": phone, "message": text, "id": mid})

    new_state = {"last_ts": max_ts, "ids": seen_ids[-_MAX_SEEN_IDS:]}
    return posts, new_state


def collect_inbound(
    chats: Iterable[dict],
    list_messages: Callable[[str], list[dict]],
    state: dict,
) -> tuple[list[dict], dict]:
    """Recorre las conversaciones DM y junta los mensajes entrantes nuevos.

    `state` mapea jid → estado por conversación; se devuelve actualizado. Los grupos
    (kind != 'dm') se ignoran: la cobranza es 1 a 1, no en grupos."""
    posts: list[dict] = []
    new_state = dict(state)
    for chat in chats:
        if chat.get("kind") not in (None, "dm"):
            continue  # solo conversaciones directas
        jid = chat.get("jid")
        if not jid:
            continue
        chat_posts, chat_state = select_new(list_messages(jid), jid, state.get(jid))
        posts.extend(chat_posts)
        new_state[jid] = chat_state
    return posts, new_state
