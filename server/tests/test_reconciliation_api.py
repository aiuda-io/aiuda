"""Flujo completo de conciliación por API: bandeja con evidencia, confirmar (cierra
con auditoría y write-back), parcial (abona sin cerrar), multifactura, ajustar,
rechazar, dichos de pago contrastados contra banco, historial y tolerancia.

HITL siempre: ninguna factura se cierra sin un confirm explícito del humano."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server.api.main import app, get_db
from aiuda_core.models import (
    AuditLog,
    Base,
    Customer,
    Invoice,
    OutboxEntry,
    Payment,
    Tenant,
)

HEADERS = {"X-API-Key": "k-demo"}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.state.queue = None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant(db_session):
    t = Tenant(
        name="Demo SA",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={"api_key": "k-demo"},
    )
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture()
def customer(db_session, tenant):
    c = Customer(tenant_id=tenant.id, name="Papelería Bic", phone="5215511110001")
    db_session.add(c)
    db_session.flush()
    return c


def _inv(db, tenant, customer, folio, amount, **kw):
    inv = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio=folio, amount=amount,
        issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open", **kw,
    )
    db.add(inv)
    db.flush()
    return inv


def _pay(db, tenant, amount, **kw):
    kw.setdefault("paid_at", date(2026, 6, 1))
    kw.setdefault("source", "banco")
    kw.setdefault("status", "pendiente")
    pay = Payment(tenant_id=tenant.id, amount=amount, currency="MXN", **kw)
    db.add(pay)
    db.flush()
    return pay


def _audit_actions(db, tenant):
    return [a.action for a in db.scalars(
        select(AuditLog).where(AuditLog.tenant_id == tenant.id)
    ).all()]


def test_bandeja_trae_evidencia_fuentes_y_config(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "M-104", 17073.60)
    _pay(db_session, tenant, 17073.60, source="stripe", counterparty="PAPELERIA BIC SA DE CV")

    data = client.get("/v1/reconciliation", headers=HEADERS).json()
    assert data["count"] == 1
    item = data["pending"][0]
    assert item["proposal"]["folio"] == "M-104"
    assert item["proposal"]["cuadra"] is True
    # Evidencia explicable: señales con nombre y score.
    assert "monto exacto" in item["proposal"]["reason"]
    assert "nombre del cliente" in item["proposal"]["reason"]
    assert item["proposal"]["score"] > 100
    assert item["proposal"]["saldo"] == 17073.60
    assert item["ambiguo"] is False and item["propuesta_tipo"] == "factura"
    # Estado honesto de las fuentes: sin credenciales y NUNCA verificadas en vivo.
    assert data["fuentes"]["belvo"] == {"configurada": False, "verificada_en_vivo": False}
    assert data["fuentes"]["stripe"]["verificada_en_vivo"] is False
    assert data["config"] == {"tolerancia_pct": 1.0, "tolerancia_abs": 1.0}


def test_ambiguo_no_propone_y_lo_dice(client, db_session, tenant):
    a = Customer(tenant_id=tenant.id, name="Cliente Uno", phone="5215511110002")
    b = Customer(tenant_id=tenant.id, name="Cliente Dos", phone="5215511110003")
    db_session.add_all([a, b])
    db_session.flush()
    _inv(db_session, tenant, a, "X-1", 5000)
    _inv(db_session, tenant, b, "X-2", 5000)
    _pay(db_session, tenant, 5000)

    item = client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]
    assert item["ambiguo"] is True
    assert item["proposal"] is None  # sin propuesta única: decide el humano
    assert len(item["alternates"]) == 2  # las dos candidatas, parejas
    assert "parejas" in item["nota"]


def test_confirmar_cierra_con_auditoria_y_writeback(client, db_session, tenant, customer):
    # source=odoo para verificar que el cierre encola el write-back a la fuente.
    inv = _inv(db_session, tenant, customer, "M-104", 17073.60, source="odoo")
    pay = _pay(db_session, tenant, 17073.60, source="stripe", counterparty="PAPELERIA BIC")

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["invoice"]["status"] == "paid"
    assert body["invoices"][0]["cerrada"] is True and body["invoices"][0]["saldo"] == 0.0

    db_session.refresh(inv)
    db_session.refresh(pay)
    assert inv.status == "paid" and inv.paid_source == "stripe" and inv.verified == "verificada"
    assert pay.status == "conciliado" and pay.invoice_id == inv.id
    assert pay.meta["aplicaciones"][0]["folio"] == "M-104"
    # Procedencia del cobro en la factura: el abono queda registrado con su fuente.
    assert inv.meta["abonos"][0]["source"] == "stripe"
    # Auditoría: quién concilió qué.
    assert "payment.reconcile" in _audit_actions(db_session, tenant)
    # Write-back encolado hacia Odoo (la fuente de la factura).
    outbox = db_session.scalar(select(OutboxEntry).where(OutboxEntry.tenant_id == tenant.id))
    assert outbox is not None and outbox.action == "registrar_pago" and outbox.target == "odoo"

    # Ya conciliado: no se puede de nuevo.
    again = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert again.status_code == 409


def test_parcial_abona_sin_cerrar_y_luego_liquida(client, db_session, tenant, customer):
    inv = _inv(db_session, tenant, customer, "P-1", 10000)
    abono = _pay(db_session, tenant, 4000, counterparty="PAPELERIA BIC")

    res = client.post(
        f"/v1/reconciliation/{abono.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert res.status_code == 200
    aplicacion = res.json()["invoices"][0]
    assert aplicacion["cerrada"] is False and aplicacion["saldo"] == 6000.0

    db_session.refresh(inv)
    db_session.refresh(abono)
    assert inv.status == "open"  # HITL y honestidad: un abono NO cierra la factura
    assert inv.meta["abonos"][0]["aplicado"] == 4000.0
    assert abono.status == "conciliado"
    assert "payment.abono" in _audit_actions(db_session, tenant)

    # La bandeja ahora casa contra el SALDO (6,000), no contra el total original.
    resto = _pay(db_session, tenant, 6000)
    item = client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]
    assert item["proposal"]["folio"] == "P-1" and item["proposal"]["saldo"] == 6000.0

    res2 = client.post(
        f"/v1/reconciliation/{resto.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert res2.status_code == 200 and res2.json()["invoice"]["status"] == "paid"
    db_session.refresh(inv)
    assert inv.status == "paid" and len(inv.meta["abonos"]) == 2


def test_multifactura_cierra_varias_en_cascada(client, db_session, tenant, customer):
    inv_a = _inv(db_session, tenant, customer, "G-1", 600)
    inv_b = _inv(db_session, tenant, customer, "G-2", 400)
    pay = _pay(db_session, tenant, 1000, counterparty="PAPELERIA BIC")

    # La bandeja propone el grupo (ninguna factura sola alcanza el monto).
    item = client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]
    assert item["propuesta_tipo"] == "grupo"
    grupo = item["grupos"][0]
    assert sorted(grupo["folios"]) == ["G-1", "G-2"] and grupo["cuadra"] is True

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm",
        headers=HEADERS,
        json={"invoice_ids": grupo["invoice_ids"]},
    )
    assert res.status_code == 200
    assert all(a["cerrada"] for a in res.json()["invoices"])
    db_session.refresh(inv_a)
    db_session.refresh(inv_b)
    assert inv_a.status == "paid" and inv_b.status == "paid"
    db_session.refresh(pay)
    assert len(pay.meta["aplicaciones"]) == 2


def test_multifactura_parcial_cierra_la_primera_y_abona_la_ultima(
    client, db_session, tenant, customer
):
    """$800 contra $600 + $400: cierra la más antigua y deja $200 de saldo en la otra."""
    vieja = _inv(db_session, tenant, customer, "V-1", 600)
    nueva = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio="V-2", amount=400,
        issued_date=date(2026, 5, 10), due_date=date(2026, 6, 15), status="open",
    )
    db_session.add(nueva)
    db_session.flush()
    pay = _pay(db_session, tenant, 800)

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm",
        headers=HEADERS,
        json={"invoice_ids": [nueva.id, vieja.id]},  # el orden lo pone el vencimiento, no el body
    )
    assert res.status_code == 200
    db_session.refresh(vieja)
    db_session.refresh(nueva)
    assert vieja.status == "paid"  # la más antigua por vencer se liquida primero
    assert nueva.status == "open"
    assert nueva.meta["abonos"][0]["aplicado"] == 200.0


def test_pago_que_excede_lo_elegido_se_rechaza(client, db_session, tenant, customer):
    inv = _inv(db_session, tenant, customer, "E-1", 500)
    pay = _pay(db_session, tenant, 2000)

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert res.status_code == 409
    assert "excede" in res.json()["detail"]
    db_session.refresh(inv)
    db_session.refresh(pay)
    assert inv.status == "open" and pay.status == "pendiente"  # nada cambió


def test_ajustar_confirma_otra_factura_distinta_a_la_propuesta(
    client, db_session, tenant, customer
):
    """El humano manda: puede aplicar el pago a una factura que Diego no propuso."""
    _inv(db_session, tenant, customer, "A-1", 1000)
    otra = _inv(db_session, tenant, customer, "A-2", 995)
    pay = _pay(db_session, tenant, 1000)

    item = client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]
    assert item["proposal"]["folio"] == "A-1"  # la propuesta es la exacta

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": otra.id}
    )
    # $1,000 contra $995: dentro de la tolerancia (±1% = $9.95) → cierra con excedente.
    assert res.status_code == 200
    db_session.refresh(otra)
    assert otra.status == "paid"
    assert res.json()["excedente"] == 5.0
    db_session.refresh(pay)
    assert pay.meta["excedente"] == 5.0  # el sobrante queda registrado, no desaparece


def test_rechazar_saca_de_bandeja_y_queda_en_historial(client, db_session, tenant):
    pay = _pay(db_session, tenant, 50)
    res = client.post(f"/v1/reconciliation/{pay.id}/ignore", headers=HEADERS)
    assert res.status_code == 200 and res.json()["status"] == "ignorado"
    assert client.get("/v1/reconciliation", headers=HEADERS).json()["count"] == 0
    assert "payment.ignore" in _audit_actions(db_session, tenant)

    resueltos = client.get("/v1/reconciliation/resueltos", headers=HEADERS).json()["resueltos"]
    assert resueltos[0]["id"] == pay.id and resueltos[0]["status"] == "ignorado"


def test_resueltos_muestra_aplicaciones(client, db_session, tenant, customer):
    inv = _inv(db_session, tenant, customer, "R-1", 700)
    pay = _pay(db_session, tenant, 700)
    client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    resueltos = client.get("/v1/reconciliation/resueltos", headers=HEADERS).json()["resueltos"]
    assert resueltos[0]["status"] == "conciliado"
    assert resueltos[0]["aplicaciones"][0]["folio"] == "R-1"
    assert resueltos[0]["aplicaciones"][0]["cerrada"] is True


def test_dicho_sin_respaldo_y_con_respaldo(client, db_session, tenant, customer):
    """El cliente DICE que pagó: sin movimiento que lo respalde la factura sigue
    abierta; cuando el banco trae un pago que cuadra, se concilia y cierra."""
    inv = _inv(db_session, tenant, customer, "D-1", 3000, payment_reported=True)

    data = client.get("/v1/reconciliation", headers=HEADERS).json()
    assert data["dichos"][0]["folio"] == "D-1"
    assert data["dichos"][0]["respaldo"] is None  # un dicho no es un pago

    pay = _pay(db_session, tenant, 3000, counterparty="PAPELERIA BIC")
    data = client.get("/v1/reconciliation", headers=HEADERS).json()
    respaldo = data["dichos"][0]["respaldo"]
    assert respaldo is not None and respaldo["payment_id"] == pay.id

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={"invoice_id": inv.id}
    )
    assert res.status_code == 200
    db_session.refresh(inv)
    assert inv.status == "paid" and inv.payment_reported is False
    # Ya cerrada: sale de la lista de dichos.
    assert client.get("/v1/reconciliation", headers=HEADERS).json()["dichos"] == []


def test_tolerancia_configurable_por_api(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "T-1", 1080)
    _pay(db_session, tenant, 1000)

    # Con la tolerancia default (±1%) no hay candidata.
    assert client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]["proposal"] is None

    res = client.put(
        "/v1/reconciliation/config",
        headers=HEADERS,
        json={"tolerancia_pct": 10, "tolerancia_abs": 1},
    )
    assert res.status_code == 200
    assert client.get("/v1/reconciliation/config", headers=HEADERS).json() == {
        "tolerancia_pct": 10.0,
        "tolerancia_abs": 1.0,
    }
    db_session.refresh(tenant)
    assert tenant.config["conciliacion"]["tolerancia_pct"] == 10
    assert "reconciliation.config" in _audit_actions(db_session, tenant)

    # Con ±10% la factura ya es candidata (y la razón nombra la tolerancia).
    item = client.get("/v1/reconciliation", headers=HEADERS).json()["pending"][0]
    assert item["proposal"]["folio"] == "T-1"
    assert "tolerancia" in item["proposal"]["reason"]

    # Valores sin sentido se rechazan.
    assert (
        client.put(
            "/v1/reconciliation/config",
            headers=HEADERS,
            json={"tolerancia_pct": -5, "tolerancia_abs": 1},
        ).status_code
        == 422
    )


def test_confirm_sin_facturas_es_422(client, db_session, tenant):
    pay = _pay(db_session, tenant, 100)
    res = client.post(f"/v1/reconciliation/{pay.id}/confirm", headers=HEADERS, json={})
    assert res.status_code == 422
