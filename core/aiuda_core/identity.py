"""Resolución de identidad por teléfono: cruza clientes y conversaciones aunque el
teléfono venga en formatos distintos (Excel crudo, '+52…' de Shopify, '521…' del webhook).

La clave del cruce es `match_key` (últimos 10 dígitos, el número local mexicano), estable
entre formatos. Los teléfonos guardados NO están normalizados, por eso cruzarlos por
igualdad exacta fallaba en toda la app y el hilo de WhatsApp salía vacío o duplicado. Aquí
se comparan por match_key, la única forma confiable sin re-guardar toda la base.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.models.entities import Conversation, Customer
from aiuda_core.phones import match_key


def resolve_customer_by_phone(session: Session, tenant_id: str, phone) -> Customer | None:
    """El cliente cuyo teléfono cruza con `phone` por match_key. None si ninguno.

    Escanea los clientes con teléfono y confirma por match_key: los teléfonos guardados
    pueden traer '+', espacios o el '1' móvil, así que un pre-filtro por sufijo en SQL no es
    confiable. A escala de piloto (decenas/cientos de clientes) el escaneo es barato."""
    key = match_key(phone)
    if not key:
        return None
    candidates = session.scalars(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone.isnot(None))
    ).all()
    return next((c for c in candidates if match_key(c.phone) == key), None)


def resolve_customer_by_email(session: Session, tenant_id: str, email) -> Customer | None:
    """El cliente cuyo correo cruza con `email` (sin distinguir mayúsculas/espacios).
    None si ninguno. Es el cruce de identidad del canal de correo: el remitente de un
    correo entrante contra el directorio. Mismo trato que el teléfono: escaneo barato
    a escala de piloto y comparación normalizada (los correos guardados vienen como
    los capturó el dueño o la fuente)."""
    key = str(email or "").strip().lower()
    if not key or "@" not in key:
        return None
    candidates = session.scalars(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.email.isnot(None))
    ).all()
    return next((c for c in candidates if (c.email or "").strip().lower() == key), None)


def find_conversation_by_phone(session: Session, tenant_id: str, phone) -> Conversation | None:
    """La conversación cuyo remote_phone cruza con `phone` por match_key. None si ninguna.

    remote_phone se guarda normalizado (solo dígitos), así que se pre-filtra por sufijo en SQL
    y se confirma por match_key para descartar coincidencias parciales."""
    key = match_key(phone)
    if not key:
        return None
    candidates = session.scalars(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id, Conversation.remote_phone.like(f"%{key}")
        )
    ).all()
    return next((cv for cv in candidates if match_key(cv.remote_phone) == key), None)
