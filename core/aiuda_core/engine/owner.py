"""Comandos del dueño por WhatsApp: la bandeja de aprobaciones en tu bolsillo.

Cuando el mensaje entrante viene del número del dueño, no es un deudor — son
órdenes. Comandos deterministas (sin LLM: aprobar dinero no se deja a
interpretación); cualquier otra cosa pasa al agente, que le contesta con los
datos reales de su negocio.

  pendientes → lista numerada de lo que espera aprobación
  aprobar 2 / aprobar todo
  rechazar 1
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.engine import approval
from aiuda_core.models import Customer, Invoice, Reminder, Tenant


@dataclass
class OwnerReply:
    text: str
    send_reminders: list[tuple[Reminder, str]] # (reminder aprobado, teléfono destino)


def _pending(session: Session, tenant: Tenant) -> list[Reminder]:
    return list(
        session.scalars(
            select(Reminder)
            .where(Reminder.tenant_id == tenant.id, Reminder.status == "pending_approval")
            .order_by(Reminder.created_at)
        )
    )


def _describe(session: Session, reminder: Reminder, index: int) -> str:
    if reminder.invoice_id:
        invoice = session.get(Invoice, reminder.invoice_id)
        customer = session.get(Customer, invoice.customer_id)
        return (
            f"{index}. {customer.name} · {invoice.folio} · "
            f"${float(invoice.amount):,.2f} ({reminder.agent})"
        )
    return f"{index}. {reminder.title or 'Sin título'} ({reminder.agent})"


def _recipient_phone(session: Session, reminder: Reminder) -> str | None:
    if reminder.invoice_id:
        invoice = session.get(Invoice, reminder.invoice_id)
        return session.get(Customer, invoice.customer_id).phone
    return reminder.recipient_phone


def handle_owner_command(session: Session, tenant: Tenant, body: str) -> OwnerReply | None:
    """None si no es un comando: el agente atiende el mensaje normalmente."""
    text = body.strip().lower()

    if text in ("pendientes", "bandeja", "aprobaciones"):
        pending = _pending(session, tenant)
        if not pending:
            return OwnerReply("Bandeja limpia. Nada espera tu aprobación.", [])
        lines = [f"{len(pending)} por aprobar:"]
        lines += [_describe(session, r, i + 1) for i, r in enumerate(pending)]
        lines.append('\nResponde "aprobar 2", "aprobar todo" o "rechazar 1".')
        return OwnerReply("\n".join(lines), [])

    match = re.fullmatch(r"(aprobar|rechazar)\s+(todo|\d+)", text)
    if match is None:
        return None

    action, target = match.groups()
    pending = _pending(session, tenant)
    if not pending:
        return OwnerReply("No hay nada pendiente de aprobar ahora mismo.", [])

    if target == "todo":
        selected = pending if action == "aprobar" else []
        if action == "rechazar":
            return OwnerReply(
                'Por seguridad "rechazar todo" no existe: rechaza uno por uno ("rechazar 1").',
                [],
            )
    else:
        index = int(target)
        if index < 1 or index > len(pending):
            return OwnerReply(
                f'No tengo el número {index}. Responde "pendientes" para ver la lista.', []
            )
        selected = [pending[index - 1]]

    to_send: list[tuple[Reminder, str]] = []
    descriptions = []
    for reminder in selected:
        descriptions.append(_describe(session, reminder, len(descriptions) + 1))
        if action == "aprobar":
            approval.advance(reminder, "approved")
            phone = _recipient_phone(session, reminder)
            if phone:
                to_send.append((reminder, phone))
        else:
            approval.advance(reminder, "rejected")
    session.flush()

    verb = "Aprobado y enviando" if action == "aprobar" else "Rechazado (queda en el historial)"
    return OwnerReply(f"{verb}:\n" + "\n".join(descriptions), to_send)
