"""Importar estados de cuenta por API: analizar (previa, sin escribir) e
importar (los depósitos aprobados entran a conciliación con procedencia).

Los PDFs son sintéticos (core/tests/pdf_sintetico.py): misma geometría que los
estados reales contra los que se verificó el parser, datos inventados."""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server.api.main import app, get_db
from aiuda_core.models import AuditLog, Base, Payment, Tenant

# El generador de PDFs sintéticos vive con los tests del core (no es código de
# producto); se importa directo de esa carpeta.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "core" / "tests"))
from pdf_sintetico import MOVS_BANORTE, estado_banorte, estado_generico  # noqa: E402

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


def _analizar(client, pdf: bytes, nombre="marzo.pdf"):
    return client.post(
        "/v1/banco/analizar",
        headers=HEADERS,
        files={"file": (nombre, pdf, "application/pdf")},
    )


def test_analizar_banorte_devuelve_previa_sin_escribir(client, db_session, tenant):
    res = _analizar(client, estado_banorte(MOVS_BANORTE, 10000.00))
    assert res.status_code == 200
    previa = res.json()
    assert previa["banco"] == "Banorte"
    assert previa["metodo"] == "banorte"
    assert previa["cuadra"] is True
    assert previa["depositos"] == {"n": 3, "total": 20200.00}
    assert previa["retiros"]["n"] == 2
    assert len(previa["movimientos"]) == 5
    assert previa["periodo"] == "marzo 2026"
    # Analizar NO importa: la bandeja sigue vacía (HITL: primero la previa).
    assert db_session.scalars(select(Payment)).all() == []


def test_importar_lo_aprobado_entra_a_conciliacion(client, db_session, tenant):
    previa = _analizar(client, estado_banorte(MOVS_BANORTE, 10000.00)).json()
    res = client.post("/v1/banco/importar", headers=HEADERS, json=previa)
    assert res.status_code == 200
    assert res.json()["creados"] == 3
    assert res.json()["cargos_ignorados"] == 2

    # Los depósitos quedan en la bandeja de Diego, con procedencia visible.
    bandeja = client.get("/v1/reconciliation", headers=HEADERS).json()
    assert bandeja["count"] == 3
    pago = bandeja["pending"][0]
    assert pago["source"] == "banco"
    assert pago["origen"] == "de tu estado de cuenta de Banorte, marzo 2026"

    # Y queda rastro en la bitácora de lo soberano.
    log = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "banco.importar_estado")
    )
    assert log is not None
    assert log.after["creados"] == 3

    # Re-importar el mismo estado no duplica (dedup fecha + monto + referencia).
    res2 = client.post("/v1/banco/importar", headers=HEADERS, json=previa)
    assert res2.status_code == 200
    assert res2.json()["creados"] == 0
    assert res2.json()["omitidos"] == 3
    assert len(db_session.scalars(select(Payment)).all()) == 3


def test_importar_un_estado_que_no_cuadra_se_rechaza(client, db_session, tenant):
    previa = _analizar(client, estado_banorte(MOVS_BANORTE, 10000.00)).json()
    previa["saldo_final"] = 99999.99  # manipulado: ya no cuadra
    res = client.post("/v1/banco/importar", headers=HEADERS, json=previa)
    assert res.status_code == 409
    assert "No importo nada a ciegas" in res.json()["detail"]
    assert db_session.scalars(select(Payment)).all() == []


def test_banco_desconocido_usa_la_ia_del_dueno(client, db_session, tenant, monkeypatch):
    import json as _json

    import aiuda_server.metering as metering

    class RunnerFijo:
        def model_for(self, role):
            return "fake"

        def complete(self, system, user, *, task, model=None, role="redaccion", max_tokens=1024):
            assert task == "leer_estado_cuenta"
            return _json.dumps(
                {
                    "banco": "Banco Regional del Golfo",
                    "moneda": "MXN",
                    "periodo_inicio": "2026-03-01",
                    "periodo_fin": "2026-03-31",
                    "saldo_inicial": 7000.00,
                    "saldo_final": 17650.00,
                    "movimientos": [
                        {"fecha": "2026-03-04", "concepto": "DEPOSITO CLIENTE FACTURA F-77",
                         "referencia": "", "cargo": None, "abono": 12500.00},
                        {"fecha": "2026-03-09", "concepto": "RETIRO PAGO NOMINA",
                         "referencia": "", "cargo": 6200.00, "abono": None},
                        {"fecha": "2026-03-16", "concepto": "DEPOSITO CLIENTE FACTURA F-81",
                         "referencia": "", "cargo": None, "abono": 4350.00},
                    ],
                }
            )

    monkeypatch.setattr(metering, "tenant_runner", lambda db, t: RunnerFijo())
    movs = [
        ("2026-03-04", "DEPOSITO CLIENTE FACTURA F-77", None, 12500.00),
        ("2026-03-09", "RETIRO PAGO NOMINA", 6200.00, None),
        ("2026-03-16", "DEPOSITO CLIENTE FACTURA F-81", None, 4350.00),
    ]
    res = _analizar(client, estado_generico(movs, 7000.00), nombre="golfo.pdf")
    assert res.status_code == 200
    previa = res.json()
    assert previa["metodo"] == "ia"
    assert previa["cuadra"] is True
    assert previa["depositos"]["n"] == 2

    res = client.post("/v1/banco/importar", headers=HEADERS, json=previa)
    assert res.status_code == 200
    assert res.json()["creados"] == 2


def test_pdf_escaneado_da_mensaje_claro(client, db_session, tenant):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "core" / "tests"))
    from pdf_sintetico import construir_pdf

    res = _analizar(client, construir_pdf([[]]), nombre="escaneado.pdf")
    assert res.status_code == 422
    assert "escaneado" in res.json()["detail"]


def test_basura_no_tumba_el_endpoint(client, db_session, tenant):
    res = _analizar(client, b"no soy un pdf", nombre="cosa.pdf")
    assert res.status_code == 422
    assert db_session.scalars(select(Payment)).all() == []
