"""Conexión de OpenAI por OAuth (Sign in with ChatGPT) en el panel de proveedor.

Se mockea el módulo codex (no se toca la red ni ~/.codex): se prueba que el endpoint ingiere
la sesión, verifica con una llamada REAL antes de guardar, persiste la credencial cifrada
(name=codex, mode=subscription), y que la vía de pegar-secreto rechaza codex."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.engine import codex as codex_mod
from aiuda_core.models import Base, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("cryptography")

@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    t = Tenant(
        name="Taquería Demo",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={"demo": True, "members": [{"name": "Demo", "email": "demo@aiuda.mx", "role": "dueño", "status": "activo"}]},
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_connect_openai_ingiere_sesion_y_guarda_credencial(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(codex_mod, "read_tokens", lambda path=None: {"access_token": "a", "account_id": "acct-9", "refresh_token": "r"})
    monkeypatch.setattr(codex_mod, "test_codex", lambda *a, **k: {"ok": True, "mode": "subscription", "model": "gpt-5.5", "latency_ms": 42})

    res = client.post("/v1/provider/openai/connect")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "codex" and body["mode"] == "subscription" and body["connected"] is True
    assert body["test"]["ok"] is True

    # La credencial quedó guardada y el panel la muestra conectada.
    state = client.get("/v1/provider").json()
    assert state["name"] == "codex" and state["mode"] == "subscription" and state["connected"] is True


def test_connect_openai_no_guarda_si_la_prueba_real_falla(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(codex_mod, "read_tokens", lambda path=None: {"access_token": "a", "account_id": "x", "refresh_token": "r"})
    monkeypatch.setattr(codex_mod, "test_codex", lambda *a, **k: {"ok": False, "code": "auth", "error": "no autorizó"})

    res = client.post("/v1/provider/openai/connect")
    assert res.status_code == 502
    # No se guardó nada: el panel sigue sin conectar.
    assert client.get("/v1/provider").json()["connected"] is False


def test_connect_openai_sin_sesion_ni_pegado_da_409(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    # Sin sesión local (self-host) y sin nada pegado: 409 honesto. Ya NO se corre `codex
    # login` en el servidor (mutaba un archivo global compartido entre tenants).
    monkeypatch.setattr(codex_mod, "read_tokens", lambda path=None: None)

    res = client.post("/v1/provider/openai/connect")
    assert res.status_code == 409
    assert "codex login" in res.json()["detail"]


def test_connect_openai_con_bundle_pegado_guarda_cifrado_por_tenant(
    client, db_session, demo_tenant, demo_login, monkeypatch
):
    """La fuga cerrada: el dueño pega SU auth.json (capturado en su máquina); NO se lee el
    archivo global del servidor. El bundle COMPLETO (access + refresh) queda cifrado en la
    fila del tenant — el runner autentica con eso, no con ~/.codex/auth.json compartido."""
    demo_login(client)
    import json as _json

    from aiuda_core.connectors import credentials as cred

    # No hay sesión local en la máquina; el dueño pega su auth.json.
    monkeypatch.setattr(codex_mod, "read_tokens", lambda path=None: None)
    seen = {}

    def _fake_test(runner=None):
        # Prueba con el bundle DE ESTE TENANT, no el archivo global.
        seen["tokens"] = getattr(runner, "_tokens", None)
        return {"ok": True, "mode": "subscription", "model": "gpt-5.5", "latency_ms": 5}

    monkeypatch.setattr(codex_mod, "test_codex", _fake_test)

    auth = '{"tokens": {"access_token": "acc-tenant", "refresh_token": "ref-tenant", "account_id": "acct-1"}}'
    res = client.post("/v1/provider/openai/connect", json={"auth_json": auth})
    assert res.status_code == 200, res.text
    # Se verificó con el bundle del tenant.
    assert seen["tokens"]["access_token"] == "acc-tenant"
    # Y quedó guardado CIFRADO por tenant, bundle completo (no solo el account_id cosmético).
    stored = cred.read_stored(db_session, demo_tenant.id, "ia")
    bundle = _json.loads(stored["secret"])
    assert bundle["access_token"] == "acc-tenant"
    assert bundle["refresh_token"] == "ref-tenant"
    assert bundle["account_id"] == "acct-1"


def test_guardar_proveedor_rechaza_codex_por_pegado(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put("/v1/provider", json={"name": "codex", "mode": "subscription", "secret": "x"})
    assert res.status_code == 400
    assert "ChatGPT" in res.json()["detail"]


# --- device code: "Iniciar sesion con ChatGPT" sin pegar nada ----------------
def test_device_start_devuelve_codigo_y_url(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(
        codex_mod,
        "device_start",
        lambda *a, **k: {
            "device_code": "dev-1",
            "user_code": "ABCD-1234",
            "verification_uri": "https://auth.openai.com/codex/device",
            "interval": 5,
            "expires_in": 900,
        },
    )
    res = client.post("/v1/provider/openai/device/start")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["device_code"] == "dev-1" and body["user_code"] == "ABCD-1234"
    assert body["verification_uri"].endswith("/codex/device")


def test_device_poll_pending_no_guarda(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(codex_mod, "device_poll", lambda *a, **k: {"status": "pending"})
    res = client.post("/v1/provider/openai/device/poll", json={"device_code": "dev-1", "user_code": "ABCD-1234"})
    assert res.status_code == 200
    assert res.json() == {"status": "pending"}
    assert client.get("/v1/provider").json()["connected"] is False


def test_device_poll_success_verifica_y_guarda_cifrado(client, db_session, demo_tenant, demo_login, monkeypatch):
    """start -> poll pending -> poll success -> verify -> save: al autorizar, canjea el bundle,
    lo PRUEBA con una llamada real (mismo camino del motor) y lo guarda CIFRADO por tenant."""
    demo_login(client)
    import json as _json

    from aiuda_core.connectors import credentials as cred

    monkeypatch.setattr(
        codex_mod,
        "device_poll",
        lambda *a, **k: {
            "status": "success",
            "bundle": {"access_token": "acc-d", "refresh_token": "ref-d", "account_id": "acct-d"},
        },
    )
    seen = {}

    def _fake_test(runner=None):
        # Se verifica con el bundle DEL device code, no el archivo global.
        seen["tokens"] = getattr(runner, "_tokens", None)
        return {"ok": True, "mode": "subscription", "model": "gpt-5.5", "latency_ms": 7}

    monkeypatch.setattr(codex_mod, "test_codex", _fake_test)

    res = client.post("/v1/provider/openai/device/poll", json={"device_code": "dev-1", "user_code": "ABCD-1234"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success" and body["connected"] is True
    assert body["test"]["ok"] is True
    assert seen["tokens"]["access_token"] == "acc-d"

    # Guardado CIFRADO por tenant, bundle completo.
    stored = cred.read_stored(db_session, demo_tenant.id, "ia")
    bundle = _json.loads(stored["secret"])
    assert bundle == {"access_token": "acc-d", "refresh_token": "ref-d", "account_id": "acct-d"}

    state = client.get("/v1/provider").json()
    assert state["name"] == "codex" and state["mode"] == "subscription" and state["connected"] is True


def test_device_poll_no_guarda_si_prueba_real_falla(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(
        codex_mod,
        "device_poll",
        lambda *a, **k: {"status": "success", "bundle": {"access_token": "a", "refresh_token": "r", "account_id": "x"}},
    )
    monkeypatch.setattr(codex_mod, "test_codex", lambda *a, **k: {"ok": False, "code": "auth", "error": "no autorizó"})
    res = client.post("/v1/provider/openai/device/poll", json={"device_code": "dev-1", "user_code": "ABCD-1234"})
    assert res.status_code == 200
    assert res.json()["status"] == "error"
    assert client.get("/v1/provider").json()["connected"] is False


def test_device_poll_propaga_error_del_backend(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    monkeypatch.setattr(codex_mod, "device_poll", lambda *a, **k: {"status": "error", "error": "OpenAI respondió 500 al autorizar."})
    res = client.post("/v1/provider/openai/device/poll", json={"device_code": "dev-1", "user_code": "x"})
    assert res.status_code == 200
    assert res.json()["status"] == "error" and "500" in res.json()["detail"]


def test_device_poll_sin_codigo_da_400(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.post("/v1/provider/openai/device/poll", json={"device_code": "", "user_code": ""})
    assert res.status_code == 400


# --- API KEY de OpenAI (sk-...), simetrica a la de Claude --------------------
def test_openai_api_key_se_guarda_por_put_provider(client, db_session, demo_tenant, demo_login):
    demo_login(client)
    from aiuda_core.connectors import credentials as cred

    res = client.put("/v1/provider", json={"name": "codex", "mode": "api_key", "secret": "sk-openai-123"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "codex" and body["mode"] == "api_key" and body["connected"] is True

    stored = cred.read_stored(db_session, demo_tenant.id, "ia")
    assert stored["name"] == "codex" and stored["mode"] == "api_key" and stored["secret"] == "sk-openai-123"

    state = client.get("/v1/provider").json()
    assert state["name"] == "codex" and state["mode"] == "api_key" and state["connected"] is True


def test_probar_conexion_codex_api_key_ramifica_a_make_runner(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    client.put("/v1/provider", json={"name": "codex", "mode": "api_key", "secret": "sk-x"})
    monkeypatch.setattr(
        codex_mod, "test_codex", lambda *a, **k: {"ok": True, "mode": "api_key", "model": "gpt-5.5", "latency_ms": 3}
    )
    res = client.post("/v1/provider/test")
    assert res.status_code == 200
    assert res.json()["ok"] is True and res.json()["mode"] == "api_key"


def test_probar_conexion_ramifica_a_codex(client, demo_tenant, demo_login, monkeypatch):
    demo_login(client)
    # Conecta codex primero.
    monkeypatch.setattr(codex_mod, "read_tokens", lambda path=None: {"access_token": "a", "account_id": "x", "refresh_token": "r"})
    monkeypatch.setattr(codex_mod, "test_codex", lambda *a, **k: {"ok": True, "mode": "subscription", "model": "gpt-5.5", "latency_ms": 10})
    client.post("/v1/provider/openai/connect")

    res = client.post("/v1/provider/test")
    assert res.status_code == 200
    assert res.json()["ok"] is True and res.json()["model"] == "gpt-5.5"
