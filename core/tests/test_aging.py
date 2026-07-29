from datetime import date

from aiuda_core.cartera.aging import Bucket, aging_summary, classify

TODAY = date(2026, 6, 9)


def test_por_vencer():
    assert classify(date(2026, 6, 20), TODAY) == Bucket.POR_VENCER
    assert classify(date(2026, 6, 13), TODAY) == Bucket.POR_VENCER  # vence en 4 días


def test_vence_pronto_limites():
    assert classify(date(2026, 6, 12), TODAY) == Bucket.VENCE_PRONTO  # en 3 días
    assert classify(date(2026, 6, 9), TODAY) == Bucket.VENCE_PRONTO  # hoy


def test_vencida_reciente_limites():
    assert classify(date(2026, 6, 8), TODAY) == Bucket.VENCIDA_RECIENTE  # 1 día
    assert classify(date(2026, 5, 25), TODAY) == Bucket.VENCIDA_RECIENTE  # 15 días


def test_vencida_limites():
    assert classify(date(2026, 5, 24), TODAY) == Bucket.VENCIDA  # 16 días
    assert classify(date(2026, 4, 25), TODAY) == Bucket.VENCIDA  # 45 días


def test_critica():
    assert classify(date(2026, 4, 24), TODAY) == Bucket.CRITICA  # 46 días


def test_aging_summary_agrupa_montos():
    class Inv:
        def __init__(self, due, amount):
            self.due_date = due
            self.amount = amount

    invoices = [
        Inv(date(2026, 6, 20), 100.0),
        Inv(date(2026, 6, 8), 200.0),
        Inv(date(2026, 6, 7), 300.0),
        Inv(date(2026, 1, 1), 999.0),
    ]
    summary = aging_summary(invoices, TODAY)
    assert summary[Bucket.POR_VENCER].count == 1
    assert summary[Bucket.VENCIDA_RECIENTE].count == 2
    assert summary[Bucket.VENCIDA_RECIENTE].total == 500.0
    assert summary[Bucket.CRITICA].total == 999.0
    assert summary[Bucket.VENCIDA].count == 0
