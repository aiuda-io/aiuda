"""Conciliación (Diego): dado un pago que llegó, PROPONE a qué factura(s) abiertas
corresponde. Diego nunca cierra una factura solo — propone y el humano confirma.

El match no es solo por monto: un mismo monto puede ser de varias facturas, así que
se rankean candidatas por señales (monto exacto o dentro de tolerancia, total del
CFDI, nombre del cliente en el depósito, folio en la referencia, fecha cercana al
vencimiento) y se devuelven con la razón, para que el humano decida.

Reglas duras:
- El score es EXPLICABLE: cada punto viene de una señal con nombre; `reason` las lista.
- AMBIGUO (dos o más candidatas parejas) = sin propuesta única; se presentan todas
  y decide el humano. Empatar no es razón para adivinar.
- Un pago puede cubrir VARIAS facturas del mismo cliente (grupo) o ser PARCIAL
  (abono: no alcanza el saldo). Ambos se proponen con su etiqueta, nunca se aplican solos.
- El match es contra el SALDO pendiente (monto menos abonos ya conciliados), no
  contra el total original: una factura abonada se termina de cobrar con lo que falta.
"""

import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.models import Customer, Invoice, Payment

# Dos candidatas a menos de esta distancia de puntos son "parejas" → ambiguo.
MARGEN_AMBIGUO = 15
# Techos del generador de grupos: la conciliación real es 2-4 facturas por depósito.
_GRUPO_MAX_FACTURAS = 4
_GRUPO_MAX_RESULTADOS = 6
_GRUPO_MAX_NODOS = 500  # corta la búsqueda de combinaciones en carteras enormes


@dataclass
class Candidate:
    invoice_id: str
    folio: str
    customer: str
    amount: float  # total original de la factura
    saldo: float  # lo que FALTA por cobrar (total menos abonos conciliados)
    due_date: str  # ISO, para mostrar "vence …" en el panel de la factura
    score: int  # mayor = mejor; suma de señales con nombre
    reason: str  # las señales, legibles: el "por qué" de la propuesta
    cuadra: bool  # el pago cubre el saldo al centavo
    parcial: bool = False  # el pago NO alcanza el saldo: sería un abono


@dataclass
class GroupCandidate:
    """Varias facturas del MISMO cliente cuyos saldos suman el pago."""

    invoice_ids: list[str]
    folios: list[str]
    customer: str
    total: float  # suma de saldos del grupo
    score: int
    reason: str
    cuadra: bool


@dataclass
class Evaluation:
    """Resultado completo para un pago: candidatas, grupos y el veredicto de ambigüedad."""

    candidates: list[Candidate] = field(default_factory=list)
    groups: list[GroupCandidate] = field(default_factory=list)
    ambiguous: bool = False
    note: str = ""

    @property
    def proposal_kind(self) -> str | None:
        """Qué se propone como mejor opción: 'factura', 'grupo' o None (ambiguo/sin nada)."""
        if self.ambiguous:
            return None
        best_single = self.candidates[0].score if self.candidates else -1
        best_group = self.groups[0].score if self.groups else -1
        if best_single < 0 and best_group < 0:
            return None
        return "grupo" if best_group > best_single else "factura"


def _norm(s: str | None) -> str:
    """Minúsculas y SIN acentos: el banco reporta 'PAPELERIA', el maestro tiene
    'Papelería'. Para que casen, ambos se comparan sin acentos."""
    s = (s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def abonos_de(invoice: Invoice) -> list[dict]:
    """Abonos ya conciliados de la factura (viven en meta, sin migración)."""
    return list((invoice.meta or {}).get("abonos") or [])


def saldo_pendiente(invoice: Invoice) -> float:
    """Lo que falta por cobrar: total menos abonos conciliados. Nunca negativo."""
    aplicado = sum(float(a.get("aplicado", 0)) for a in abonos_de(invoice))
    return max(0.0, round(float(invoice.amount) - aplicado, 2))


def tolerancia(config: dict | None) -> tuple[float, float]:
    """(pct, abs) de tolerancia de monto desde Tenant.config['conciliacion'].

    Default: ±1% con piso de $1 — cubre redondeos y comisiones chicas sin
    inventar matches. El dueño la ajusta desde la consola."""
    cfg = (config or {}).get("conciliacion") or {}
    try:
        pct = max(0.0, float(cfg.get("tolerancia_pct", 1.0)))
        abs_ = max(0.0, float(cfg.get("tolerancia_abs", 1.0)))
    except (TypeError, ValueError):
        pct, abs_ = 1.0, 1.0
    return pct, abs_


def tol_monto(monto: float, tol_pct: float, tol_abs: float) -> float:
    """Tolerancia efectiva en pesos para un monto dado."""
    return max(tol_abs, monto * tol_pct / 100.0)


def _senales_texto(
    payment: Payment, invoice: Invoice, customer: Customer
) -> tuple[int, list[str]]:
    """Señales que NO dependen del monto: nombre en el depósito, folio en la
    referencia, fecha cercana al vencimiento. Devuelve (puntos, razones)."""
    score = 0
    reasons: list[str] = []
    counterparty = _norm(payment.counterparty)
    ref = _norm(payment.reference)
    if counterparty and _norm(customer.name) and _norm(customer.name) in counterparty:
        score += 30
        reasons.append("nombre del cliente en el depósito")
    if ref and _norm(invoice.folio) and _norm(invoice.folio) in ref:
        score += 50
        reasons.append("folio en la referencia")
    dias = abs((payment.paid_at - invoice.due_date).days)
    if dias <= 7:
        score += 15
        reasons.append("pagado cerca del vencimiento")
    elif dias <= 30:
        score += 5
        reasons.append("pagado en el mes del vencimiento")
    return score, reasons


def propose_matches(
    session: Session,
    tenant_id: str,
    payment: Payment,
    limit: int = 3,
    tol_pct: float = 1.0,
    tol_abs: float = 1.0,
) -> list[Candidate]:
    """Candidatas individuales para un pago, mejor primero. Vacío si nada se acerca.

    Incluye candidatas PARCIALES (el pago no alcanza el saldo) solo cuando hay una
    señal de cliente o folio que las respalde — un monto chico contra una factura
    grande, sin más, es ruido, no candidata."""
    rows = session.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.tenant_id == tenant_id, Invoice.status == "open")
    ).all()
    pay_amount = float(payment.amount)

    candidates: list[Candidate] = []
    for inv, cust in rows:
        saldo = saldo_pendiente(inv)
        if saldo <= 0:
            continue  # abierta pero ya cubierta por abonos: no debería, pero no propongas
        diff = abs(saldo - pay_amount)
        tol = tol_monto(saldo, tol_pct, tol_abs)
        cuadra = diff < 0.01
        parcial = False
        score = 0
        reasons: list[str] = []
        senales, senales_reasons = _senales_texto(payment, inv, cust)
        if cuadra:
            score += 100
            reasons.append("monto exacto")
        elif diff <= tol:
            score += 40
            reasons.append(f"monto dentro de la tolerancia (±${tol:,.2f})")
        elif pay_amount < saldo - tol:
            # Posible abono: solo si el cliente o el folio lo respaldan.
            if not any(
                r.startswith(("nombre del cliente", "folio en la referencia"))
                for r in senales_reasons
            ):
                continue
            parcial = True
            score += 25
            reasons.append(f"posible pago parcial: dejaría saldo de ${saldo - pay_amount:,.2f}")
        else:
            continue  # el pago EXCEDE el saldo más la tolerancia: no es esta factura sola
        # El total del CFDI confirma el monto fiscal real.
        cfdi_total = (inv.cfdi or {}).get("total")
        if cfdi_total is not None and abs(float(cfdi_total) - pay_amount) < 0.01:
            score += 20
            reasons.append("cuadra con el CFDI")
        score += senales
        reasons.extend(senales_reasons)
        candidates.append(
            Candidate(
                invoice_id=inv.id,
                folio=inv.folio,
                customer=cust.name,
                amount=float(inv.amount),
                saldo=saldo,
                due_date=inv.due_date.isoformat(),
                score=score,
                reason=", ".join(reasons),
                cuadra=cuadra,
                parcial=parcial,
            )
        )

    # Orden estable: score primero; a igual score, la más antigua por vencer.
    candidates.sort(key=lambda c: (-c.score, c.due_date))
    return candidates[:limit]


def _combos(
    saldos: list[tuple[str, float]], objetivo: float, tol: float
) -> list[list[int]]:
    """Índices de combinaciones (2..N facturas) cuyos saldos suman el objetivo ±tol.

    Búsqueda en profundidad con poda por suma; acotada en nodos y resultados para
    que una cartera enorme no cuelgue la bandeja."""
    resultados: list[list[int]] = []
    nodos = 0

    def dfs(inicio: int, suma: float, elegidos: list[int]) -> None:
        nonlocal nodos
        if nodos >= _GRUPO_MAX_NODOS or len(resultados) >= _GRUPO_MAX_RESULTADOS:
            return
        nodos += 1
        if len(elegidos) >= 2 and abs(suma - objetivo) <= tol:
            resultados.append(list(elegidos))
            return
        if len(elegidos) >= _GRUPO_MAX_FACTURAS or suma > objetivo + tol:
            return
        for i in range(inicio, len(saldos)):
            elegidos.append(i)
            dfs(i + 1, suma + saldos[i][1], elegidos)
            elegidos.pop()

    dfs(0, 0.0, [])
    return resultados


def propose_groups(
    session: Session,
    tenant_id: str,
    payment: Payment,
    tol_pct: float = 1.0,
    tol_abs: float = 1.0,
) -> list[GroupCandidate]:
    """Grupos de facturas del MISMO cliente cuyos saldos suman el pago.

    El caso real: un cliente transfiere una vez y liquida 2-3 facturas juntas.
    No se combinan facturas de clientes distintos — eso ya no es un match, es
    contabilidad creativa."""
    pay_amount = float(payment.amount)
    tol = tol_monto(pay_amount, tol_pct, tol_abs)
    rows = session.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.tenant_id == tenant_id, Invoice.status == "open")
        .order_by(Invoice.due_date)
    ).all()

    por_cliente: dict[str, list[tuple[Invoice, Customer]]] = {}
    for inv, cust in rows:
        por_cliente.setdefault(cust.id, []).append((inv, cust))

    counterparty = _norm(payment.counterparty)
    ref = _norm(payment.reference)
    groups: list[GroupCandidate] = []
    for pares in por_cliente.values():
        if len(pares) < 2:
            continue
        # (factura, saldo) con saldo vivo, en el mismo orden (por vencer) que la query.
        con_saldo = [(inv, saldo_pendiente(inv)) for inv, _ in pares]
        con_saldo = [(inv, s) for inv, s in con_saldo if s > 0]
        if len(con_saldo) < 2:
            continue
        for combo in _combos([(inv.id, s) for inv, s in con_saldo], pay_amount, tol):
            invs = [con_saldo[i][0] for i in combo]
            cust = pares[0][1]
            total = round(sum(con_saldo[i][1] for i in combo), 2)
            cuadra = abs(total - pay_amount) < 0.01
            score = 90 if cuadra else 60
            reasons = [
                f"{len(invs)} facturas del cliente suman "
                + ("el monto exacto" if cuadra else f"el monto dentro de la tolerancia (±${tol:,.2f})")
            ]
            if counterparty and _norm(cust.name) and _norm(cust.name) in counterparty:
                score += 30
                reasons.append("nombre del cliente en el depósito")
            if ref and any(_norm(inv.folio) and _norm(inv.folio) in ref for inv in invs):
                score += 20
                reasons.append("folio en la referencia")
            groups.append(
                GroupCandidate(
                    invoice_ids=[inv.id for inv in invs],
                    folios=[inv.folio for inv in invs],
                    customer=cust.name,
                    total=total,
                    score=score,
                    reason=", ".join(reasons),
                    cuadra=cuadra,
                )
            )
    groups.sort(key=lambda g: (-g.score, g.total))
    return groups[:_GRUPO_MAX_RESULTADOS]


def evaluate(
    session: Session,
    tenant_id: str,
    payment: Payment,
    limit: int = 5,
    tol_pct: float = 1.0,
    tol_abs: float = 1.0,
) -> Evaluation:
    """Evaluación completa de un pago: candidatas + grupos + veredicto de ambigüedad.

    Ambiguo = dos o más opciones (facturas o grupos) a menos de MARGEN_AMBIGUO
    puntos de la mejor. En ese caso NO hay propuesta única: decide el humano."""
    singles = propose_matches(session, tenant_id, payment, limit, tol_pct, tol_abs)
    groups = propose_groups(session, tenant_id, payment, tol_pct, tol_abs)
    scores = [c.score for c in singles] + [g.score for g in groups]
    if not scores:
        return Evaluation(note="Sin factura abierta que se acerque al monto.")
    top = max(scores)
    parejas = sum(1 for s in scores if s >= top - MARGEN_AMBIGUO)
    ambiguous = parejas >= 2
    note = (
        f"{parejas} opciones quedan parejas; tu ayudante no elige solo: decides tú."
        if ambiguous
        else ""
    )
    return Evaluation(candidates=singles, groups=groups, ambiguous=ambiguous, note=note)
