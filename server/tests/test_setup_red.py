"""Buscar una IA en la red local desde el asistente."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.engine import red
from aiuda_core.models import Base
from aiuda_server.api.main import app, get_db


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()
    session.close()


def test_buscar_devuelve_lo_encontrado_con_aviso_honesto(client, monkeypatch):
    hallazgo = red.ServidorIA(
        ip="192.168.1.10", puerto=11434, equipo="Mac de la oficina",
        base_url="http://192.168.1.10:11434/v1", programa="Ollama",
        modelos=["llama3.1:8b"],
    )
    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.5")
    monkeypatch.setattr(red, "buscar", lambda: [hallazgo])

    body = client.post("/v1/setup/red/buscar").json()
    assert body["mi_ip"] == "192.168.1.5"
    assert body["encontrados"][0]["equipo"] == "Mac de la oficina"
    assert body["encontrados"][0]["base_url"] == "http://192.168.1.10:11434/v1"
    # El dueño debe saber que sus datos salen de esta computadora.
    assert "viaja" in body["aviso"]


def test_sin_red_lo_dice_en_vez_de_fallar(client, monkeypatch):
    monkeypatch.setattr(red, "ip_local", lambda: None)
    body = client.post("/v1/setup/red/buscar").json()
    assert body["encontrados"] == [] and "no está en una red" in body["aviso"]


def test_red_vacia_no_inventa_resultados(client, monkeypatch):
    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.5")
    monkeypatch.setattr(red, "buscar", lambda: [])
    body = client.post("/v1/setup/red/buscar").json()
    assert body["encontrados"] == []
