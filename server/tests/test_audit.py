"""AuditLog: el diferenciador "quién hizo qué" pasó de NUNCA escribirse a registrar
cada acción soberana, y se puede leer (solo admin)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server import audit as audit_mod
from aiuda_server.api.main import app, get_db
from aiuda_core.config import settings
from aiuda_core.models import AuditLog, Base, Tenant

pytest.importorskip("cryptography")

@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")


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
def demo_tenant(db_session):
    t = Tenant(
        name="Demo",
        owner_phone="52155",
        evolution_instance="demo",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño", "status": "activo"}]},
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_record_y_recent(db_session, demo_tenant):
    audit_mod.record(db_session, tenant_id=demo_tenant.id, action="x.do", entity_type="x")
    audit_mod.record(db_session, tenant_id=demo_tenant.id, action="y.do", entity_type="y")
    rows = audit_mod.recent(db_session, demo_tenant.id)
    assert [r.action for r in rows][:2] == ["y.do", "x.do"]  # más reciente primero


def test_guardar_proveedor_se_audita(client, demo_tenant, db_session, demo_login):
    demo_login(client)
    client.put("/v1/provider", json={"name": "claude", "mode": "api_key", "secret": "sk-x"})

    row = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "provider.update")
    )
    assert row is not None
    assert row.entity_type == "provider"
    # El secreto NUNCA entra a la bitácora.
    assert "sk-x" not in str(row.after)

    # Y se puede leer por el endpoint.
    log = client.get("/v1/audit").json()
    assert any(e["action"] == "provider.update" for e in log)
