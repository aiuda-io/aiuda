"""Errores de las rutas que usa Cartera: en español, con código cuando la pantalla
necesita reconocerlos, y sin el texto de la excepción.
"""

from datetime import date, timedelta

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
from aiuda_server.api.main import _errores_de_importacion, app, get_db

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


# ---------- 3. Errores con código, sin el texto de la excepción ----------


def test_recordar_con_el_tope_de_ia_agotado_lo_dice_sin_cifras_tecnicas(
    client, db_session, tenant, customer, monkeypatch
):
    from aiuda_core.engine.engine import CleoEngine
    from aiuda_core.engine.llm import BudgetExceeded

    inv = _inv(db_session, tenant, customer, "M-1", 1000)

    def sin_presupuesto(self, invoice, customer, today, broken_promise=None):
        raise BudgetExceeded("Se alcanzó el tope (9,000 de 9,000 tokens); ia_tope_tokens_mes")

    monkeypatch.setattr(CleoEngine, "draft_reminder", sin_presupuesto)

    res = client.post(f"/v1/invoices/{inv.id}/remind")

    assert res.status_code == 402
    assert res.json()["code"] == "ia_tope"
    assert "tope de uso de este mes" in res.json()["detail"]
    assert "token" not in res.text and "ia_tope_tokens_mes" not in res.text


def test_importar_sin_ia_trae_codigo_para_poner_la_liga(client, tenant, monkeypatch):
    import aiuda_core.connectors.smart_import as smart_import

    def boom(*a, **k):
        raise RuntimeError("Could not resolve authentication method")

    monkeypatch.setattr(smart_import, "analyze", boom)

    res = client.post(
        "/v1/import/analyze", files={"file": ("cartera.csv", b"folio,monto\nF-1,10\n", "text/csv")}
    )

    assert res.status_code == 409
    assert res.json()["code"] == "ia_no_conectada"
    assert "Could not" not in res.text


def test_filas_ilegibles_del_importador_no_llevan_la_excepcion():
    avisos = _errores_de_importacion(
        [
            "Fila 3: could not convert string to float: 'mil pesos'",
            "Fila 9: fecha no reconocida: '32/13/2026'",
            "2 sin teléfono: cargados, pero aún no se les puede escribir por WhatsApp.",
        ]
    )

    assert avisos[0].startswith("Las filas 3, 9 no se pudieron leer")
    assert "could not convert" not in " ".join(avisos)
    assert avisos[1].startswith("2 sin teléfono")
    assert _errores_de_importacion(["Fila 4: x"])[0].startswith("La fila 4 no se pudo leer")
    assert _errores_de_importacion([]) == []
