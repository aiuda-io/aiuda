"""Tools de Diego (Conciliación): solo lectura sobre pagos detectados y sus matches.

Qué PROPONE Diego (proponer, nunca ejecutar): a qué factura abierta corresponde cada
depósito detectado, con la razón del match (`engine/reconcile.propose_matches`). La
conciliación real (marcar la factura pagada) la CONFIRMA el humano en /conciliacion —
Diego jamás cierra una factura solo, igual que un dicho del cliente no es un pago.

En el chat, esta herramienta únicamente CONSULTA la bandeja: pagos pendientes y su
candidata propuesta, con el tenant obligatorio en cada query.
"""

from sqlalchemy import select

from aiuda_core.agents.base import ToolExecutor
from aiuda_core.engine.reconcile import propose_matches
from aiuda_core.models import Payment

DIEGO_TOOLS: list[dict] = [
    {
        "name": "consultar_pagos",
        "description": (
            "Consulta los pagos detectados (depósitos del banco o la pasarela) pendientes de "
            "conciliar y, para cada uno, la factura a la que probablemente corresponde con la "
            "razón del match. Úsala SIEMPRE antes de afirmar si un depósito ya se aplicó o qué "
            "factura cubre — nunca lo supongas. Solo consulta: conciliar (confirmar el match) "
            "lo hace el humano en Conciliación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


class DiegoToolExecutor(ToolExecutor):
    """Ejecuta los tools de conciliación con tenant_id obligatorio en toda query."""

    def _consultar_pagos(self) -> str:
        pagos = self.session.scalars(
            select(Payment)
            .where(Payment.tenant_id == self.tenant.id, Payment.status == "pendiente")
            .order_by(Payment.paid_at.desc())
            .limit(20)
        ).all()
        if not pagos:
            return "No hay pagos pendientes de conciliar."
        lines = [f"Pagos pendientes de conciliar: {len(pagos)}"]
        for p in pagos:
            quien = p.counterparty or p.reference or "sin referencia"
            lines.append(
                f"- ${float(p.amount):,.2f} {p.currency} del {p.paid_at} ({p.source}, {quien})"
            )
            cands = propose_matches(self.session, self.tenant.id, p, limit=1)
            if cands:
                c = cands[0]
                cuadra = "cuadra al centavo" if c.cuadra else "monto cercano"
                lines.append(
                    f"  Propuesta: factura {c.folio} de {c.customer} por ${c.amount:,.2f} "
                    f"({c.reason}; {cuadra}). Falta que el humano la confirme."
                )
            else:
                lines.append("  Sin factura candidata: revisarlo a mano en Conciliación.")
        return "\n".join(lines)
