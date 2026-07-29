"""Hardening del API: corrida diaria por cron protegida y trazas por request."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base
from aiuda_server.api.main import app, get_db


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


def test_corrida_manual_encola_y_corre(client, monkeypatch):
    """POST /v1/daily/run dispara la corrida AHORA (local: sin tokens de cron)."""
    corridas = {"n": 0}
    import aiuda_server.worker.main as worker

    monkeypatch.setattr(
        worker, "run_daily_blocking", lambda: corridas.__setitem__("n", corridas["n"] + 1)
    )
    res = client.post("/v1/daily/run")
    assert res.status_code == 202
    assert res.json()["status"] == "encolado"
    assert corridas["n"] == 1  # el background task efectivamente corrió


def test_request_id_en_cada_respuesta(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers.get("X-Request-Id")
