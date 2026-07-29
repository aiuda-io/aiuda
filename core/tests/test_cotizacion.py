"""Vertical de Ventas: generar cotización (mismo molde HITL que cobranza)."""

import pytest
from datetime import date

from aiuda_core.agents.carlos.engine import CarlosEngine, QuoteError
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Ayudante, Customer, Product
from conftest import FakeResponse

TODAY = date(2026, 6, 9)


def engine(session, tenant, fake_client_factory):
    return CarlosEngine(session, tenant, runner=ClaudeRunner(client=fake_client_factory(
        FakeResponse("Con gusto le comparto su cotización:")
    )))


def productos(session, tenant):
    a = Product(tenant_id=tenant.id, name="Anillo oro 14k", sku="AN-14", price=1000, stock=5, unit="pza")
    b = Product(tenant_id=tenant.id, name="Pulsera plata", sku="PL-22", price=500, stock=10, unit="pza")
    session.add_all([a, b])
    session.flush()
    return a, b


def cliente(session, tenant):
    c = Customer(tenant_id=tenant.id, name="Joyería Aurora", phone="5215511112222")
    session.add(c)
    session.flush()
    return c


def con_cotizacion_cfg(session, tenant, cfg: dict):
    session.add(Ayudante(tenant_id=tenant.id, name="gio", aiuditas={"ventas.generar_cotizacion": cfg}))
    session.flush()


def test_cotiza_con_precios_reales_y_total(session, tenant, fake_client_factory):
    a, b = productos(session, tenant)
    c = cliente(session, tenant)
    r = engine(session, tenant, fake_client_factory).draft_quote(
        c, [{"product_id": a.id, "cantidad": 2}, {"product_id": b.id, "cantidad": 1}], today=TODAY
    )
    assert r.agent == "carlos" and r.status == "pending_approval"
    assert "Joyería Aurora" in r.title
    # subtotal = 1000*2 + 500*1 = 2500; sin descuento (default tope 0)
    assert "$2,500.00" in r.message
    assert "Anillo oro 14k x2" in r.message
    assert "Vigencia: 15 días" in r.message  # default


def test_descuento_se_topa_al_maximo(session, tenant, fake_client_factory):
    a, _ = productos(session, tenant)
    c = cliente(session, tenant)
    con_cotizacion_cfg(session, tenant, {"validez_dias": 15, "iva_incluido": True, "descuento_max": 10})
    # pide 25% pero el tope es 10%
    r = engine(session, tenant, fake_client_factory).draft_quote(
        c, [{"product_id": a.id, "cantidad": 1}], descuento_pct=25, today=TODAY
    )
    assert "Descuento (10%)" in r.message  # topado
    assert "-$100.00" in r.message  # 10% de 1000


def test_iva_aparte_cuando_no_incluido(session, tenant, fake_client_factory):
    a, _ = productos(session, tenant)
    c = cliente(session, tenant)
    con_cotizacion_cfg(session, tenant, {"validez_dias": 30, "iva_incluido": False, "descuento_max": 0})
    r = engine(session, tenant, fake_client_factory).draft_quote(
        c, [{"product_id": a.id, "cantidad": 1}], today=TODAY
    )
    assert "IVA (16%): $160.00" in r.message  # 1000 * 0.16
    assert "Total: $1,160.00" in r.message
    assert "Vigencia: 30 días" in r.message


def test_cotizacion_guarda_procedencia_de_los_precios(session, tenant, fake_client_factory):
    a, _ = productos(session, tenant)
    a.source = "excel"
    a.presence = {"excel": {"file": "catalogo.xlsx", "at": "2026-06-15"}}
    c = cliente(session, tenant)
    r = engine(session, tenant, fake_client_factory).draft_quote(
        c, [{"product_id": a.id, "cantidad": 1}], today=TODAY
    )
    proc = (r.meta or {}).get("procedencia")
    assert proc and proc["source"] == "excel"
    assert proc["presence"]["excel"]["file"] == "catalogo.xlsx"
    # la procedencia NO se filtra al mensaje del cliente
    assert "catalogo.xlsx" not in r.message


def test_producto_inexistente_falla(session, tenant, fake_client_factory):
    c = cliente(session, tenant)
    with pytest.raises(QuoteError):
        engine(session, tenant, fake_client_factory).draft_quote(
            c, [{"product_id": "no-existe", "cantidad": 1}], today=TODAY
        )


def test_sin_partidas_falla(session, tenant, fake_client_factory):
    c = cliente(session, tenant)
    with pytest.raises(QuoteError):
        engine(session, tenant, fake_client_factory).draft_quote(c, [], today=TODAY)
