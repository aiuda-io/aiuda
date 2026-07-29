"""Guardia local estilo Jupyter: AIUDA_SESSION_TOKEN protege el API aunque otro
proceso local intente hablarle. Sin token configurado (dev/tests) no estorba."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.models import Base
from aiuda_server.api.main import SESSION_COOKIE_LOCAL, app, get_db


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()
    session.close()


def test_sin_token_configurado_no_estorba(client, monkeypatch):
    monkeypatch.setattr(settings, "session_token", "")
    assert client.get("/v1/workspace").status_code == 200


def test_con_token_exige_credencial(client, monkeypatch):
    monkeypatch.setattr(settings, "session_token", "t0ken-secreto")
    res = client.get("/v1/workspace")
    assert res.status_code == 401
    assert "aiuda start" in res.json()["detail"]
    # /health queda exento (diagnóstico sin fricción).
    assert client.get("/health").status_code == 200


def test_query_token_canjea_cookie_y_la_cookie_basta(client, monkeypatch):
    monkeypatch.setattr(settings, "session_token", "t0ken-secreto")
    res = client.get("/v1/workspace?token=t0ken-secreto")
    assert res.status_code == 200
    assert client.cookies.get(SESSION_COOKIE_LOCAL) == "t0ken-secreto"
    # Siguiente petición: solo cookie, sin query.
    assert client.get("/v1/workspace").status_code == 200


def test_token_incorrecto_rechazado(client, monkeypatch):
    monkeypatch.setattr(settings, "session_token", "t0ken-secreto")
    assert client.get("/v1/workspace?token=malo").status_code == 401
    client.cookies.set(SESSION_COOKIE_LOCAL, "malo")
    assert client.get("/v1/workspace").status_code == 401


def test_navegador_recibe_pagina_amable_no_json(client, monkeypatch):
    """Una persona que llega sin llave merece una explicación, no un JSON."""
    monkeypatch.setattr(settings, "session_token", "t0ken-secreto")
    res = client.get("/", headers={"Accept": "text/html"})
    assert res.status_code == 401
    assert "text/html" in res.headers["content-type"]
    assert "llave de tu sesión" in res.text
    assert "detail" not in res.text
