"""Máquina de estados HITL de los recordatorios.

El LLM redacta; este módulo decide qué transiciones son válidas. Nada se envía
sin pasar por aquí — el agente no puede saltarse estados.
"""

from aiuda_core.models import Reminder, utcnow


class InvalidTransition(Exception):
    pass


TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_approval"},
    "pending_approval": {"approved", "rejected"},
    "approved": {"sent", "failed"},
    # Rechazar NO es un callejón sin salida: el dueño puede corregir el borrador y
    # enviarlo, o devolverlo a la bandeja. Nada se pierde (trazabilidad).
    "rejected": {"approved", "pending_approval"},
    "failed": {"approved"},  # reintento de envío requiere re-marcar approved
}


def advance(reminder: Reminder, new_status: str) -> Reminder:
    allowed = TRANSITIONS.get(reminder.status, set())
    if new_status not in allowed:
        raise InvalidTransition(
            f"Recordatorio {reminder.id}: {reminder.status} → {new_status} no permitido"
        )
    reminder.status = new_status
    if new_status == "sent":
        reminder.sent_at = utcnow()
    return reminder


def can_auto_send(tenant_config: dict, bucket: str) -> bool:
    """Auto-envío es opt-in por tenant y por bucket; nunca para crítica."""
    if bucket == "critica":
        return False
    return bucket in (tenant_config or {}).get("auto_send_buckets", [])
