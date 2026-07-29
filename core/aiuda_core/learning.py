"""El loop de aprendizaje: convierte las correcciones del humano en mejora del agente.

Cada vez que el dueño aprueba un borrador tal cual, lo edita, o lo rechaza, se guarda la
señal (AgentFeedback). Las ediciones se RE-INYECTAN como ejemplos en el prompt del agente
(`recent_corrections` → `build_system_prompt`), así redacta cada vez más como el dueño.
No es telemetría: es el mecanismo por el que el producto mejora con el uso.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.models import AgentFeedback, Invoice, Reminder, Tenant

# Cuántas correcciones recientes se muestran al agente como ejemplo. Pocas y frescas:
# el prompt no es un dataset, son las últimas señales de cómo corrige HOY el dueño.
FEWSHOT_CORRECCIONES = 3


def record_feedback(
    session: Session,
    tenant: Tenant,
    reminder: Reminder,
    *,
    decision: str,
    draft_original: str,
    final_text: str | None,
) -> AgentFeedback:
    """Guarda la señal de una decisión humana sobre un borrador. `draft_original` es lo que
    el agente escribió; `final_text` lo que de verdad se envió (None si se rechazó)."""
    customer_id = None
    if reminder.invoice_id:
        inv = session.get(Invoice, reminder.invoice_id)
        customer_id = inv.customer_id if inv else None
    fb = AgentFeedback(
        tenant_id=tenant.id,
        agent=reminder.agent,
        bucket=reminder.bucket,
        tone=reminder.tone,
        reminder_id=reminder.id,
        invoice_id=reminder.invoice_id,
        customer_id=customer_id,
        draft_original=draft_original,
        final_text=final_text,
        decision=decision,
    )
    session.add(fb)
    session.flush()
    return fb


def recent_corrections(
    session: Session, tenant: Tenant, agent: str = "mariana", limit: int = FEWSHOT_CORRECCIONES
) -> list[tuple[str, str]]:
    """Las últimas ediciones del dueño para ese agente, como pares (borrador, enviado).
    Alimentan el few-shot del prompt: 'así corrige el dueño; imítalo'."""
    rows = session.scalars(
        select(AgentFeedback)
        .where(
            AgentFeedback.tenant_id == tenant.id,
            AgentFeedback.agent == agent,
            AgentFeedback.decision == "edited",
        )
        .order_by(AgentFeedback.created_at.desc())
        .limit(limit)
    ).all()
    return [(r.draft_original, r.final_text) for r in rows if r.final_text]


def learning_summary(session: Session, tenant: Tenant, agent: str = "mariana") -> dict:
    """Qué está aprendiendo el agente: cuánto se aprueba sin tocar, cuánto se edita/rechaza,
    y las últimas correcciones. Hace visible (y confiable) el aprendizaje."""
    rows = session.scalars(
        select(AgentFeedback)
        .where(AgentFeedback.tenant_id == tenant.id, AgentFeedback.agent == agent)
        .order_by(AgentFeedback.created_at.desc())
        .limit(200)
    ).all()
    total = len(rows)
    approved = sum(1 for r in rows if r.decision == "approved")
    edited = sum(1 for r in rows if r.decision == "edited")
    rejected = sum(1 for r in rows if r.decision == "rejected")
    revisados = approved + edited  # los que se enviaron
    tasa_sin_editar = round(approved / revisados, 2) if revisados else None
    recientes = [
        {
            "original": r.draft_original,
            "final": r.final_text,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
        if r.decision == "edited" and r.final_text
    ][:5]
    return {
        "total": total,
        "approved": approved,
        "edited": edited,
        "rejected": rejected,
        "tasaSinEditar": tasa_sin_editar,
        "recientes": recientes,
    }
