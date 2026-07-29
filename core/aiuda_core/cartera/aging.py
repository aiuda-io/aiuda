"""Aging de cartera: clasificación determinística de facturas por días contra vencimiento.

El tono y la urgencia los decide código, no el LLM — ver tone.py.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Bucket(StrEnum):
    POR_VENCER = "por_vencer"  # vence en >3 días
    VENCE_PRONTO = "vence_pronto"  # vence en 0–3 días
    VENCIDA_RECIENTE = "vencida_reciente"  # vencida 1–15 días
    VENCIDA = "vencida"  # vencida 16–45 días
    CRITICA = "critica"  # vencida >45 días


def classify(due_date: date, today: date) -> Bucket:
    days_overdue = (today - due_date).days
    if days_overdue <= -4:
        return Bucket.POR_VENCER
    if days_overdue <= 0:
        return Bucket.VENCE_PRONTO
    if days_overdue <= 15:
        return Bucket.VENCIDA_RECIENTE
    if days_overdue <= 45:
        return Bucket.VENCIDA
    return Bucket.CRITICA


@dataclass
class AgingLine:
    bucket: Bucket
    count: int
    total: float


def aging_summary(invoices, today: date) -> dict[Bucket, AgingLine]:
    """Resume facturas abiertas por bucket. `invoices` requiere .due_date y .amount."""
    summary: dict[Bucket, AgingLine] = {
        b: AgingLine(bucket=b, count=0, total=0.0) for b in Bucket
    }
    for inv in invoices:
        bucket = classify(inv.due_date, today)
        line = summary[bucket]
        line.count += 1
        line.total += float(inv.amount)
    return summary
