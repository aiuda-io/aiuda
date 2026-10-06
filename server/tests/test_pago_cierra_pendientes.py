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
    # La ficha de la factura dice por qué ya no está pendiente (no "rechazado" a secas).
    ficha = client.get(f"/v1/invoices/{inv.id}").json()
    assert {r["status"]: r["retirado"] for r in ficha["reminders"]} == {
        "rejected": "La factura ya se pagó.",
        "sent": None,
    }
    assert ficha["promises"][0]["fulfilled"] is True
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


@pytest.mark.parametrize("estado_factura", ["paid", "cancelled"])
def test_el_envio_no_deja_salir_lo_aprobado_de_una_factura_cerrada(
    monkeypatch, db_session, tenant, customer, estado_factura
):
    """La última puerta. Un recordatorio aprobado (esperando canal, o que se quedó
    atrás del cierre por pago) no sale si la factura ya no está abierta: ni se
    resuelve el canal ni se intenta el envío."""
    from contextlib import contextmanager

    import aiuda_server.worker.main as worker_main

    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    aprobado = _reminder(db_session, tenant, inv, "approved")
    fallido = _reminder(db_session, tenant, inv, "failed")
    inv.status = estado_factura
    db_session.flush()

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(worker_main, "session_scope", scope)

    def no_debe_llegar(*args, **kwargs):
        raise AssertionError("se intentó enviar un recordatorio de una factura cerrada")

    monkeypatch.setattr(worker_main, "resolve_whatsapp", no_debe_llegar)

    worker_main.send_reminder_blocking(tenant.id, aprobado.id)

    assert aprobado.status == "rejected"
    # El fallido de la misma factura tampoco queda vivo para un reintento.
    assert fallido.status == "rejected"
    if estado_factura == "paid":
        assert aprobado.meta["retirado"] == "La factura ya se pagó."


def test_no_se_aprueba_ni_se_reintenta_lo_de_una_factura_pagada(
    client, db_session, tenant, customer
):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    pendiente = _reminder(db_session, tenant, inv, "pending_approval")
    fallido = _reminder(db_session, tenant, inv, "failed")
    inv.status = "paid"
    db_session.flush()

    for r in (pendiente, fallido):
        res = client.post(f"/v1/reminders/{r.id}/approve")
        assert res.status_code == 409
        assert "ya se pagó" in res.json()["detail"]
    assert pendiente.status == "pending_approval" and fallido.status == "failed"


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


# ---------- 3. Una promesa vencida se puede dar por incumplida ----------


def test_dar_una_promesa_por_incumplida_la_saca_de_lo_que_espera_al_dueno(
    client, db_session, tenant, customer
):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    vencida = _promesa(db_session, tenant, inv, dias=-4)
    assert client.get("/v1/cartera").json()["espera_tu_ok"] == 1

    res = client.post(f"/v1/promises/{vencida.id}/no-cumplio")

    assert res.status_code == 200
    assert res.json() == {"id": vencida.id, "fulfilled": False, "incumplida": True}
    # No se marcó cumplida (sería mentir) ni se tocó la factura: se sigue cobrando.
    assert vencida.fulfilled is False and inv.status == "open"
    assert client.get("/v1/cartera").json()["espera_tu_ok"] == 0
    [p] = client.get("/v1/promises").json()
    assert (p["vencida"], p["incumplida"]) == (False, True)
    # Repetirlo no truena ni cambia la fecha en que se dio por incumplida.
    antes = dict(tenant.config["promesas_incumplidas"])
    assert client.post(f"/v1/promises/{vencida.id}/no-cumplio").status_code == 200
    assert tenant.config["promesas_incumplidas"] == antes


def test_no_se_da_por_incumplida_una_promesa_vigente_ni_una_cumplida(
    client, db_session, tenant, customer
):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    vigente = _promesa(db_session, tenant, inv, dias=3)
    cumplida = _promesa(db_session, tenant, inv, dias=-4)
    cumplida.fulfilled = True
    db_session.flush()

    assert client.post(f"/v1/promises/{vigente.id}/no-cumplio").status_code == 409
    assert client.post(f"/v1/promises/{cumplida.id}/no-cumplio").status_code == 409
    assert client.post("/v1/promises/no-existe/no-cumplio").status_code == 404
    assert "promesas_incumplidas" not in (tenant.config or {})


def test_si_despues_paga_la_promesa_incumplida_queda_cumplida(
    client, db_session, tenant, customer
):
    inv = _inv(db_session, tenant, customer, "M-1", 1000)
    promesa = _promesa(db_session, tenant, inv, dias=-4)
    client.post(f"/v1/promises/{promesa.id}/no-cumplio")

    assert client.post(f"/v1/invoices/{inv.id}/pay").status_code == 200

    assert promesa.fulfilled is True
    [p] = client.get("/v1/promises?status=fulfilled").json()
    assert p["incumplida"] is False
