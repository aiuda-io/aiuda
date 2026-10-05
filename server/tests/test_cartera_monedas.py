"""`GET /v1/cartera` sumaba pesos y dólares como si fueran la misma moneda: una
factura de 10,000 USD contaba como 10,000 MXN. Los totales van por moneda.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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


# ---------- 1. Pesos y dólares no se suman ----------


def test_cartera_no_suma_pesos_con_dolares(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "M-1", 1000)
    _inv(db_session, tenant, customer, "M-2", 500, dias_vencida=-5)  # aún no vence
    _inv(db_session, tenant, customer, "U-1", 10000, currency="USD")

    data = client.get("/v1/cartera").json()

    # Los campos de siempre hablan SOLO de la moneda principal.
    assert data["moneda_principal"] == "MXN"
    assert data["open_total"] == 1500
    assert data["open_count"] == 2
    assert sum(line["total"] for line in data["aging"]) == 1500
    assert data["open_count_todas"] == 3

    # El desglose trae cada moneda por separado, la principal primero.
    assert [m["moneda"] for m in data["por_moneda"]] == ["MXN", "USD"]
    mxn, usd = data["por_moneda"]
    assert (mxn["open_total"], mxn["open_count"], mxn["overdue_total"]) == (1500, 2, 1000)
    assert (usd["open_total"], usd["open_count"], usd["overdue_total"]) == (10000, 1, 10000)
    assert sum(line["count"] for line in usd["aging"]) == 1
    assert {line["bucket"] for line in usd["aging"]} == {line["bucket"] for line in data["aging"]}


def test_cartera_solo_en_dolares_usa_dolares_como_principal(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "U-1", 200, currency="usd")  # minúsculas: se normaliza

    data = client.get("/v1/cartera").json()

    assert data["moneda_principal"] == "USD"
    assert data["open_total"] == 200 and data["open_count"] == 1
    assert [m["moneda"] for m in data["por_moneda"]] == ["USD"]


def test_cartera_vacia_sigue_trayendo_la_forma_completa(client, tenant):
    data = client.get("/v1/cartera").json()

    assert data["moneda_principal"] == "MXN"
    assert data["open_total"] == 0 and data["open_count"] == 0
    assert len(data["por_moneda"]) == 1 and data["por_moneda"][0]["moneda"] == "MXN"
    assert len(data["aging"]) == len(data["por_moneda"][0]["aging"]) > 0


def test_recuperado_del_mes_va_por_moneda(client, db_session, tenant, customer):
    ahora = datetime.now(timezone.utc)
    for folio, monto, moneda in (("M-1", 300, "MXN"), ("U-1", 70, "USD")):
        inv = _inv(
            db_session, tenant, customer, folio, monto, currency=moneda,
            status="paid", paid_at=ahora,
        )
        _reminder(db_session, tenant, inv, "sent")

    data = client.get("/v1/cartera").json()

    assert data["recovered_this_month"] == 300
    recuperado = {m["moneda"]: m["recovered_this_month"] for m in data["por_moneda"]}
    assert recuperado == {"MXN": 300, "USD": 70}


def test_promesas_traen_la_moneda_de_su_factura(client, db_session, tenant, customer):
    _promesa(db_session, tenant, _inv(db_session, tenant, customer, "U-1", 900, currency="USD"))

    assert client.get("/v1/promises").json()[0]["currency"] == "USD"


# ---------- 3. El mismo criterio en clientes y en el SAT ----------


def test_la_lista_de_clientes_no_suma_pesos_con_dolares(client, db_session, tenant, customer):
    solo_usd = Customer(tenant_id=tenant.id, name="Exportadora Norte", phone="5215511110002")
    sin_saldo = Customer(tenant_id=tenant.id, name="Zapatería Sol", phone="5215511110003")
    db_session.add_all([solo_usd, sin_saldo])
    db_session.flush()
    _inv(db_session, tenant, customer, "M-1", 1000)
    _inv(db_session, tenant, customer, "U-1", 10000, currency="USD")
    _inv(db_session, tenant, solo_usd, "U-2", 250, currency="usd")
    _inv(db_session, tenant, solo_usd, "U-3", 50, currency="USD", status="paid")

    por_nombre = {c["name"]: c for c in client.get("/v1/customers").json()}

    mixto = por_nombre["Papelería Bic"]
    assert (mixto["open_total"], mixto["moneda"], mixto["open_invoices"]) == (1000, "MXN", 2)
    assert mixto["por_moneda"] == [
        {"moneda": "MXN", "open_total": 1000, "open_count": 1},
        {"moneda": "USD", "open_total": 10000, "open_count": 1},
    ]
    usd = por_nombre["Exportadora Norte"]
    assert (usd["open_total"], usd["moneda"], usd["open_invoices"]) == (250, "USD", 1)
    vacio = por_nombre["Zapatería Sol"]
    assert (vacio["open_total"], vacio["moneda"], vacio["por_moneda"]) == (0, "MXN", [])


def test_la_ficha_del_cliente_dice_la_moneda_de_cada_cifra(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "M-1", 1000)
    _inv(db_session, tenant, customer, "U-1", 10000, currency="USD")

    ficha = client.get(f"/v1/customers/{customer.id}").json()

    assert (ficha["open_total"], ficha["moneda"], ficha["open_count"]) == (1000, "MXN", 2)
    assert [(p["moneda"], p["open_total"]) for p in ficha["por_moneda"]] == [
        ("MXN", 1000), ("USD", 10000),
    ]
    assert {i["folio"]: i["currency"] for i in ficha["invoices"]} == {"M-1": "MXN", "U-1": "USD"}


def test_el_sat_tampoco_suma_pesos_con_dolares(client, db_session, tenant, customer):
    _inv(db_session, tenant, customer, "M-1", 1000)
    _inv(db_session, tenant, customer, "U-1", 10000, currency="USD")

    todo = client.get("/v1/sat/estado").json()["cartera"]["todo_junto"]

    assert (todo["abiertas"], todo["total"], todo["moneda"]) == (2, 1000, "MXN")
    assert [(p["moneda"], p["open_total"]) for p in todo["por_moneda"]] == [
        ("MXN", 1000), ("USD", 10000),
    ]
