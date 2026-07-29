"""Endpoint POST /v1/cobro/link: genera un link de pago con la pasarela conectada
del tenant (Mercado Pago / Clip / Conekta), en orden de preferencia. No cobra: solo
crea el link que el ayudante manda con el recordatorio.

El cliente de pasarela se arma de la credencial CIFRADA del tenant; aquí la clase
se sustituye por una fake para no tocar la red.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.connectors import credentials as cred
from aiuda_core.models import Base, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("cryptography")

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
def demo(db_session, client, demo_login):
    t = Tenant(
        name="Demo", owner_phone="52155", evolution_instance="demo",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño"}]},
    )
    db_session.add(t)
    db_session.flush()
    demo_login(client)
    return t


class _FakeMP:
    """Sustituye a MercadoPagoClient: registra lo que le piden y devuelve un link."""

    ultima = {}

    def __init__(self, **kwargs):
        _FakeMP.ultima["kwargs"] = kwargs

    def crear_link_pago(self, monto, concepto="", referencia=""):
        _FakeMP.ultima.update(monto=monto, concepto=concepto, referencia=referencia)
        return "https://mpago.la/PAGA123"


def test_sin_pasarela_conectada_da_409(client, demo):
    res = client.post("/v1/cobro/link", json={"monto": 500.0})
    assert res.status_code == 409
    assert "pasarela" in res.json()["detail"].lower()


def test_monto_no_positivo_da_400(client, demo):
    res = client.post("/v1/cobro/link", json={"monto": 0})
    assert res.status_code == 400


def test_con_mercadopago_conectado_genera_link(client, db_session, demo, monkeypatch):
    cred.set_credential(db_session, demo.id, "mercadopago", {"access_token": "APP_USR-x"})
    db_session.flush()
    import aiuda_core.connectors.mercadopago as mp

    monkeypatch.setattr(mp, "MercadoPagoClient", _FakeMP)
    res = client.post(
        "/v1/cobro/link",
        json={"monto": 1850.0, "concepto": "Factura F-1042", "referencia": "F-1042"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["proveedor"] == "mercadopago"
    assert body["link"] == "https://mpago.la/PAGA123"
    # La credencial cifrada llegó al constructor y el folio va como referencia.
    assert _FakeMP.ultima["kwargs"].get("access_token") == "APP_USR-x"
    assert _FakeMP.ultima["referencia"] == "F-1042"


def test_pasarela_caida_da_502(client, db_session, demo, monkeypatch):
    cred.set_credential(db_session, demo.id, "mercadopago", {"access_token": "APP_USR-x"})
    db_session.flush()
    import aiuda_core.connectors.mercadopago as mp

    class _Boom(_FakeMP):
        def crear_link_pago(self, *a, **k):
            raise RuntimeError("la pasarela no responde")

    monkeypatch.setattr(mp, "MercadoPagoClient", _Boom)
    res = client.post("/v1/cobro/link", json={"monto": 100.0})
    assert res.status_code == 502
