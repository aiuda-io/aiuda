"""Tools de Cleo: definiciones JSON Schema + ejecutor con validaciones de código.

Las descripciones dicen CUÁNDO usar cada tool, no sólo qué hace — eso eleva
la tasa de uso correcto del modelo.
"""

from datetime import date

from sqlalchemy import select

from aiuda_core.agents.base import ToolExecutor
from aiuda_core.cartera.aging import classify
from aiuda_core.engine import approval
from aiuda_core.identity import resolve_customer_by_phone
from aiuda_core.models import Customer, Invoice, PaymentPromise, Reminder
from aiuda_core.phones import match_key

CLEO_TOOLS: list[dict] = [
    {
        "name": "consultar_cartera",
        "description": (
            "Consulta las facturas abiertas del negocio con su atraso actual. Úsala SIEMPRE "
            "antes de mencionar montos, folios o fechas — nunca los inventes. Puedes filtrar "
            "por teléfono del cliente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono_cliente": {
                    "type": "string",
                    "description": "Teléfono del cliente para filtrar (opcional)",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "registrar_promesa_pago",
        "description": (
            "Registra una promesa de pago. Úsala cuando el cliente diga que pagará en una "
            "fecha concreta (ej. 'te deposito el viernes')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folio": {"type": "string", "description": "Folio de la factura"},
                "fecha_promesa": {
                    "type": "string",
                    "description": "Fecha prometida en formato YYYY-MM-DD",
                },
                "nota": {"type": "string", "description": "Contexto breve de la promesa"},
            },
            "required": ["folio", "fecha_promesa"],
            "additionalProperties": False,
        },
    },
    {
        "name": "registrar_pago",
        "description": (
            "Registra que el CLIENTE REPORTA haber pagado una factura. Úsala cuando diga "
            "que ya pagó. OJO: esto NO marca la factura como cobrada — queda pendiente de "
            "verificación contra el banco o el registro del negocio. Un dicho no es un pago."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"folio": {"type": "string", "description": "Folio de la factura"}},
            "required": ["folio"],
            "additionalProperties": False,
        },
    },
]


# En el chat con el dueño, Mariana solo CONSULTA (las escrituras viven en el flujo
# de cobranza con aprobación). Reusa la misma definición y ejecutor.
CLEO_CHAT_TOOLS: list[dict] = [t for t in CLEO_TOOLS if t["name"] == "consultar_cartera"]


class CleoToolExecutor(ToolExecutor):
    """Ejecuta los tools de cobranza con tenant_id obligatorio en toda query."""

    def _invoice_by_folio(self, folio: str) -> Invoice:
        inv = self.session.scalar(
            select(Invoice).where(Invoice.tenant_id == self.tenant.id, Invoice.folio == folio)
        )
        if inv is None:
            raise ValueError(f"No existe la factura con folio {folio}")
        # Si el interlocutor es un deudor (caller_phone definido), la factura DEBE
        # ser suya. Cierra el vector de que un deudor registre pagos/promesas sobre
        # folios ajenos del mismo negocio citando el número en su mensaje.
        if self.caller_phone is not None:
            cust = self.session.get(Customer, inv.customer_id)
            # Cruce por match_key (últimos 10 dígitos): el teléfono guardado y el del
            # que llama vienen en formatos distintos; la igualdad exacta dejaba fuera al
            # dueño legítimo de la factura.
            if cust is None or match_key(cust.phone) != match_key(self.caller_phone):
                raise ValueError(f"No encuentro una factura {folio} asociada a este número.")
        return inv

    def _consultar_cartera(self, telefono_cliente: str | None = None) -> str:
        query = select(Invoice, Customer).join(Customer, Invoice.customer_id == Customer.id)
        query = query.where(Invoice.tenant_id == self.tenant.id, Invoice.status == "open")
        # Con un deudor, la consulta se ata SIEMPRE a su número (se ignora cualquier
        # teléfono que el modelo proponga): no puede listar la cartera completa ni la
        # de otro cliente. En el chat del dueño (caller_phone None) el filtro es libre.
        # Se resuelve el cliente por match_key y se ata por id: robusto al formato del
        # teléfono y más seguro (liga al cliente exacto, no a una cadena de teléfono).
        if self.caller_phone is not None:
            caller = resolve_customer_by_phone(self.session, self.tenant.id, self.caller_phone)
            if caller is None:
                return "Sin facturas abiertas con ese criterio."
            query = query.where(Customer.id == caller.id)
        elif telefono_cliente:
            match = resolve_customer_by_phone(self.session, self.tenant.id, telefono_cliente)
            if match is None:
                return "Sin facturas abiertas con ese criterio."
            query = query.where(Customer.id == match.id)
        rows = self.session.execute(query).all()
        if not rows:
            return "Sin facturas abiertas con ese criterio."
        lines = []
        for inv, cust in rows:
            bucket = classify(inv.due_date, self.today)
            days = (self.today - inv.due_date).days
            atraso = f"{days} días de atraso" if days > 0 else f"vence en {-days} días"
            lines.append(
                f"Folio {inv.folio} | {cust.name} ({cust.phone}) | "
                f"${float(inv.amount):,.2f} {inv.currency} | vence {inv.due_date} | "
                f"{atraso} | bucket: {bucket}"
            )
        return "\n".join(lines)

    def _registrar_promesa_pago(self, folio: str, fecha_promesa: str, nota: str = "") -> str:
        inv = self._invoice_by_folio(folio)
        promise = PaymentPromise(
            tenant_id=self.tenant.id,
            invoice_id=inv.id,
            promised_date=date.fromisoformat(fecha_promesa),
            note=nota or None,
        )
        self.session.add(promise)
        self.session.flush()
        return f"Promesa registrada: factura {folio} para el {fecha_promesa}."

    def _registrar_pago(self, folio: str) -> str:
        """Fact-check obligatorio: el reporte del cliente nunca cierra la factura solo."""
        inv = self._invoice_by_folio(folio)
        inv.payment_reported = True
        self.session.flush()
        return (
            f"Reporte de pago registrado para {folio}. La factura sigue abierta hasta que "
            "el negocio lo verifique contra el banco o su registro. Agradece al cliente y "
            "dile que se confirmará en cuanto se refleje."
        )


def send_approved_reminder(reminder: Reminder, send_fn) -> Reminder:
    """Único camino de envío real. Valida estado ANTES de tocar WhatsApp."""
    if reminder.status != "approved":
        raise approval.InvalidTransition(
            f"Sólo se envían recordatorios aprobados (estado actual: {reminder.status})"
        )
    try:
        send_fn(reminder.message)
    except Exception:
        approval.advance(reminder, "failed")
        raise
    return approval.advance(reminder, "sent")
