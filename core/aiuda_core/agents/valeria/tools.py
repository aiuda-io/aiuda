"""Tools de Valeria (Recepción): solo lectura sobre la agenda.

Valeria no inventa citas ni horarios: los consulta. Aterriza sus respuestas en las
citas reales del negocio (Appointment) con el tenant obligatorio en cada query.
"""

from datetime import datetime, timedelta

from sqlalchemy import or_, select

from aiuda_core.agents.base import ToolExecutor
from aiuda_core.models import Appointment

VALERIA_TOOLS: list[dict] = [
    {
        "name": "consultar_agenda",
        "description": (
            "Consulta las citas próximas de la agenda. Úsala SIEMPRE antes de hablar de "
            "horarios o disponibilidad — nunca inventes una cita. Por defecto trae los "
            "próximos 7 días; puedes pedir más días."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "description": "Cuántos días hacia adelante mirar (default 7)",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "buscar_cita",
        "description": (
            "Busca citas por asunto o por nombre del cliente. Úsala cuando pregunten por "
            "la cita de alguien en específico."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "busqueda": {"type": "string", "description": "Asunto o nombre del cliente"}
            },
            "required": ["busqueda"],
            "additionalProperties": False,
        },
    },
]


def _fmt(a: Appointment) -> str:
    cuando = a.starts_at.strftime("%d/%m %H:%M") if a.starts_at else "sin fecha"
    quien = f" | {a.customer_name}" if a.customer_name else ""
    notas = f" | {a.notes}" if a.notes else ""
    return f"{cuando} | {a.title}{quien}{notas}"


class ValeriaToolExecutor(ToolExecutor):
    """Ejecuta los tools de recepción. Solo lectura, tenant obligatorio."""

    _LIMIT = 30

    def _consultar_agenda(self, dias: int = 7) -> str:
        desde = datetime.combine(self.today, datetime.min.time())
        hasta = datetime.combine(self.today + timedelta(days=max(1, dias)), datetime.max.time())
        rows = self.session.scalars(
            select(Appointment)
            .where(
                Appointment.tenant_id == self.tenant.id,
                Appointment.starts_at >= desde,
                Appointment.starts_at <= hasta,
            )
            .order_by(Appointment.starts_at)
            .limit(self._LIMIT)
        ).all()
        if not rows:
            return f"Sin citas en los próximos {dias} días."
        return "\n".join(_fmt(a) for a in rows)

    def _buscar_cita(self, busqueda: str) -> str:
        like = f"%{busqueda.strip()}%"
        rows = self.session.scalars(
            select(Appointment)
            .where(
                Appointment.tenant_id == self.tenant.id,
                or_(Appointment.title.ilike(like), Appointment.customer_name.ilike(like)),
            )
            .order_by(Appointment.starts_at.is_(None), Appointment.starts_at)
            .limit(self._LIMIT)
        ).all()
        if not rows:
            return "Sin citas con ese criterio."
        return "\n".join(_fmt(a) for a in rows)
