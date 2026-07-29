"""Panel de proveedor: guardar/leer/enmascarar/desconectar la credencial de IA."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.models import Base, IntegrationCredential, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("cryptography")  # el secreto del proveedor se guarda cifrado

@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Sin API key de entorno por defecto, para que env_fallback sea determinista.
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
        name="Taquería Demo",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={
            "demo": True,
            "members": [
                {"name": "Demo", "email": "demo@aiuda.mx", "role": "dueño", "status": "activo"}
            ],
        },
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_provider_responde_local(client, demo_tenant):
    assert client.get("/v1/provider").status_code == 200


def test_estado_inicial_sin_conectar(client, demo_tenant, demo_login):
    demo_login(client)
    body = client.get("/v1/provider").json()
    assert body["name"] == "claude"
    assert body["mode"] == "api_key"
    assert body["connected"] is False
    assert body["env_fallback"] is False
    assert body["secret"] == ""


def test_guardar_leer_enmascarado_y_desconectar(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put(
        "/v1/provider", json={"name": "claude", "mode": "api_key", "secret": "sk-abc"}
    )
    assert res.status_code == 200 and res.json()["connected"] is True
    # Leer: el secreto va enmascarado
    body = client.get("/v1/provider").json()
    assert body["connected"] is True and body["secret"] == "••••••"
    # Re-guardar con el placeholder no borra el secreto
    client.put("/v1/provider", json={"name": "claude", "mode": "api_key", "secret": "••••••"})
    assert client.get("/v1/provider").json()["connected"] is True
    # Desconectar
    assert client.delete("/v1/provider").json()["connected"] is False
    assert client.get("/v1/provider").json()["connected"] is False


def test_modo_suscripcion_se_guarda(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put(
        "/v1/provider",
        json={"name": "claude", "mode": "subscription", "secret": "oauth-tok"},
    )
    assert res.status_code == 200
    body = client.get("/v1/provider").json()
    assert body["mode"] == "subscription" and body["connected"] is True


def test_codex_no_se_conecta_pegando_secreto(client, demo_tenant, demo_login):
    # OpenAI (codex) se conecta por OAuth, no pegando un secreto: la vía PUT lo rechaza y
    # dirige al botón de ChatGPT. La conexión real se prueba en test_provider_openai.py.
    demo_login(client)
    res = client.put(
        "/v1/provider", json={"name": "codex", "mode": "subscription", "secret": "sk-x"}
    )
    assert res.status_code == 400
    assert "ChatGPT" in res.json()["detail"]


def test_modo_invalido_rechazado(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put(
        "/v1/provider", json={"name": "claude", "mode": "inventado", "secret": "sk-x"}
    )
    assert res.status_code == 400


def test_secreto_vacio_rechazado(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put("/v1/provider", json={"name": "claude", "mode": "api_key", "secret": ""})
    assert res.status_code == 400


def test_env_fallback_se_reporta(client, demo_tenant, monkeypatch, demo_login):
    demo_login(client)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    body = client.get("/v1/provider").json()
    assert body["connected"] is False and body["env_fallback"] is True


def test_secreto_se_guarda_cifrado_no_en_claro(client, demo_tenant, db_session, demo_login):
    """El bug de la auditoría: el secreto de IA vivía en texto plano en
    tenant.config['provider']. Ahora se cifra en IntegrationCredential('ia') y el
    config queda limpio; el motor lo lee descifrado por la vía sesión+tenant."""
    from aiuda_core.engine.provider import resolve_credential

    demo_login(client)
    assert client.put(
        "/v1/provider",
        json={"name": "claude", "mode": "subscription", "secret": "sk-secreto-real"},
    ).status_code == 200

    db_session.refresh(demo_tenant)
    # 1) Ya NO hay texto plano del proveedor en tenant.config (scrub).
    assert "provider" not in (demo_tenant.config or {})
    # 2) Hay fila cifrada 'ia', con el secreto FUERA del ciphertext.
    row = db_session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == demo_tenant.id,
            IntegrationCredential.provider == "ia",
        )
    )
    assert row is not None
    assert row.public_config == {"name": "claude", "mode": "subscription"}
    assert b"sk-secreto-real" not in (row.secret_ciphertext or b"")
    # 3) El motor lo resuelve descifrado (lo que de verdad usa el runner).
    cred = resolve_credential(session=db_session, tenant_id=demo_tenant.id)
    assert cred is not None
    assert cred.secret == "sk-secreto-real"
    assert cred.mode == "subscription"


def test_cifrado_end_to_end_hasta_el_cliente_del_motor(client, demo_tenant, db_session, demo_login):
    """El eslabón final del E2E: el cliente Anthropic que arma el motor a partir de
    la fila CIFRADA lleva el secreto descifrado en el header correcto (auth_token en
    suscripción, api_key en api_key). Guardar → cifrar → resolver → usar."""
    from aiuda_core.engine.provider import build_anthropic_client, resolve_credential

    demo_login(client)

    # Vía suscripción: Authorization Bearer con el token descifrado.
    client.put(
        "/v1/provider",
        json={"name": "claude", "mode": "subscription", "secret": "oauth-cifrado-e2e"},
    )
    cred = resolve_credential(session=db_session, tenant_id=demo_tenant.id)
    cli = build_anthropic_client(cred)
    assert cli.auth_token == "oauth-cifrado-e2e" and cli.api_key is None

    # Vía API key: x-api-key con la key descifrada.
    client.put(
        "/v1/provider",
        json={"name": "claude", "mode": "api_key", "secret": "sk-cifrado-e2e"},
    )
    cred = resolve_credential(session=db_session, tenant_id=demo_tenant.id)
    cli = build_anthropic_client(cred)
    assert cli.api_key == "sk-cifrado-e2e" and cli.auth_token is None


# ---------------------------------------------------------------- #
# El CLI ya instalado del dueño: un clic, sin secreto que guardar.
# ---------------------------------------------------------------- #


def test_conectar_el_cli_instalado_sin_pegar_nada(client, demo_tenant, db_session, demo_login, monkeypatch):
    from aiuda_core.engine import cli_runner

    monkeypatch.setattr(cli_runner, "detectar", lambda cli: "/usr/local/bin/claude")
    r = client.put("/v1/provider", json={"name": "claude_cli", "mode": "cli", "secret": ""})
    assert r.status_code == 200
    assert r.json() == {"name": "claude_cli", "mode": "cli", "connected": True}

    estado = client.get("/v1/provider").json()
    assert estado["connected"] is True
    assert estado["mode"] == "cli"
    assert estado["secret"] == ""  # no hay secreto: la sesión vive en el CLI

    fila = db_session.execute(select(IntegrationCredential)).scalar_one()
    assert fila.provider == "ia"


def test_conectar_cli_no_instalado_lo_dice_sin_guardar(client, demo_tenant, db_session, demo_login, monkeypatch):
    from aiuda_core.engine import cli_runner

    monkeypatch.setattr(cli_runner, "detectar", lambda cli: None)
    r = client.put("/v1/provider", json={"name": "codex_cli", "mode": "cli", "secret": ""})
    assert r.status_code == 400
    assert "codex" in r.json()["detail"].lower()
    assert db_session.execute(select(IntegrationCredential)).first() is None


def test_probar_el_cli_ejecuta_el_binario(client, demo_tenant, demo_login, monkeypatch):
    from aiuda_core.engine import cli_runner

    monkeypatch.setattr(cli_runner, "detectar", lambda cli: "/usr/local/bin/claude")
    client.put("/v1/provider", json={"name": "claude_cli", "mode": "cli", "secret": ""})
    monkeypatch.setattr(
        cli_runner, "probar", lambda cli, **kw: {"ok": True, "mode": "cli", "model": f"{cli}-cli", "latency_ms": 42}
    )
    r = client.post("/v1/provider/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "mode": "cli", "model": "claude-cli", "latency_ms": 42}
