"""Costo y tope de gasto de IA, versión local.

Una sola tabla de precios alimenta el uso del mes (/v1/usage) y el tope de
tokens del mes (``config["ia_tope_tokens_mes"]``). No hay planes ni
suscripciones: aiuda no cobra inferencia, el dueño paga la suya.

Por eso mismo existe un tope DE FÁBRICA. Si el default fuera "sin tope", el día
que una corrida se atore (o el mes que llegue el triple de trabajo) el dueño se
entera por su recibo con Anthropic/OpenAI, no por aiuda. Quien quiera otro
número lo pone; quien de verdad no quiera tope escribe un 0 explícito.
limite=None → sin tope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from aiuda_core.models import UsageEvent

MX_TZ = ZoneInfo("America/Mexico_City")

# Tope de tokens del mes cuando el dueño no puso el suyo. No es un cobro ni una
# cuota nuestra: es el freno que evita la factura sorpresa con SU proveedor.
# 5 millones de tokens dan de sobra para la cobranza de una PyME (una corrida
# horaria redactando gasta miles, no millones), así que el negocio normal nunca
# lo toca; una corrida atorada sí, y ahí es donde sirve.
DEFAULT_TOPE_TOKENS_MES = 5_000_000

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


def _limite_de(config: dict | None) -> tuple[int | None, str | None]:
    """(limite, fuente) a partir de la config del negocio.

    - número > 0  → el tope que el dueño escribió ('propio')
    - 0 (o < 0)   → sin tope, dicho a propósito (None)
    - nada        → el tope de fábrica ('default')

    El ``bool`` se descarta a mano: en Python ``True`` es un entero y un
    ``ia_tope_tokens_mes: true`` mal escrito dejaría el tope en 1 token."""
    propio = (config or {}).get("ia_tope_tokens_mes")
    if isinstance(propio, bool) or not isinstance(propio, (int, float)):
        return DEFAULT_TOPE_TOKENS_MES, "default"
    if propio > 0:
        return int(propio), "propio"
    return None, None


def ia_budget(db, tenant) -> dict:
    """Veredicto del presupuesto de IA, para el corte y para la UI.

    {usados, limite, fuente ('propio'|'default'|None), agotado, bloqueada, estado}.
    ``bloqueada`` se conserva en el contrato por compatibilidad, pero en local
    siempre es False: no hay suscripción que suspender."""
    usados = tokens_this_month(db, tenant.id)
    limite, fuente = _limite_de(tenant.config)
    return {
        "usados": usados,
        "limite": limite,
        "fuente": fuente,
        "agotado": limite is not None and usados >= limite,
        "bloqueada": False,
        "estado": "activa",
    }


def ia_budget_message(verdict: dict) -> str:
    """El motivo del corte, en palabras del dueño (para BudgetExceeded y la UI).

    Distingue el tope que él puso del de fábrica: si nunca configuró nada, decirle
    'tu tope personal' lo dejaría buscando un ajuste que no existe."""
    limite = verdict.get("limite") or 0
    usados = verdict.get("usados") or 0
    if verdict.get("fuente") == "default":
        cual = (
            f"Se alcanzó el tope de fábrica de IA de este mes ({usados:,} de {limite:,} tokens). "
            "Es el freno que trae aiuda para que un mes raro no te sorprenda en el recibo de tu "
            "proveedor de IA; puedes subirlo o quitarlo con ia_tope_tokens_mes."
        )
    else:
        cual = f"Se alcanzó tu tope personal de IA de este mes ({usados:,} de {limite:,} tokens)."
    return (
        f"{cual} Ninguna corrida volverá a llamar a la IA hasta el próximo mes o hasta "
        "subir el tope."
    )
