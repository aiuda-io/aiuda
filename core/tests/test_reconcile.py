"""Conciliación (Diego): propone la factura de un pago, no la cierra sola.

Cubre el contrato del matching: exacto, tolerancia configurable, ambiguo (parejas =
sin propuesta única), grupos multifactura, pago parcial y match contra saldo."""

from datetime import date

from aiuda_core.engine.reconcile import (
    evaluate,
    propose_groups,
    propose_matches,
    saldo_pendiente,
    tolerancia,
)
from aiuda_core.models import Customer, Invoice, Payment


def _inv(session, tenant, customer, folio, amount, **kw):
    inv = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio=folio, amount=amount,
        issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open", **kw,
    )
    session.add(inv)
    session.flush()
    return inv


def _pay(session, tenant, amount, **kw):
    kw.setdefault("paid_at", date(2026, 6, 1))
    kw.setdefault("source", "banco")
    pay = Payment(tenant_id=tenant.id, amount=amount, currency="MXN", **kw)
    session.add(pay)
    session.flush()
    return pay


def test_propone_monto_exacto_primero(session, tenant, customer):
    _inv(session, tenant, customer, "A-1", 500)
    _inv(session, tenant, customer, "A-2", 1000)
    pay = _pay(session, tenant, 1000)
    cands = propose_matches(session, tenant.id, pay)
    assert cands and cands[0].folio == "A-2"
    assert cands[0].cuadra is True
    assert "monto exacto" in cands[0].reason


def test_nombre_del_depositante_desempata(session, tenant):
    """Dos facturas del mismo monto: gana la del cliente cuyo nombre va en el depósito."""
    a = Customer(tenant_id=tenant.id, name="Papelería Bic", phone="5215511110001")
    b = Customer(tenant_id=tenant.id, name="Restaurante Fogón", phone="5215511110002")
    session.add_all([a, b])
    session.flush()
    _inv(session, tenant, a, "M-104", 17073.60)
    _inv(session, tenant, b, "M-105", 17073.60)
    pay = _pay(session, tenant, 17073.60, source="stripe", counterparty="PAPELERIA BIC SA DE CV")
    cands = propose_matches(session, tenant.id, pay)
    assert cands[0].folio == "M-104"  # desempata por nombre
    assert cands[0].score > cands[1].score
    # Con la señal del nombre la distancia es clara: NO es ambiguo.
    ev = evaluate(session, tenant.id, pay)
    assert ev.ambiguous is False and ev.proposal_kind == "factura"


def test_sin_coincidencia_de_monto_no_propone(session, tenant, customer):
    _inv(session, tenant, customer, "A-1", 500)
    pay = _pay(session, tenant, 99999)
    assert propose_matches(session, tenant.id, pay) == []
    ev = evaluate(session, tenant.id, pay)
    assert ev.candidates == [] and ev.groups == [] and ev.note


def test_tolerancia_configurable_abre_el_match(session, tenant, customer):
    """$1,080 contra un pago de $1,000: con la tolerancia default no cuadra;
    subiéndola a 10% sí, y la razón lo dice."""
    _inv(session, tenant, customer, "T-1", 1080)
    pay = _pay(session, tenant, 1000)
    assert propose_matches(session, tenant.id, pay) == []
    cands = propose_matches(session, tenant.id, pay, tol_pct=10.0, tol_abs=1.0)
    assert cands and cands[0].folio == "T-1" and cands[0].cuadra is False
    assert "tolerancia" in cands[0].reason


def test_tolerancia_lee_config_del_tenant():
    assert tolerancia(None) == (1.0, 1.0)
    assert tolerancia({}) == (1.0, 1.0)
    assert tolerancia({"conciliacion": {"tolerancia_pct": 2.5, "tolerancia_abs": 5}}) == (2.5, 5.0)
    # Basura en config no truena: cae al default.
    assert tolerancia({"conciliacion": {"tolerancia_pct": "x"}}) == (1.0, 1.0)
    # Negativos se recortan a cero, no a tolerancia fantasma.
    assert tolerancia({"conciliacion": {"tolerancia_pct": -3, "tolerancia_abs": -1}}) == (0.0, 0.0)


def test_ambiguo_dos_exactas_sin_senal_no_propone(session, tenant):
    """Dos facturas del mismo monto y NADA que las distinga: ambiguo, decide el humano."""
    a = Customer(tenant_id=tenant.id, name="Cliente Uno", phone="5215511110003")
    b = Customer(tenant_id=tenant.id, name="Cliente Dos", phone="5215511110004")
    session.add_all([a, b])
    session.flush()
    _inv(session, tenant, a, "X-1", 5000)
    _inv(session, tenant, b, "X-2", 5000)
    pay = _pay(session, tenant, 5000)
    ev = evaluate(session, tenant.id, pay)
    assert ev.ambiguous is True
    assert ev.proposal_kind is None
    assert "parejas" in ev.note
    assert len(ev.candidates) == 2  # las dos se presentan, ninguna se elige sola


def test_grupo_multifactura_mismo_cliente(session, tenant, customer):
    """Un depósito de $1,000 que liquida dos facturas de $600 y $400 del mismo cliente."""
    _inv(session, tenant, customer, "G-1", 600)
    _inv(session, tenant, customer, "G-2", 400)
    pay = _pay(session, tenant, 1000, counterparty="CLIENTE DEMO")
    groups = propose_groups(session, tenant.id, pay)
    assert groups and groups[0].cuadra is True
    assert sorted(groups[0].folios) == ["G-1", "G-2"]
    assert groups[0].total == 1000.0
    assert "2 facturas del cliente" in groups[0].reason
    assert "nombre del cliente en el depósito" in groups[0].reason
    # Ninguna factura sola alcanza el monto: la propuesta es el grupo.
    ev = evaluate(session, tenant.id, pay)
    assert ev.proposal_kind == "grupo" and ev.ambiguous is False


def test_grupo_no_cruza_clientes(session, tenant):
    """$1,000 = $600 de un cliente + $400 de OTRO: eso no es un grupo, es inventar."""
    a = Customer(tenant_id=tenant.id, name="Cliente A", phone="5215511110005")
    b = Customer(tenant_id=tenant.id, name="Cliente B", phone="5215511110006")
    session.add_all([a, b])
    session.flush()
    _inv(session, tenant, a, "C-1", 600)
    _inv(session, tenant, b, "C-2", 400)
    pay = _pay(session, tenant, 1000)
    assert propose_groups(session, tenant.id, pay) == []


def test_parcial_solo_con_senal_de_cliente_o_folio(session, tenant, customer):
    """Un pago menor al saldo solo es candidata (abono) si el depósito trae al
    cliente o el folio; sin señal es ruido y no se propone."""
    _inv(session, tenant, customer, "P-1", 10000)
    sin_senal = _pay(session, tenant, 4000)
    assert propose_matches(session, tenant.id, sin_senal) == []
    con_senal = _pay(session, tenant, 4000, counterparty="SPEI CLIENTE DEMO")
    cands = propose_matches(session, tenant.id, con_senal)
    assert cands and cands[0].parcial is True and cands[0].cuadra is False
    assert "pago parcial" in cands[0].reason
    assert cands[0].saldo == 10000.0


def test_match_contra_saldo_con_abonos(session, tenant, customer):
    """Una factura de $1,000 con abono de $400 se concilia con un pago de $600:
    el match es contra lo que FALTA, no contra el total original."""
    inv = _inv(
        session, tenant, customer, "S-1", 1000,
        meta={"abonos": [{"payment_id": "p0", "aplicado": 400}]},
    )
    assert saldo_pendiente(inv) == 600.0
    pay = _pay(session, tenant, 600)
    cands = propose_matches(session, tenant.id, pay)
    assert cands and cands[0].folio == "S-1" and cands[0].cuadra is True
    assert cands[0].saldo == 600.0 and cands[0].amount == 1000.0


def test_fecha_cercana_al_vencimiento_suma(session, tenant):
    """Mismo monto en dos clientes distintos: gana la factura cuyo vencimiento está
    cerca de la fecha del pago (y la razón lo explica)."""
    a = Customer(tenant_id=tenant.id, name="Uno", phone="5215511110007")
    b = Customer(tenant_id=tenant.id, name="Dos", phone="5215511110008")
    session.add_all([a, b])
    session.flush()
    cerca = Invoice(
        tenant_id=tenant.id, customer_id=a.id, folio="F-CERCA", amount=2000,
        issued_date=date(2026, 5, 1), due_date=date(2026, 5, 30), status="open",
    )
    lejos = Invoice(
        tenant_id=tenant.id, customer_id=b.id, folio="F-LEJOS", amount=2000,
        issued_date=date(2026, 1, 1), due_date=date(2026, 1, 31), status="open",
    )
    session.add_all([cerca, lejos])
    session.flush()
    pay = _pay(session, tenant, 2000, paid_at=date(2026, 6, 1))
    cands = propose_matches(session, tenant.id, pay)
    assert cands[0].folio == "F-CERCA"
    assert "vencimiento" in cands[0].reason
    assert cands[0].score > cands[1].score
