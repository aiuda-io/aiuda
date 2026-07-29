"""Webhook de estado de las llamadas de voz (Twilio), de punta a punta.

Cubre:
- firma X-Twilio-Signature OBLIGATORIA (HMAC-SHA1 url+params, base64) con el
  auth_token del tenant; sin firma válida → 403,
- routing por AccountSid al tenant dueño de la cuenta (cuenta desconocida → 403),
- 'completed' confirma la entrega (queda 'sent' con resultado),
- 'no-answer'/'busy'/'failed' marca 'failed' con motivo visible (mismo trato honesto),
- idempotencia (Twilio reintenta el callback).
"""

import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.connectors.credentials import set_credential
from aiuda_core.models import Base, Customer, Reminder, Tenant
from aiuda_server.api.main import _available_channels, app, get_db

CALLBACK_URL = "https://api.aiuda.mx/v1/webhooks/twilio-voz"
ACCOUNT_A = "ACxxxxaaaaxxxxaaaaxxxxaaaaxxxxaaaa"
ACCOUNT_B = "ACxxxxbbbbxxxxbbbbxxxxbbbbxxxxbbbb"
TOKEN_A = "token-de-A"
TOKEN_B = "token-de-B"


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
def client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "twilio_voz_status_callback_url", CALLBACK_URL)
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _tenant(db, name, account_sid, auth_token) -> Tenant:
    t = Tenant(name=name, owner_phone="5215500000000", evolution_instance=f"inst-{name}", config={})
    db.add(t)
    db.flush()
    set_credential(db, t.id, "twilio_voz", {
        "account_sid": account_sid, "auth_token": auth_token, "from_number": "+5215512345678",
    })
    return t


def _reminder(db, tenant, call_sid, status="sent") -> Reminder:
    r = Reminder(
        tenant_id=tenant.id, bucket="vencida", tone="firme",
        message="Su factura F-001 vence hoy.", channel="voz", status=status,
        meta={"voz": {"call_sid": call_sid, "estado": "en_curso"}},
    )
    db.add(r)
    db.flush()
    return r


def _sign(params: dict, token: str, url: str = CALLBACK_URL) -> str:
    base = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(token.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _callback(call_sid, status, account_sid=ACCOUNT_A) -> dict:
    return {"CallSid": call_sid, "CallStatus": status, "AccountSid": account_sid, "CallDuration": "30"}


# ---------- firma ----------

def test_firma_invalida_rechaza_y_no_toca_el_recordatorio(client, db_session):
    t = _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    r = _reminder(db_session, t, "CA1")
    params = _callback("CA1", "completed")
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": "firma-falsa"})
    assert resp.status_code == 403
    db_session.refresh(r)
    assert r.status == "sent" and r.meta["voz"]["estado"] == "en_curso"  # intacto


def test_cuenta_desconocida_rechaza(client, db_session):
    _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    params = _callback("CA1", "completed", account_sid="ACdesconocida000000000000000000000")
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": _sign(params, TOKEN_A)})
    assert resp.status_code == 403


# ---------- entrega ----------

def test_completed_confirma_la_entrega(client, db_session):
    t = _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    r = _reminder(db_session, t, "CA1")
    params = _callback("CA1", "completed")
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": _sign(params, TOKEN_A)})
    assert resp.status_code == 200 and resp.json()["status"] == "completed"
    db_session.refresh(r)
    assert r.status == "sent"  # sigue enviado: la llamada se contestó
    assert r.meta["voz"]["estado"] == "completed"
    assert r.meta["voz"]["resultado"] == "contestada"


@pytest.mark.parametrize("status,motivo", [
    ("no-answer", "no contestó"), ("busy", "ocupado"), ("failed", "la llamada falló"),
])
def test_falla_marca_failed_con_motivo(client, db_session, status, motivo):
    t = _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    r = _reminder(db_session, t, "CA1")
    params = _callback("CA1", status)
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": _sign(params, TOKEN_A)})
    assert resp.status_code == 200 and resp.json()["status"] == "failed"
    db_session.refresh(r)
    assert r.status == "failed"  # sent -> failed: entrega fallida honesta
    assert motivo in r.meta["motivo_fallo"]
    assert r.meta["voz"]["resultado"] == motivo


def test_idempotente_ignora_el_reintento(client, db_session):
    t = _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    _reminder(db_session, t, "CA1")
    params = _callback("CA1", "completed")
    headers = {"X-Twilio-Signature": _sign(params, TOKEN_A)}
    client.post("/v1/webhooks/twilio-voz", data=params, headers=headers)
    r2 = client.post("/v1/webhooks/twilio-voz", data=params, headers=headers)
    assert r2.json()["status"] == "duplicate"  # Twilio reintenta: no re-procesa


def test_callsid_sin_recordatorio_se_ignora(client, db_session):
    _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    params = _callback("CA-inexistente", "completed")
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": _sign(params, TOKEN_A)})
    assert resp.status_code == 200 and resp.json()["status"] == "ignored"


# ---------- routing por cuenta ----------

def test_rutea_al_tenant_dueno_de_la_cuenta(client, db_session):
    a = _tenant(db_session, "A", ACCOUNT_A, TOKEN_A)
    b = _tenant(db_session, "B", ACCOUNT_B, TOKEN_B)
    ra = _reminder(db_session, a, "CA-A")
    rb = _reminder(db_session, b, "CA-B")
    # Callback de la cuenta de B, firmado con el token de B: solo toca el de B.
    params = _callback("CA-B", "no-answer", account_sid=ACCOUNT_B)
    resp = client.post("/v1/webhooks/twilio-voz", data=params,
                       headers={"X-Twilio-Signature": _sign(params, TOKEN_B)})
    assert resp.status_code == 200
    db_session.refresh(ra)
    db_session.refresh(rb)
    assert ra.status == "sent"  # el de A no se tocó
    assert rb.status == "failed"


# ---------- selector de canal en /v1/reminders ----------

def test_voz_es_canal_elegible_cuando_esta_vivo_y_hay_telefono():
    cust = Customer(name="Cliente", phone="5215587654321")
    # Canal 'voz' vivo (tenant conectó Twilio) + cliente con teléfono → elegible.
    canales = {c["key"]: c["connected"] for c in _available_channels(cust, None, live={"whatsapp", "voz"})}
    assert canales["voz"] is True
    # Sin voz en los vivos aparece, pero 'por conectar' (connected=False).
    solo_wa = {c["key"]: c["connected"] for c in _available_channels(cust, None, live={"whatsapp"})}
    assert solo_wa["voz"] is False
    # Vivo pero el cliente no tiene teléfono (voz entrega a phone): no elegible.
    sin_tel = Customer(name="Sin Tel")
    sin = {c["key"]: c["connected"] for c in _available_channels(sin_tel, None, live={"voz"})}
    assert sin["voz"] is False
