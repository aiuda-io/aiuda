"""WhatsApp sin terminal: instalar el conector con un clic, que el server sea
dueño del proceso de wacli y que las fallas lleguen en español.

Nada de aquí toca un WhatsApp de verdad: el binario es el wacli falso de
``wacli_falso/`` (mismo candado, mismos eventos) sobre un store temporal.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.connectors import wacli_bin
from aiuda_core.models import Base, Tenant
from aiuda_server.api.main import app, get_db

WACLI_FALSO = str(Path(__file__).parent / "wacli_falso" / "wacli")


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
def tenant(db_session):
    t = Tenant(name="Negocio", owner_phone="5215500000000", evolution_instance="inst-a", config={})
    db_session.add(t)
    db_session.flush()
    return t


# ---------- instalar con un clic ----------

def test_status_sin_conector_ofrece_instalar(client, tenant, monkeypatch):
    monkeypatch.setattr(wacli_bin, "puede_instalarse", lambda: None)
    r = client.get("/v1/integrations/whatsapp/status").json()
    assert r["connected"] is False
    assert r["instalado"] is False and r["no_se_puede"] is None


def test_status_en_mac_vieja_dice_por_que_no(client, tenant, monkeypatch):
    monkeypatch.setattr(wacli_bin, "_macos_mayor", lambda: 14)
    r = client.get("/v1/integrations/whatsapp/status").json()
    assert r["instalado"] is False
    assert "macOS 15" in r["no_se_puede"]


def test_instalar_deja_el_conector_listo(client, tenant, monkeypatch):
    def instalar():
        monkeypatch.setattr(settings, "wacli_bin", WACLI_FALSO)
        return WACLI_FALSO

    monkeypatch.setattr(wacli_bin, "instalar", instalar)
    r = client.post("/v1/integrations/whatsapp/instalar")
    assert r.status_code == 200
    assert r.json() == {"instalado": True, "version": "0.20.0", "no_se_puede": None}


def test_instalar_que_falla_responde_en_espanol(client, tenant, monkeypatch):
    def instalar():
        raise wacli_bin.WacliInstallError(wacli_bin.DESCARGA_FALLO)

    monkeypatch.setattr(wacli_bin, "instalar", instalar)
    r = client.post("/v1/integrations/whatsapp/instalar")
    assert r.status_code == 502
    assert "Revisa tu internet" in r.json()["detail"]


def test_qr_sin_conector_pide_instalarlo(client, tenant):
    r = client.post("/v1/integrations/whatsapp/qr")
    assert r.status_code == 409
    assert "presiona Instalar" in r.json()["detail"]
