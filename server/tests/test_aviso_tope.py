"""El aviso de tope de IA llega a una pantalla.

Antes `_aviso_tope` lo guardaba en la config y nadie lo leía: el tablero amanecía
vacío y el dueño no sabía por qué. El Centro de mando lo lee por
GET /v1/avisos/tope-ia y se puede descartar.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Tenant, UsageEvent
from aiuda_server.api.main import app, get_db
from aiuda_server.worker.main import _aviso_tope


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
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def demo_tenant(db_session):
    t = Tenant(name="Negocio", owner_phone="", evolution_instance="demo", config={"demo": True})
    db_session.add(t)
    db_session.flush()
    return t


def _gastar(db_session, tenant, tokens: int) -> None:
    db_session.add(
        UsageEvent(
            tenant_id=tenant.id, model="claude-test", task="t", input_tokens=tokens, output_tokens=0
        )
    )
    db_session.flush()


def test_sin_corte_no_hay_aviso(client, demo_tenant, demo_login):
    demo_login(client)
    assert client.get("/v1/avisos/tope-ia").json() == {"aviso": None}


def test_el_corte_deja_aviso_y_se_descarta(client, db_session, demo_tenant, demo_login):
    demo_login(client)
    demo_tenant.config = {**(demo_tenant.config or {}), "ia_tope_tokens_mes": 100}
    _gastar(db_session, demo_tenant, 150)
    _aviso_tope(db_session, demo_tenant, "Se alcanzó tu tope")
    db_session.flush()

    aviso = client.get("/v1/avisos/tope-ia").json()["aviso"]
    assert aviso and aviso["mes"] and aviso["desde"]

    assert client.post("/v1/avisos/tope-ia/descartar").status_code == 200
    assert client.get("/v1/avisos/tope-ia").json() == {"aviso": None}
    # Otro corte en el MISMO mes no lo resucita: ya lo leyó.
    _aviso_tope(db_session, demo_tenant, "Se alcanzó tu tope")
    assert client.get("/v1/avisos/tope-ia").json() == {"aviso": None}


def test_si_sube_el_tope_el_aviso_se_calla(client, db_session, demo_tenant, demo_login):
    demo_login(client)
    demo_tenant.config = {**(demo_tenant.config or {}), "ia_tope_tokens_mes": 100}
    _gastar(db_session, demo_tenant, 150)
    _aviso_tope(db_session, demo_tenant, "Se alcanzó tu tope")
    demo_tenant.config = {**demo_tenant.config, "ia_tope_tokens_mes": 10_000}
    db_session.flush()
    assert client.get("/v1/avisos/tope-ia").json() == {"aviso": None}
