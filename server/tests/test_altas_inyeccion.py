"""Altas directas + inyección: aiuda captura y el registro viaja al maestro ELEGIDO.

El pivote de producto: aiuda NO es el sistema maestro — es capaz de INYECTAR a los
maestros. Estos tests fijan el contrato HTTP: alta honesta (source="aiuda" /
presence vacío), validaciones de dominio (folio/teléfono únicos → 409), pago manual
que entra a conciliación, destinos disponibles derivados de credenciales reales, y
el check "crear también en..." encolando al outbox.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server.api.main import app, get_db
from aiuda_core.models import Base, Customer, Invoice, OutboxEntry, Payment, Tenant

# El alta rechaza una factura que vence antes de emitirse, y si no mandas issued_date
# la emisión es HOY. Con fechas clavadas, estos tests aprobaban hasta que el calendario
# las alcanzaba y luego fallaban solos. Relativas a hoy, no caducan.
VENCE = (date.today() + timedelta(days=30)).isoformat()
VENCE_ANTES_DE_EMITIRSE = (date.today() + timedelta(days=40)).isoformat()

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
def client(db_session, monkeypatch):
    # El drenado del outbox corre en background con su propia sesión; aquí se
    # apaga (los tests del drenado viven en core/tests/test_writeback.py).
    import aiuda_server.worker.main as worker_main

    monkeypatch.setattr(worker_main, "process_writebacks_blocking", lambda tenant_id: None)
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant(db_session):
    t = Tenant(
        name="Demo",
        owner_phone="5215512345678",
        evolution_instance="demo-altas",
        config={"demo": True, "members": []},
    )
    db_session.add(t)
    db_session.flush()
    return t


# El login demo por endpoint se retiró (commit "Quita el demo por completo"):
# los tests autentican con el fixture demo_login del conftest (cookie directa).


# --------------------------------------------------------------------------- #
# Altas directas: procedencia honesta y reglas de dominio                      #
# --------------------------------------------------------------------------- #
def test_alta_de_cliente_nativo_con_telefono_normalizado(client, db_session, tenant, demo_login):
    demo_login(client)
    res = client.post(
        "/v1/customers",
        json={"name": "Refacciones Norte", "phone": "55 3333 0044", "email": "rn@x.mx"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["phone"] == "5215533330044"  # 10 dígitos -> 521 canónico
    cust = db_session.get(Customer, data["id"])
    assert cust.presence == {}  # nativo de aiuda: sin presencia, sin mentir fuente
    assert data["inyeccion"] is None  # sin check, no viaja a ningún lado


def test_telefono_repetido_409_nombrando_al_dueno(client, db_session, tenant, demo_login):
    demo_login(client)
    client.post("/v1/customers", json={"name": "Uno", "phone": "5511110001"})
    res = client.post("/v1/customers", json={"name": "Dos", "phone": "55 1111 0001"})
    assert res.status_code == 409
    assert "Uno" in res.json()["detail"]


def test_alta_de_producto_lleva_source_aiuda_y_sku_unico(client, db_session, tenant, demo_login):
    demo_login(client)
    res = client.post("/v1/products", json={"name": "Tornillo", "sku": "T-1", "price": 12.5})
    assert res.status_code == 201
    from aiuda_core.models import Product

    prod = db_session.get(Product, res.json()["id"])
    assert prod.source == "aiuda"  # procedencia honesta: nació aquí, no en un Excel
    res = client.post("/v1/products", json={"name": "Otro", "sku": "T-1"})
    assert res.status_code == 409


def test_alta_de_factura_valida_folio_unico_y_fechas(client, db_session, tenant, demo_login):
    demo_login(client)
    cid = client.post("/v1/customers", json={"name": "Ferretería"}).json()["id"]
    res = client.post(
        "/v1/invoices",
        json={"customer_id": cid, "folio": "A-1", "amount": 1500.0, "due_date": VENCE},
    )
    assert res.status_code == 201
    inv = db_session.get(Invoice, res.json()["id"])
    assert inv.source == "aiuda" and inv.status == "open"

    assert client.post(
        "/v1/invoices",
        json={"customer_id": cid, "folio": "A-1", "amount": 3, "due_date": VENCE},
    ).status_code == 409  # folio único
    assert client.post(
        "/v1/invoices",
        json={
            "customer_id": cid, "folio": "A-2", "amount": 3,
            "issued_date": VENCE_ANTES_DE_EMITIRSE, "due_date": VENCE,
        },
    ).status_code == 422  # vence antes de emitirse
    assert client.post(
        "/v1/invoices",
        json={"customer_id": "no-existe", "folio": "A-3", "amount": 3, "due_date": VENCE},
    ).status_code == 404


def test_alta_de_cita_source_aiuda(client, db_session, tenant, demo_login):
    demo_login(client)
    res = client.post(
        "/v1/appointments",
        json={"title": "Revisión anual", "starts_at": "2026-07-15T10:00:00"},
    )
    assert res.status_code == 201
    from aiuda_core.models import Appointment

    cita = db_session.get(Appointment, res.json()["id"])
    assert cita.source == "aiuda"


def test_pago_manual_entra_a_conciliacion_no_cierra_nada(client, db_session, tenant, demo_login):
    """El pago a mano es un Payment pendiente: Diego propone y el humano confirma
    por el flujo normal (un alta de pago no cierra facturas sola)."""
    demo_login(client)
    cid = client.post("/v1/customers", json={"name": "Ferretería"}).json()["id"]
    inv_id = client.post(
        "/v1/invoices",
        json={"customer_id": cid, "folio": "B-1", "amount": 900.0, "due_date": VENCE},
    ).json()["id"]

    res = client.post(
        "/v1/payments",
        json={"amount": 900.0, "reference": "SPEI 123", "invoice_id": inv_id},
    )
    assert res.status_code == 201
    pago = db_session.get(Payment, res.json()["id"])
    assert pago.source == "manual" and pago.status == "pendiente"
    assert pago.invoice_id is None  # se fija al CONCILIAR, no al capturar
    inv = db_session.get(Invoice, inv_id)
    assert inv.status == "open"  # nada se cerró solo
    # Y Diego ya lo ve en su bandeja con propuesta (monto exacto).
    bandeja = client.get("/v1/reconciliation").json()
    assert bandeja["count"] == 1
    assert bandeja["pending"][0]["proposal"]["folio"] == "B-1"


# --------------------------------------------------------------------------- #
# Inyección: destinos reales y encolado explícito                              #
# --------------------------------------------------------------------------- #
def test_destinos_derivan_de_credenciales_y_recetas_con_escritura(client, db_session, tenant, demo_login):
    demo_login(client)
    destinos = client.get("/v1/inyectar/destinos").json()
    assert destinos["cliente"] == []  # sin Odoo ni conexiones: honesto, nada que ofrecer

    tenant.config = {
        **(tenant.config or {}),
        "custom_sources": [
            {"id": "cx1", "name": "Mi ERP", "cap": "directorio_clientes", "write_path": "clientes"},
            {"id": "cx2", "name": "Solo lectura", "cap": "directorio_clientes"},
        ],
    }
    db_session.flush()
    destinos = client.get("/v1/inyectar/destinos").json()
    assert destinos["cliente"] == [
        {"target": "custom", "conexion_id": "cx1", "label": "Mi ERP"}
    ]  # la conexión sin write_path NO se ofrece


def test_check_al_crear_encola_el_alta_al_destino(client, db_session, tenant, demo_login):
    demo_login(client)
    tenant.config = {
        **(tenant.config or {}),
        "custom_sources": [
            {"id": "cx1", "name": "Mi ERP", "cap": "directorio_clientes", "write_path": "clientes"},
        ],
    }
    db_session.flush()
    res = client.post(
        "/v1/customers",
        json={"name": "Nuevo", "inyectar_a": "custom", "conexion_id": "cx1"},
    )
    assert res.status_code == 201
    assert res.json()["inyeccion"]["status"] == "encolada"
    entry = db_session.scalar(select(OutboxEntry).where(OutboxEntry.tenant_id == tenant.id))
    assert entry.action == "crear_cliente" and entry.target == "custom"
    assert entry.payload["conexion"] == {"id": "cx1", "pkey": "Mi ERP"}


def test_inyectar_despues_desde_la_ficha(client, db_session, tenant, demo_login):
    demo_login(client)
    cid = client.post("/v1/customers", json={"name": "Tardío"}).json()["id"]
    tenant.config = {
        **(tenant.config or {}),
        "custom_sources": [
            {"id": "cx1", "name": "Mi ERP", "cap": "directorio_clientes", "write_path": "clientes"},
        ],
    }
    db_session.flush()
    res = client.post(
        "/v1/inyectar",
        json={"entidad": "cliente", "id": cid, "target": "custom", "conexion_id": "cx1"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "encolada"
    # Repetir hacia el mismo destino cuando YA vive allá: 409 legible.
    cust = db_session.get(Customer, cid)
    cust.presence = {"Mi ERP": {"ref": "9"}}
    db_session.flush()
    res = client.post(
        "/v1/inyectar",
        json={"entidad": "cliente", "id": cid, "target": "custom", "conexion_id": "cx1"},
    )
    assert res.status_code == 409
    assert "ya vive" in res.json()["detail"]


def test_inyectar_a_conexion_sin_escritura_422_honesto(client, db_session, tenant, demo_login):
    demo_login(client)
    cid = client.post("/v1/customers", json={"name": "X"}).json()["id"]
    tenant.config = {
        **(tenant.config or {}),
        "custom_sources": [{"id": "cx2", "name": "Solo lectura", "cap": "directorio_clientes"}],
    }
    db_session.flush()
    res = client.post(
        "/v1/inyectar",
        json={"entidad": "cliente", "id": cid, "target": "custom", "conexion_id": "cx2"},
    )
    assert res.status_code == 422
    assert "escritura" in res.json()["detail"]
