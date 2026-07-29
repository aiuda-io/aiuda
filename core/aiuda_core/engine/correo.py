"""Correo → bandeja unificada: la lectura IMAP vuelta hilos con clientes.

La corrida de sync (``sync_fuentes``) llama a ``sync_correo``: baja los correos
nuevos del buzón conectado (conector ``connectors/correo.py``) y SOLO ingiere los
de remitentes que cruzan con un cliente del directorio por su email (aiuda no es
un cliente de correo: newsletters y ruido se quedan en el buzón, intactos).

Cada correo entra a la MISMA bandeja que WhatsApp (``Conversation``/``Message``)
con ``channel='correo'``:

- El hilo se resuelve primero por References/In-Reply-To (el Message-ID de cada
  mensaje vive en ``Message.wa_message_id``) y, si no hay pista, por la clave
  determinística remitente+asunto (``clave_hilo``), que cabe en
  ``Conversation.remote_phone`` (String(32) único por tenant).
- Idempotente: un Message-ID ya visto no se re-ingiere; el cursor UID del buzón
  vive en ``Tenant.config['correo_estado']``.
- Los metadatos del hilo (remitente, nombre, asunto) viven en
  ``Tenant.config['correo_hilos'][conversation_id]`` — sin migración.
- La siembra (primera corrida) NO encola respuestas del agente: solo puebla la
  bandeja con lo reciente. Después, cada entrante nuevo se encola en
  ``Tenant.config['correo_pendientes']`` y el worker propone la respuesta
  (HITL: el aiudante propone, el humano aprueba — nunca contesta solo).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.connectors.correo import CorreoEntrante, clave_hilo
from aiuda_core.connectors.credentials import get_credential
from aiuda_core.identity import resolve_customer_by_email
from aiuda_core.models import Conversation, Message, Tenant

CORREO_ESTADO_KEY = "correo_estado"  # cursor IMAP: {buzon, uidvalidity, last_uid, ...}
CORREO_HILOS_KEY = "correo_hilos"  # conversation_id -> {de, nombre, asunto}
CORREO_PENDIENTES_KEY = "correo_pendientes"  # message ids que esperan propuesta del agente

# Cola de propuestas acotada: si algo se atora (IA cortada semanas), no crece sin fin.
_MAX_PENDIENTES = 100
_MAX_REFERENCES = 10


# ---------- hilos: resolución y metadatos ----------


def hilo_meta(tenant: Tenant, conversation_id: str) -> dict:
    """Metadatos del hilo de correo ({de, nombre, asunto}) o {} si no es de correo."""
    hilos = (tenant.config or {}).get(CORREO_HILOS_KEY) or {}
    entry = hilos.get(conversation_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _registrar_hilo(cfg: dict, conversation_id: str, de: str, nombre: str, asunto: str) -> None:
    """Anota (en el dict de config en preparación) el hilo: a quién es y de qué va.
    El asunto del hilo es el PRIMERO que se conoció (los Re: no lo pisan)."""
    hilos = dict(cfg.get(CORREO_HILOS_KEY) or {})
    previo = dict(hilos.get(conversation_id) or {})
    hilos[conversation_id] = {
        "de": de or previo.get("de", ""),
        "nombre": nombre or previo.get("nombre", ""),
        "asunto": previo.get("asunto") or (asunto or "").strip(),
    }
    cfg[CORREO_HILOS_KEY] = hilos


def _hilo_por_referencias(
    session: Session, tenant_id: str, refs: tuple[str, ...]
) -> Conversation | None:
    """La conversación que ya contiene alguno de los Message-ID referenciados."""
    limpios = [r[:128] for r in refs if r]
    if not limpios:
        return None
    return session.scalar(
        select(Conversation)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "correo",
            Message.wa_message_id.in_(limpios),
        )
        .limit(1)
    )


def hilo_para_envio(
    session: Session, tenant: Tenant, correo_cliente: str, nombre: str, asunto: str
) -> Conversation:
    """El hilo de correo para un ENVÍO nuestro (recordatorio por correo): existente
    por clave remitente+asunto o creado. Registra sus metadatos en tenant.config —
    así la respuesta futura del cliente cae en la misma conversación."""
    clave = clave_hilo(correo_cliente, asunto)
    conv = session.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.remote_phone == clave
        )
    )
    if conv is None:
        conv = Conversation(tenant_id=tenant.id, remote_phone=clave, channel="correo")
        session.add(conv)
        session.flush()
    cfg = dict(tenant.config or {})
    _registrar_hilo(cfg, conv.id, correo_cliente, nombre, asunto)
    tenant.config = cfg
    session.add(tenant)
    return conv


def registrar_saliente(
    session: Session,
    tenant: Tenant,
    conversation: Conversation,
    texto: str,
    message_id: str,
    author: str = "agent",
    delivery: str = "sent",
) -> Message:
    """Deja el correo ENVIADO en el hilo (con su Message-ID: la respuesta del cliente
    enhebra por References contra él)."""
    msg = Message(
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        direction="out",
        author=author,
        body=texto,
        wa_message_id=(message_id or "")[:128] or None,
        delivery=delivery,
    )
    session.add(msg)
    session.flush()
    return msg


def reply_headers(session: Session, tenant: Tenant, conversation: Conversation) -> dict:
    """Lo que un envío de RESPUESTA en este hilo necesita: destinatario, asunto
    'Re: …' y los headers de threading (In-Reply-To = último entrante; References =
    la cadena del hilo, acotada)."""
    from aiuda_core.connectors.correo import asunto_re

    meta = hilo_meta(tenant, conversation.id)
    mids = session.scalars(
        select(Message.wa_message_id)
        .where(
            Message.tenant_id == tenant.id,
            Message.conversation_id == conversation.id,
            Message.wa_message_id.isnot(None),
        )
        .order_by(Message.created_at)
    ).all()
    ultimo_entrante = session.scalar(
        select(Message.wa_message_id)
        .where(
            Message.tenant_id == tenant.id,
            Message.conversation_id == conversation.id,
            Message.direction == "in",
            Message.wa_message_id.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return {
        "para": meta.get("de", ""),
        "asunto": asunto_re(meta.get("asunto", "")),
        "in_reply_to": ultimo_entrante or (mids[-1] if mids else ""),
        "references": [m for m in mids if m][-_MAX_REFERENCES:],
    }


# ---------- la corrida de sync ----------


def _hilo_para_entrante(session: Session, tenant: Tenant, correo: CorreoEntrante) -> Conversation:
    refs = tuple(correo.references)
    if correo.in_reply_to:
        refs = (*refs, correo.in_reply_to)
    conv = _hilo_por_referencias(session, tenant.id, refs)
    if conv is not None:
        return conv
    clave = clave_hilo(correo.from_email, correo.subject)
    conv = session.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.remote_phone == clave
        )
    )
    if conv is None:
        conv = Conversation(tenant_id=tenant.id, remote_phone=clave, channel="correo")
        session.add(conv)
        session.flush()
    return conv


def _ya_ingerido(session: Session, tenant_id: str, message_id: str) -> bool:
    if not message_id:
        return False
    return (
        session.scalar(
            select(Message.id).where(
                Message.tenant_id == tenant_id,
                Message.wa_message_id == message_id[:128],
            )
        )
        is not None
    )


def sync_correo(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    fuente_prefs: dict[str, str] | None = None,  # mono-fuente: se acepta e ignora
    client=None,
):
    """Baja el buzón conectado y vuelve los correos de CLIENTES hilos en la bandeja.

    No-op honesto sin credenciales de lectura (IMAP) o con auth OAuth (aún no
    cableado). Un buzón caído no tumba la corrida: el error queda visible en
    ``correo_estado.ultimo_error`` y se reintenta la próxima."""
    from aiuda_core.engine.sync import SyncReport

    report = SyncReport()
    creds = get_credential(session, tenant.id, "email") or {}
    lectura_lista = creds.get("email") and creds.get("password") and creds.get("imap_host")
    if not lectura_lista or (creds.get("auth_method") or "password") != "password":
        return report
    if client is None:
        from aiuda_core.connectors.correo import CorreoClient

        client = CorreoClient(
            email=creds.get("email", ""),
            password=creds.get("password", ""),
            imap_host=creds.get("imap_host", ""),
            imap_port=creds.get("imap_port") or 993,
            smtp_host=creds.get("smtp_host", ""),
            smtp_port=creds.get("smtp_port") or 587,
        )

    cfg = dict(tenant.config or {})
    estado = dict(cfg.get(CORREO_ESTADO_KEY) or {})
    estado.pop("ultimo_error", None)
    try:
        entrantes, nuevo_estado, sembrando = client.fetch_nuevos(estado, hoy=today)
    except Exception as exc:  # noqa: BLE001 — buzón caído: visible, sin tumbar la corrida
        cfg[CORREO_ESTADO_KEY] = {**estado, "ultimo_error": str(exc)}
        tenant.config = cfg
        session.add(tenant)
        session.flush()
        return report

    report.fuentes.append("email")
    cuenta_propia = (creds.get("email") or "").strip().lower()
    pendientes = list(cfg.get(CORREO_PENDIENTES_KEY) or [])
    for correo in entrantes:
        if not correo.from_email or correo.from_email == cuenta_propia:
            continue  # sin remitente o es nuestra propia cuenta (enviados/rebotes)
        if resolve_customer_by_email(session, tenant.id, correo.from_email) is None:
            continue  # solo hilos con clientes; lo demás se queda en el buzón
        if _ya_ingerido(session, tenant.id, correo.message_id):
            continue  # idempotencia por Message-ID (re-corridas no duplican)
        conv = _hilo_para_entrante(session, tenant, correo)
        msg = Message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            direction="in",
            body=correo.text or "(correo sin texto)",
            wa_message_id=(correo.message_id or "")[:128] or None,
        )
        session.add(msg)
        session.flush()
        _registrar_hilo(cfg, conv.id, correo.from_email, correo.from_name, correo.subject)
        report.correos_importados += 1
        if not sembrando:
            pendientes.append(msg.id)  # el worker propone la respuesta (HITL)

    cfg[CORREO_ESTADO_KEY] = {
        **nuevo_estado,
        "ultima_corrida": datetime.now(timezone.utc).isoformat(),
    }
    cfg[CORREO_PENDIENTES_KEY] = pendientes[-_MAX_PENDIENTES:]
    tenant.config = cfg
    session.add(tenant)
    session.flush()
    return report
