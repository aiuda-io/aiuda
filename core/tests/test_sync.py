from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from aiuda_core.connectors.belvo import BankTransaction
from aiuda_core.engine.sync import detectar_pagos, sync_pedidos
from aiuda_core.models import Invoice

TODAY = date(2026, 6, 9)


@dataclass
class FakeOrder:
    name: str
    total: float
    currency: str
    customer_name: str
    customer_phone: str
    created_at: str = ""


class FakeShop:
    def __init__(self, orders):
        self._orders = orders

    def list_unpaid_orders(self):
        return self._orders


class FakeBelvo:
    def __init__(self, inflows):
        self._inflows = inflows

    def list_inflows(self, link, date_from, date_to):
        return self._inflows

    def match_payment(self, inflows, amount):
        for t in inflows:
            if abs(t.amount - amount) <= 1.0:
                return t
        return None


def test_sync_pedidos_importa_idempotente(session, tenant):
    shop = FakeShop(
        [
            FakeOrder("#1001", 850.0, "MXN", "Cliente Online", "5215511122233"),
            FakeOrder("#1002", 1200.0, "MXN", "Otro Cliente", ""),
        ]
    )
    report = sync_pedidos(session, tenant, today=TODAY, shopify_client=shop)
    assert report.pedidos_importados == 2
    assert report.fuentes == ["shopify"]

    # re-sync no duplica
    again = sync_pedidos(session, tenant, today=TODAY, shopify_client=shop)
    assert again.pedidos_importados == 0

    inv = session.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == "#1001")
    )
    assert inv.source == "shopify"
    assert inv.verified == "verificada"  # viene del registro de la tienda


def test_detectar_pagos_confirma_con_banco(session, tenant, customer, invoice):
    # invoice del fixture: $12,500.50 abierta
    belvo = FakeBelvo(
        [
            BankTransaction(
                id="t1",
                amount=12500.50,
                description="SPEI CLIENTE DEMO",
                value_date="2026-06-08",
                type="INFLOW",
                account_id="a1",
            )
        ]
    )
    report = detectar_pagos(
        session, tenant, today=TODAY, belvo_client=belvo, belvo_link_id="link-1"
    )
    # Diego PROPONE: el pago entra pendiente de conciliar, la factura NO se cierra sola.
    from aiuda_core.models import Payment

    assert report.pagos_por_conciliar == 1
    session.refresh(invoice)
    assert invoice.status == "open"  # la confirma el humano, no el match de monto
    pago = session.scalar(select(Payment).where(Payment.tenant_id == tenant.id))
    assert pago is not None and pago.status == "pendiente"
    assert float(pago.amount) == 12500.50 and pago.source == "banco"


def test_detectar_pagos_no_duplica_en_recorrida(session, tenant, customer, invoice):
    from aiuda_core.models import Payment

    belvo = FakeBelvo(
        [
            BankTransaction(
                id="t1", amount=12500.50, description="SPEI", value_date="2026-06-08",
                type="INFLOW", account_id="a1",
            )
        ]
    )
    detectar_pagos(session, tenant, today=TODAY, belvo_client=belvo, belvo_link_id="link-1")
    detectar_pagos(session, tenant, today=TODAY, belvo_client=belvo, belvo_link_id="link-1")
    pagos = session.scalars(select(Payment).where(Payment.tenant_id == tenant.id)).all()
    assert len(pagos) == 1  # no se duplica el mismo pago


def test_detectar_pagos_sin_match_no_toca_nada(session, tenant, customer, invoice):
    belvo = FakeBelvo([])
    report = detectar_pagos(
        session, tenant, today=TODAY, belvo_client=belvo, belvo_link_id="link-1"
    )
    assert report.pagos_por_conciliar == 0
    session.refresh(invoice)
    assert invoice.status == "open"


class FakePasarela:
    """Pasarela de cobro fake (Mercado Pago/Clip/Conekta comparten la interfaz)."""

    def __init__(self, pagos):
        self._pagos = pagos

    def list_recent_payments(self):
        return self._pagos

    def match_payment(self, pagos, amount):
        for p in pagos:
            if abs(p.amount - amount) <= 1.0:
                return p
        return None


def test_detectar_pagos_confirma_con_pasarela(session, tenant, customer, invoice):
    from aiuda_core.connectors.mercadopago import PagoMP
    from aiuda_core.models import Payment

    pago = PagoMP(id="mp1", amount=12500.50, currency="MXN", description="", payer_email="", approved=True, created="")
    report = detectar_pagos(
        session, tenant, today=TODAY,
        pasarela_clients={"mercadopago": FakePasarela([pago])},
    )
    # Igual que banco/stripe: PROPONE pendiente de conciliar, no cierra la factura.
    assert report.pagos_por_conciliar == 1
    assert "mercadopago" in report.fuentes
    session.refresh(invoice)
    assert invoice.status == "open"
    p = session.scalar(select(Payment).where(Payment.tenant_id == tenant.id))
    assert p is not None and p.source == "mercadopago" and float(p.amount) == 12500.50


def test_sin_credenciales_no_hace_nada(session, tenant):
    report = sync_pedidos(session, tenant, today=TODAY)
    assert report.pedidos_importados == 0
    assert report.fuentes == []


def test_deposito_del_mes_siguiente_con_mismo_importe_si_entra(session, tenant, customer, invoice):
    """Renta mensual: el mismo importe cada mes. El dedup era por monto+fuente a
    secas, sin fecha ni referencia: el pago de un mes (ya conciliado) hacía que
    el depósito del mes siguiente jamás entrara a conciliación — pagos que se
    pierden en silencio. El dedup se acota a la ventana de detección."""
    from datetime import timedelta

    from aiuda_core.models import Payment

    # El pago del mes pasado, ya conciliado, fuera de la ventana de detección.
    session.add(Payment(
        tenant_id=tenant.id, amount=invoice.amount, currency="MXN",
        paid_at=TODAY - timedelta(days=40), source="banco", status="conciliado",
    ))
    session.flush()

    belvo = FakeBelvo([
        BankTransaction(
            id="t2", amount=12500.50, description="SPEI RENTA JULIO",
            value_date=str(TODAY), type="INFLOW", account_id="a1",
        )
    ])
    report = detectar_pagos(
        session, tenant, today=TODAY, belvo_client=belvo, belvo_link_id="link-1"
    )
    assert report.pagos_por_conciliar == 1  # el depósito de este mes SÍ entra
    pagos = session.scalars(
        select(Payment).where(Payment.tenant_id == tenant.id, Payment.source == "banco")
    ).all()
    assert len(pagos) == 2  # el conciliado viejo y el nuevo por conciliar
