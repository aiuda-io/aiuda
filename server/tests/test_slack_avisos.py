"""Avisos al equipo por Slack: helper, punto de uso real en el worker y tester.

El producto ya genera dos avisos internos (el resumen diario de cartera y el
aviso de corte de IA por tope): aquí se blinda que salen por Slack cuando el
tenant lo conectó (bot token + canal, cifrados) y que sin conexión o con Slack
caído son no-op silenciosos — un aviso nunca tumba la corrida.
"""

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server.api.main import app, get_db
from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.slack import aviso_al_equipo
from aiuda_core.models import Base, IntegrationCredential, Tenant

pytest.importorskip("cryptography")


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
    t = Tenant(
        name="Demo", owner_phone="52155", evolution_instance="demo",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño"}]},
    )
    db_session.add(t)
    db_session.flush()
    return t


def _conectar_slack(db_session, tenant, channel="#cobranza"):
    values = {"bot_token": "xoxb-cifrado"}
    if channel:
        values["channel"] = channel
    cred.set_credential(db_session, tenant.id, "slack", values)


# --------------------------------------------------------------------------- #
# aviso_al_equipo: el helper que usan el worker y quien avise después           #
# --------------------------------------------------------------------------- #


def test_aviso_sale_con_credencial_cifrada(db_session, tenant):
    _conectar_slack(db_session, tenant)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    ok = aviso_al_equipo(
        db_session, tenant.id, "aviso de prueba", transport=httpx.MockTransport(handler)
    )
    assert ok is True
    assert captured["path"] == "/api/chat.postMessage"
    assert captured["auth"] == "Bearer xoxb-cifrado"  # descifrado de la fila del tenant
    assert captured["body"] == {"channel": "#cobranza", "text": "aviso de prueba"}


def test_aviso_sin_conexion_es_noop(db_session, tenant):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("sin credencial NO debe pegar a Slack")

    ok = aviso_al_equipo(
        db_session, tenant.id, "aviso", transport=httpx.MockTransport(handler)
    )
    assert ok is False


def test_aviso_sin_canal_es_noop(db_session, tenant):
    _conectar_slack(db_session, tenant, channel="")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("sin canal NO debe pegar a Slack")

    ok = aviso_al_equipo(
        db_session, tenant.id, "aviso", transport=httpx.MockTransport(handler)
    )
    assert ok is False


def test_aviso_con_slack_caido_no_truena(db_session, tenant):
    """Error de la API (ok=false) o de red: se registra y devuelve False, sin
    excepción — el flujo que avisa (la corrida) sigue como si nada."""
    _conectar_slack(db_session, tenant)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    ok = aviso_al_equipo(
        db_session, tenant.id, "aviso", transport=httpx.MockTransport(handler)
    )
    assert ok is False

    def handler_red(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    ok = aviso_al_equipo(
        db_session, tenant.id, "aviso", transport=httpx.MockTransport(handler_red)
    )
    assert ok is False


# --------------------------------------------------------------------------- #
# Punto de uso real 1: el aviso de tope de IA sale a Slack (una vez al mes)     #
# --------------------------------------------------------------------------- #


def test_aviso_tope_sale_por_slack_una_vez(db_session, tenant, monkeypatch):
    import aiuda_core.connectors.slack as slack_mod
    from aiuda_server.worker import main as worker

    avisos: list[str] = []
    monkeypatch.setattr(
        slack_mod, "aviso_al_equipo", lambda s, tid, texto, **kw: avisos.append(texto) or True
    )

    worker._aviso_tope(db_session, tenant, "tope de tokens del plan alcanzado")
    assert len(avisos) == 1
    assert "tope de tokens" in avisos[0]

    # Mismo mes: el guard mensual también evita spamear Slack.
    worker._aviso_tope(db_session, tenant, "tope de tokens del plan alcanzado")
    assert len(avisos) == 1


# --------------------------------------------------------------------------- #
# Punto de uso real 2: el resumen diario sale a Slack en la corrida             #
# --------------------------------------------------------------------------- #


def test_resumen_diario_sale_por_slack_en_la_corrida(db_session, tenant, monkeypatch):
    import aiuda_core.connectors.slack as slack_mod
    import aiuda_core.engine.sync as sync_mod
    from aiuda_server.worker import main as worker

    @contextmanager
    def fake_scope():
        yield db_session

    class _Engine:
        runner = None

        def run_reminders(self, today):
            return []

        def summary_due(self, hour):
            return True  # es la hora del resumen

        def daily_summary(self, today):
            return "aiuda · Resumen de cartera"

        def send_whatsapp(self, phone, text):
            raise RuntimeError("sin canal de WhatsApp en la prueba")

    avisos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        slack_mod,
        "aviso_al_equipo",
        lambda s, tid, texto, **kw: avisos.append((tid, texto)) or True,
    )
    monkeypatch.setattr(worker, "session_scope", fake_scope)
    monkeypatch.setattr(worker, "_build_engine", lambda s, tt, run=None: _Engine())
    monkeypatch.setattr(worker, "_process_writebacks", lambda s, tt, run=None: None)
    monkeypatch.setattr(sync_mod, "sync_fuentes", lambda *a, **k: None)

    report = worker.run_daily_blocking()

    # El MISMO texto del resumen salió a Slack, y cuenta como entregado aunque
    # WhatsApp no tenga canal (al menos un canal lo sacó).
    assert avisos == [(tenant.id, "aiuda · Resumen de cartera")]
    assert report["summaries"] == 1


# --------------------------------------------------------------------------- #
# Tester: Probar conexión usa auth.test con la credencial cifrada               #
# --------------------------------------------------------------------------- #


def _login(client, demo_login):
    demo_login(client)


def test_probar_conexion_slack_ok(client, db_session, tenant, monkeypatch, demo_login):
    import aiuda_core.connectors.slack as slack_mod

    _login(client, demo_login)
    client.put(
        "/v1/integrations/slack/config",
        json={"values": {"bot_token": "xoxb-cifrado", "channel": "#cobranza"}},
    )

    captured = {}

    class _FakeSlack:
        def __init__(self, bot_token=None, transport=None):
            captured["bot_token"] = bot_token

        def test_connection(self):
            return {"team": "Despacho Ejemplo", "user": "aiuda"}

    monkeypatch.setattr(slack_mod, "SlackClient", _FakeSlack)
    body = client.post("/v1/integrations/slack/test").json()

    assert captured["bot_token"] == "xoxb-cifrado"
    assert body["ok"] is True
    assert "Despacho Ejemplo" in body["message"]
    assert body["details"]["Canal de avisos"] == "#cobranza"

    row = db_session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == "slack",
        )
    )
    assert row.status == "connected"


def test_probar_conexion_slack_exige_canal(client, db_session, tenant, demo_login):
    _login(client, demo_login)
    client.put("/v1/integrations/slack/config", json={"values": {"bot_token": "xoxb-solo"}})
    body = client.post("/v1/integrations/slack/test").json()
    assert body["ok"] is False
    assert "canal" in body["message"]


def test_avisos_equipo_aparece_vivo_en_el_grafo(client, tenant, demo_login):
    """El envío está cableado (worker -> aviso_al_equipo): la capacidad deja de
    ser una promesa. El semáforo 'verified' sigue diciendo si YA se probó."""
    _login(client, demo_login)
    body = client.get("/v1/integrations").json()
    caps = {c["key"]: c for c in body["capabilities"]}
    assert caps["avisos_equipo"]["live"] is True
    slack = next(s for s in body["systems"] if s["key"] == "slack")
    assert slack["live"] is True
    assert slack["connected"] is False  # vivo no miente conexión: aún sin credencial
