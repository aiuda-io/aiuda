"""WhatsApp entrante (wacli) DENTRO del proceso de `aiuda start`.

wacli no empuja mensajes: hay que sondearlos. Antes eso era un daemon aparte
(scripts/wacli_inbound.py + systemd/launchd); en local-first el sondeo vive en
un hilo del mismo proceso, así que UN comando recibe y procesa WhatsApp.

La ingesta es LA MISMA que la del webhook (conversación + dedupe por
wa_message_id + procesamiento del agente): ``ingresar_entrante`` es la función
compartida. El estado "qué ya vi" persiste en ~/.aiuda/ igual que el daemon
viejo, así que actualizar no re-importa historia.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from aiuda_core.config import settings
from aiuda_core.db import default_data_dir, session_scope
from aiuda_core.models import Conversation, Message, Tenant
from aiuda_core.phones import normalize_mx

log = logging.getLogger("aiuda.inbound")


def ingresar_entrante(db, tenant, *, phone: str, body: str, wa_id: str | None):
    """Registra un mensaje entrante (conversación + fila Message, con dedupe).
    Devuelve el Message nuevo o None si se ignoró/duplicó. NO procesa el agente:
    eso lo decide el caller (BackgroundTasks en el webhook, inline en el poller)."""
    phone = normalize_mx(str(phone or "").strip())
    body = str(body or "").strip()
    if not phone or not body:
        return None

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.remote_phone == phone
        )
    )
    if conversation is None:
        conversation = Conversation(tenant_id=tenant.id, remote_phone=phone)
        db.add(conversation)
        db.flush()

    if wa_id:
        duplicate = db.scalar(
            select(Message).where(Message.tenant_id == tenant.id, Message.wa_message_id == wa_id)
        )
        if duplicate is not None:
            return None

    message = Message(
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        direction="in",
        body=body,
        wa_message_id=wa_id or None,
    )
    db.add(message)
    db.flush()
    return message


def _wacli_tenants(db) -> list[tuple[str, str]]:
    """[(tenant_id, instance)] de los negocios con WhatsApp conectado vía wacli."""
    out: list[tuple[str, str]] = []
    for tenant in db.scalars(select(Tenant)).all():
        wa = ((tenant.config or {}).get("integrations") or {}).get("whatsapp") or {}
        if wa.get("via") == "wacli":
            out.append((tenant.id, wa.get("instance") or tenant.evolution_instance))
    return out


def _state_path(instance: str) -> Path:
    # Misma convención que el daemon viejo: el estado sobrevive la migración.
    name = f"wacli_inbound.{instance}.json" if settings.wacli_store_root else "wacli_inbound.json"
    return default_data_dir() / name


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def poll_wacli_once(client_factory=None) -> int:
    """Un sondeo de TODOS los negocios con wacli: junta lo nuevo, lo ingresa y lo
    procesa inline. Devuelve cuántos mensajes entraron. Nunca lanza por un negocio:
    el fallo de uno no detiene a los demás."""
    from aiuda_core.connectors.wacli import WacliClient
    from aiuda_core.connectors.wacli_inbound import collect_inbound
    from aiuda_server.worker.main import process_incoming_message_blocking

    with session_scope() as db:
        objetivos = _wacli_tenants(db)
    total = 0
    for tenant_id, instance in objetivos:
        try:
            store_dir = (
                str(Path(settings.wacli_store_root) / instance)
                if settings.wacli_store_root
                else None
            )
            client = (
                client_factory(instance) if client_factory else WacliClient(store_dir=store_dir)
            )
            state_path = _state_path(instance)
            posts, new_state = collect_inbound(
                client.list_chats(), client.list_messages, _load_state(state_path)
            )
            nuevos: list[str] = []
            with session_scope() as db:
                tenant = db.get(Tenant, tenant_id)
                for payload in posts:
                    message = ingresar_entrante(
                        db,
                        tenant,
                        phone=payload.get("phone", ""),
                        body=payload.get("message", ""),
                        wa_id=payload.get("id") or None,
                    )
                    if message is not None:
                        nuevos.append(message.id)
            # El estado se guarda DESPUÉS de persistir los mensajes: si algo truena
            # a media ingesta, el siguiente sondeo reintenta (el dedupe absorbe).
            _save_state(state_path, new_state)
            for message_id in nuevos:
                process_incoming_message_blocking(tenant_id, message_id)
            total += len(nuevos)
        except Exception:  # noqa: BLE001 — un negocio con wacli caído no tumba el sondeo
            log.exception("sondeo wacli falló para %s", instance)
    return total
