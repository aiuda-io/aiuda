"""Buscador global: cobertura por entidad (clientes, prospectos, facturas,
productos, conexiones a la medida), deep-links a la ficha y aislamiento por
tenant. Antes no tenía ni un test; el contrato es el que consume ⌘K."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Customer, Invoice, Product, Tenant
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
        config={
            "api_key": "k-demo",
            "custom_sources": [
                {"id": "cs1", "name": "Mi ERP de escritorio", "cap": "clientes"},
            ],
        },
    )
    db_session.add(t)
    db_session.flush()
    return t


def _grupo(data: dict, titulo: str) -> dict | None:
    return next((g for g in data["groups"] if g["title"] == titulo), None)


def test_query_corta_no_busca(client, tenant):
    res = client.get("/v1/search?q=a", headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {"groups": []}


def test_clientes_deep_link_a_su_ficha(client, db_session, tenant):
    c = Customer(tenant_id=tenant.id, name="Abarrotes Don Pepe", phone="5215511111111")
    db_session.add(c)
    db_session.flush()

    data = client.get("/v1/search?q=abarrotes", headers=HEADERS).json()
    grupo = _grupo(data, "Clientes")
    assert grupo is not None
    assert grupo["items"][0]["href"] == f"/clientes/{c.id}"


def test_prospectos_en_su_grupo_no_en_clientes(client, db_session, tenant):
    db_session.add(
        Customer(
            tenant_id=tenant.id,
            name="Ferretería Prospecto",
            phone=None,
            kind="prospecto",
            meta={"origen": "denue", "municipio": "Monterrey"},
        )
    )
    db_session.flush()

    data = client.get("/v1/search?q=ferreter", headers=HEADERS).json()
    assert _grupo(data, "Clientes") is None  # no se cuela en Clientes
    grupo = _grupo(data, "Prospectos")
    assert grupo is not None
    assert grupo["items"][0]["href"] == "/prospectos"
    assert grupo["items"][0]["sublabel"] == "Monterrey"  # sin teléfono: dice dónde está


def test_facturas_deep_link_a_su_ficha(client, db_session, tenant):
    c = Customer(tenant_id=tenant.id, name="Cliente Uno", phone="5215522222222")
    db_session.add(c)
    db_session.flush()
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=c.id,
        folio="F-100",
        amount=4500,
        status="open",
        issued_date=date(2026, 6, 1),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    db_session.flush()

    data = client.get("/v1/search?q=F-100", headers=HEADERS).json()
    grupo = _grupo(data, "Facturas")
    assert grupo is not None
    assert grupo["items"][0]["href"] == f"/facturas/{inv.id}"


def test_productos_por_nombre_y_sku(client, db_session, tenant):
    db_session.add(
        Product(tenant_id=tenant.id, name="Varilla 3/8", sku="VAR-38", source="excel")
    )
    db_session.flush()

    por_nombre = client.get("/v1/search?q=varilla", headers=HEADERS).json()
    assert _grupo(por_nombre, "Productos") is not None

    por_sku = client.get("/v1/search?q=VAR-38", headers=HEADERS).json()
    grupo = _grupo(por_sku, "Productos")
    assert grupo["items"][0] == {"label": "Varilla 3/8", "sublabel": "VAR-38", "href": "/productos"}


def test_conexiones_a_la_medida_por_nombre(client, tenant):
    data = client.get("/v1/search?q=escritorio", headers=HEADERS).json()
    grupo = _grupo(data, "Conexiones a la medida")
    assert grupo is not None
    assert grupo["items"][0]["label"] == "Mi ERP de escritorio"
    assert grupo["items"][0]["href"] == "/integraciones"


def test_no_cruza_tenants(client, db_session, tenant):
    otro = Tenant(
        name="Otro SA",
        owner_phone="5215599999999",
        evolution_instance="otro",
        config={"api_key": "k-otro"},
    )
    db_session.add(otro)
    db_session.flush()
    db_session.add(Customer(tenant_id=otro.id, name="Cliente Ajeno", phone="5215533333333"))
    db_session.flush()

    data = client.get("/v1/search?q=ajeno", headers=HEADERS).json()
    assert data == {"groups": []}
