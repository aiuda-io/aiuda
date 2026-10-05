"""Al quedar pagada una factura, sus promesas abiertas quedan cumplidas y los
recordatorios que aún no salían dejan de estar pendientes. Antes ninguna de las
dos cosas pasaba, por ninguna de las puertas por las que se paga.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import (
    Base,
    Customer,
    Invoice,
    Payment,
    PaymentPromise,
    Reminder,
    Tenant,
)
from aiuda_server.api.main import app, get_db

HOY = date.today()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
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
    t = Tenant(name="Demo SA", owner_phone="5215512345678", evolution_instance="demo")
    db_session.add(t)
    db_session.flush()
    return t


@pytest.fixture()
def customer(db_session, tenant):
    c = Customer(tenant_id=tenant.id, name="Papelería Bic", phone="5215511110001")
    db_session.add(c)
    db_session.flush()
    return c


def _inv(db, tenant, customer, folio, amount, currency="MXN", dias_vencida=10, **kw):
    inv = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio=folio, amount=amount,
        currency=currency, issued_date=HOY - timedelta(days=60),
        due_date=HOY - timedelta(days=dias_vencida), **kw,
    )
    db.add(inv)
    db.flush()
    return inv


def _reminder(db, tenant, inv, status):
    r = Reminder(
        tenant_id=tenant.id, invoice_id=inv.id, bucket="vencida", tone="firme",
        message="Recordatorio", status=status,
    )
    db.add(r)
    db.flush()
    return r


def _promesa(db, tenant, inv, dias=3):
    p = PaymentPromise(
        tenant_id=tenant.id, invoice_id=inv.id, promised_date=HOY + timedelta(days=dias),
        note="paga el viernes",
    )
    db.add(p)
    db.flush()
    return p


def _deposito(db, tenant, monto):
    pago = Payment(
        tenant_id=tenant.id, amount=monto, currency="MXN", paid_at=HOY, source="banco",
        status="pendiente",
    )
    db.add(pago)
    db.flush()
    return pago


# ---------- 2. Lo que se cierra al pagar ----------


def test_registrar_pago_cumple_promesas_y_retira_recordatorios(
    client, db_session, tenant, customer
):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    otra = _inv(db_session, tenant, customer, "M-2", 400)
    promesa = _promesa(db_session, tenant, inv)
    promesa_ajena = _promesa(db_session, tenant, otra)
    pendiente = _reminder(db_session, tenant, inv, "pending_approval")
    enviado = _reminder(db_session, tenant, inv, "sent")
    ajeno = _reminder(db_session, tenant, otra, "pending_approval")

    res = client.post(f"/v1/invoices/{inv.id}/pay")

    assert res.status_code == 200
    assert res.json()["promesas_cumplidas"] == 1
    assert res.json()["recordatorios_retirados"] == 1
    assert promesa.fulfilled is True and promesa.fulfilled_at is not None
    # El pendiente deja de estar pendiente, con su motivo; lo enviado es historia.
    assert pendiente.status == "rejected"
    assert pendiente.meta["retirado"] == "La factura ya se pagó."
    assert enviado.status == "sent"
    # Lo de otra factura no se toca.
    assert promesa_ajena.fulfilled is False and ajeno.status == "pending_approval"
    # Y ya no cuenta en lo que espera al dueño.
    assert [p["id"] for p in client.get("/v1/promises").json()] == [promesa_ajena.id]
    assert client.get("/v1/cartera").json()["espera_tu_ok"] == 1


def test_conciliar_un_deposito_tambien_cumple_y_retira(client, db_session, tenant, customer):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    promesa = _promesa(db_session, tenant, inv)
    pendiente = _reminder(db_session, tenant, inv, "pending_approval")
    pago = _deposito(db_session, tenant, 1000)

    res = client.post(f"/v1/reconciliation/{pago.id}/confirm", json={"invoice_ids": [inv.id]})

    assert res.status_code == 200
    assert inv.status == "paid"
    assert promesa.fulfilled is True
    assert pendiente.status == "rejected"


def test_un_abono_parcial_no_cumple_la_promesa(client, db_session, tenant, customer):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    promesa = _promesa(db_session, tenant, inv)
    pendiente = _reminder(db_session, tenant, inv, "pending_approval")
    pago = _deposito(db_session, tenant, 300)

    res = client.post(f"/v1/reconciliation/{pago.id}/confirm", json={"invoice_ids": [inv.id]})

    assert res.status_code == 200
    assert inv.status == "open"
    assert promesa.fulfilled is False and pendiente.status == "pending_approval"


def test_cerrar_pendientes_retira_solo_lo_que_aun_podia_salir(db_session, tenant, customer):
    from aiuda_core.engine.sync import cerrar_pendientes_por_pago

    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    promesa = _promesa(db_session, tenant, inv)
    for estado in ("draft", "pending_approval", "approved", "failed", "sent", "rejected"):
        _reminder(db_session, tenant, inv, estado)

    assert cerrar_pendientes_por_pago(db_session, inv) == (1, 4)
    # Repetirlo no hace nada: ya no queda nada abierto.
    assert cerrar_pendientes_por_pago(db_session, inv) == (0, 0)
    assert promesa.fulfilled is True
    estados = sorted(
        r.status for r in db_session.scalars(select(Reminder).where(Reminder.invoice_id == inv.id))
    )
    assert estados == ["rejected"] * 5 + ["sent"]
