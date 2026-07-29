"""API de write-back: estado visible en la ficha y reintento manual."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Customer, Invoice, OutboxEntry, Tenant
from aiuda_server.api.main import app, get_db

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


def _factura_odoo(db_session, tenant) -> Invoice:
    cust = Customer(tenant_id=tenant.id, name="Cliente Odoo", phone="5215511223344")
    db_session.add(cust)
    db_session.flush()
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=cust.id,
        folio="F-100",
        amount=8120.00,
        issued_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        source="odoo",
        presence={"odoo": {"ref": "F-100"}},
    )
    db_session.add(inv)
    db_session.flush()
    return inv


def test_pagar_encola_y_la_ficha_ve_el_estado(client, db_session, tenant):
    inv = _factura_odoo(db_session, tenant)
    res = client.post(f"/v1/invoices/{inv.id}/pay", headers=HEADERS)
    assert res.status_code == 200

    listado = client.get(f"/v1/writeback?invoice_id={inv.id}", headers=HEADERS).json()
    assert len(listado["entries"]) == 1
    entrada = listado["entries"][0]
    assert entrada["target"] == "odoo"
    assert entrada["action"] == "registrar_pago"
    assert entrada["estado"] == "pendiente"  # aún sin procesar: espera al worker
    assert entrada["folio"] == "F-100"
    assert entrada["amount"] == 8120.0

    # El filtro es por registro: otra factura no ve esta inyección
    ajeno = client.get("/v1/writeback?invoice_id=otra", headers=HEADERS).json()
    assert ajeno["entries"] == []


def test_filtro_por_cliente(client, db_session, tenant):
    cust = Customer(
        tenant_id=tenant.id,
        name="Cliente Espejo",
        phone="5215599887766",
        presence={"odoo": {"ref": "12"}},
    )
    db_session.add(cust)
    db_session.flush()
    res = client.put(
        f"/v1/customers/{cust.id}", headers=HEADERS, json={"name": "Cliente Espejo SA"}
    )
    assert res.status_code == 200 and res.json()["writeback"] == ["odoo"]

    listado = client.get(f"/v1/writeback?customer_id={cust.id}", headers=HEADERS).json()
    assert len(listado["entries"]) == 1
    assert listado["entries"][0]["action"] == "actualizar_cliente"
    assert listado["entries"][0]["changes"] == {"name": "Cliente Espejo SA"}


def test_reintentar_fallida_resetea_y_dispara_proceso(client, db_session, tenant, monkeypatch):
    import aiuda_server.worker.main as worker

    corridas: list[str] = []
    monkeypatch.setattr(worker, "process_writebacks_blocking", lambda tid: corridas.append(tid))

    entry = OutboxEntry(
        tenant_id=tenant.id,
        target="odoo",
        action="registrar_pago",
        payload={"invoice_id": "inv1", "folio": "F-100", "amount": 100.0, "paid_source": "manual"},
        status="failed",
        attempts=5,
        last_error="Odoo no responde",
    )
    db_session.add(entry)
    db_session.flush()

    res = client.post(f"/v1/writeback/{entry.id}/retry", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["estado"] == "pendiente"
    assert body["attempts"] == 0
    assert body["last_error"] == "Odoo no responde"  # el rastro se conserva
    assert corridas == [tenant.id]  # el procesado se disparó en segundo plano

    fila = db_session.scalar(select(OutboxEntry).where(OutboxEntry.id == entry.id))
    assert fila.status == "pending" and fila.attempts == 0


def test_reintentar_solo_fallidas(client, db_session, tenant):
    entry = OutboxEntry(
        tenant_id=tenant.id,
        target="odoo",
        action="registrar_pago",
        payload={"folio": "F-100"},
        status="pending",
    )
    db_session.add(entry)
    db_session.flush()
    res = client.post(f"/v1/writeback/{entry.id}/retry", headers=HEADERS)
    assert res.status_code == 409
    assert client.post("/v1/writeback/no-existe/retry", headers=HEADERS).status_code == 404


def test_writeback_de_otro_tenant_no_se_ve(client, db_session, tenant):
    otro = Tenant(name="Otro", owner_phone="5215500000000", evolution_instance="otro", config={})
    db_session.add(otro)
    db_session.flush()
    entry = OutboxEntry(
        tenant_id=otro.id,
        target="odoo",
        action="registrar_pago",
        payload={"invoice_id": "inv-ajena", "folio": "F-9"},
        status="failed",
        attempts=5,
    )
    db_session.add(entry)
    db_session.flush()

    listado = client.get("/v1/writeback", headers=HEADERS).json()
    assert all(e["id"] != entry.id for e in listado["entries"])
    assert client.post(f"/v1/writeback/{entry.id}/retry", headers=HEADERS).status_code == 404
