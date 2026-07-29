"""Costo y tope de gasto de IA, versión local.

Una sola tabla de precios alimenta el uso del mes (/v1/usage) y el tope
opcional que el dueño se pone a sí mismo (``config["ia_tope_tokens_mes"]``).
No hay planes ni suscripciones: el único presupuesto que existe es el que el
dueño decide. limite=None → sin tope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from aiuda_core.models import UsageEvent

MX_TZ = ZoneInfo("America/Mexico_City")

# --------------------------------------------------------------------------- #
# Precio de la IA: USD por millón de tokens (entrada, salida). Modelo fuera de #
# la tabla = costo 0 (honesto: no inventamos precio; los tokens sí se cuentan).#
# --------------------------------------------------------------------------- #
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    # gpt-5.x por la SUSCRIPCIÓN de ChatGPT (Codex): tarifa plana, costo marginal 0.
    "gpt-5.5": (0.0, 0.0),
    # El Claude Code / Codex que el dueño ya tiene instalado: lo paga su plan,
    # no aiuda. Los tokens se cuentan; el costo extra es 0.
    "claude-cli": (0.0, 0.0),
    "codex-cli": (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Costo estimado en USD de una llamada/agregado, según la tabla de precios."""
    in_price, out_price = MODEL_PRICES.get(model, (0.0, 0.0))
    return (input_tokens or 0) / 1e6 * in_price + (output_tokens or 0) / 1e6 * out_price


def month_start() -> datetime:
    """Arranque del mes EN HORA DE MÉXICO (aware, en UTC para comparar contra
    created_at). El dueño piensa su mes en su reloj, no en el de la máquina."""
    now = datetime.now(MX_TZ)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def tokens_this_month(db, tenant_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0)).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= month_start(),
        )
    )
    return int(total or 0)


def ia_month_cost_usd(db, tenant_id: str) -> float:
    """Costo estimado (USD) del consumo de IA del mes, por la tabla de precios."""
    rows = db.execute(
        select(
            UsageEvent.model,
            func.sum(UsageEvent.input_tokens),
            func.sum(UsageEvent.output_tokens),
        )
        .where(UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= month_start())
        .group_by(UsageEvent.model)
    ).all()
    return sum(cost_usd(model, int(inp or 0), int(out or 0)) for model, inp, out in rows)


def ia_budget(db, tenant) -> dict:
    """Veredicto del presupuesto de IA, para el corte y para la UI.

    {usados, limite, fuente ('propio'|None), agotado, bloqueada, estado}.
    ``bloqueada`` se conserva en el contrato por compatibilidad, pero en local
    siempre es False: no hay suscripción que suspender."""
    usados = tokens_this_month(db, tenant.id)
    propio = (tenant.config or {}).get("ia_tope_tokens_mes")
    limite = int(propio) if isinstance(propio, (int, float)) and propio > 0 else None
    return {
        "usados": usados,
        "limite": limite,
        "fuente": "propio" if limite is not None else None,
        "agotado": limite is not None and usados >= limite,
        "bloqueada": False,
        "estado": "activa",
    }


def ia_budget_message(verdict: dict) -> str:
    """El motivo del corte, en palabras del dueño (para BudgetExceeded y la UI)."""
    limite = verdict.get("limite") or 0
    usados = verdict.get("usados") or 0
    return (
        f"Se alcanzó tu tope personal de IA de este mes ({usados:,} de {limite:,} tokens). "
        "Ninguna corrida volverá a llamar a la IA hasta el próximo mes o hasta subir el tope."
    )
