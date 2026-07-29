"""Bandeja unificada de conversaciones sobre la tabla Conversation (lo que llena el webhook,
la única verdad de entrantes). Clasifica identificado / por_identificar / descartado por
match_key, y permite descartar, deshacer y registrar a un desconocido como cliente. No toca
wacli: prueba la coherencia de identidad, que es lo que antes vivía en dos mundos separados."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Conversation, Customer, Message, Tenant
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
def data(db_session):
    t = Tenant(
        name="Demo SA", owner_phone="5215512345678",
        evolution_instance="demo", config={"api_key": "k-demo"},
    )
    db_session.add(t)
    db_session.flush()
    # Cliente conocido en formato distinto al de la conversación: debe cruzar por match_key.
    db_session.add(Customer(tenant_id=t.id, name="Aitana", phone="+52 229 542 3903"))
    ident = Conversation(tenant_id=t.id, remote_phone="5212295423903")  # cruza al conocido
    desco = Conversation(tenant_id=t.id, remote_phone="5215512345678")  # desconocido
    db_session.add_all([ident, desco])
    db_session.flush()
    db_session.add(
        Message(tenant_id=t.id, conversation_id=ident.id, direction="in", author="agent", body="hola")
    )
    db_session.flush()
    return {"ident": ident.id, "desco": desco.id}


def _rows(client):
    return {r["id"]: r for r in client.get("/v1/conversations", headers=HEADERS).json()}


def test_bandeja_clasifica_identificado_y_por_identificar(client, data):
    rows = _rows(client)
    assert rows[data["ident"]]["status"] == "identificado"
    assert rows[data["ident"]]["customer"] == "Aitana"
    assert rows[data["ident"]]["customer_id"] is not None
    assert rows[data["desco"]]["status"] == "por_identificar"
    assert rows[data["desco"]]["customer"] is None


def test_descartar_y_deshacer(client, data):
    cid = data["desco"]
    assert client.post(f"/v1/conversations/{cid}/dismiss", headers=HEADERS).json()["status"] == "descartado"
    assert _rows(client)[cid]["status"] == "descartado"
    assert (
        client.post(f"/v1/conversations/{cid}/undismiss", headers=HEADERS).json()["status"]
        == "por_identificar"
    )
    assert _rows(client)[cid]["status"] == "por_identificar"


def test_registrar_cliente_desde_conversacion(client, data):
    cid = data["desco"]
    res = client.post(
        f"/v1/conversations/{cid}/registrar-cliente", headers=HEADERS, json={"name": "Beto"}
    )
    assert res.status_code == 200 and res.json()["created"] is True
    # Ya cruza sola: la conversación queda identificada con el cliente recién creado.
    row = _rows(client)[cid]
    assert row["status"] == "identificado"
    assert row["customer"] == "Beto"


def test_registrar_sin_nombre_ni_liga_falla(client, data):
    # Sin nombre y sin ligar: 422. Antes volcaba el teléfono como nombre y ensuciaba Clientes
    # con "clientes" que eran solo un número por identificar.
    cid = data["desco"]
    res = client.post(f"/v1/conversations/{cid}/registrar-cliente", headers=HEADERS, json={})
    assert res.status_code == 422
    assert _rows(client)[cid]["status"] == "por_identificar"  # sigue sin identificar


def test_ligar_conversacion_a_cliente_existente(client, data, db_session):
    # Ligar a un cliente que ya existe: su WhatsApp pasa a ser este número y la conversación
    # cruza a él, sin crear un cliente nuevo.
    from sqlalchemy import select

    cid = data["desco"]
    aitana = db_session.scalar(select(Customer).where(Customer.name == "Aitana"))
    res = client.post(
        f"/v1/conversations/{cid}/registrar-cliente",
        headers=HEADERS,
        json={"link_customer_id": aitana.id},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["created"] is False and body.get("linked") is True and body["name"] == "Aitana"
    row = _rows(client)[cid]
    assert row["status"] == "identificado" and row["customer"] == "Aitana"
