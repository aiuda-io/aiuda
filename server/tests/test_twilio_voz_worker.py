"""Canal de voz en el worker: un recordatorio aprobado con canal 'voz' COLOCA la
llamada por Twilio (guardando el Call SID para ligar el veredicto), y sin credenciales
queda aprobado-esperando-canal (no 'failed'), mismo trato honesto que WhatsApp/correo.
El REST de Twilio se prueba en core; aquí se intercepta el cliente para ver el cableado.
"""

from contextlib import contextmanager
from datetime import date


import aiuda_server.worker.main as worker_main
from aiuda_core.config import settings
from aiuda_core.connectors import twilio_voz as tv
from aiuda_core.connectors.credentials import set_credential
from aiuda_core.models import Base, Customer, Invoice, Reminder, Tenant
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

CALLBACK_URL = "https://api.aiuda.mx/v1/webhooks/twilio-voz"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _scope_of(session):
    @contextmanager
    def scope():
        yield session

    return scope


def _tenant(session, *, twilio=True) -> Tenant:
    t = Tenant(name="Voz S.A.", owner_phone="5215500000000", evolution_instance="inst-v", config={})
    session.add(t)
    session.flush()
    if twilio:
        set_credential(session, t.id, "twilio_voz", {
            "account_sid": "AC123", "auth_token": "tok", "from_number": "+5215512345678",
        })
    return t


def _reminder(session, t, phone="5215587654321") -> Reminder:
    cliente = Customer(tenant_id=t.id, name="Cliente", phone=phone)
    session.add(cliente)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=cliente.id, folio="F-1", amount=100,
                  issued_date=date.today(), due_date=date.today())
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Su factura F-1 vence hoy.", channel="voz", status="approved")
    session.add(r)
    session.flush()
    return r


def test_recordatorio_por_voz_coloca_la_llamada_y_queda_sent(monkeypatch):
    session = _session()
    t = _tenant(session)
    r = _reminder(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(settings, "twilio_voz_status_callback_url", CALLBACK_URL)
    llamadas: list = []
    monkeypatch.setattr(
        tv.TwilioVozClient, "llamar_recordatorio",
        lambda self, to, mensaje, from_number, status_callback=None: llamadas.append(
            (to, mensaje, from_number, status_callback)
        ) or "CA-99",
    )

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "sent"  # la llamada se colocó (salió)
    assert r.meta["voz"]["call_sid"] == "CA-99"  # ligado para el StatusCallback
    assert r.meta["voz"]["estado"] == "en_curso"
    assert llamadas == [("5215587654321", "Su factura F-1 vence hoy.", "+5215512345678", CALLBACK_URL)]


def test_recordatorio_voz_sin_twilio_queda_aprobado_esperando_canal(monkeypatch):
    session = _session()
    t = _tenant(session, twilio=False)  # sin credenciales de Twilio
    r = _reminder(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "approved"  # sin canal no hay intento: NO es 'failed'
    assert r.sent_at is None
    assert "las llamadas de voz" in r.meta["pendiente_canal"]


def test_recordatorio_voz_sin_telefono_falla_con_motivo(monkeypatch):
    session = _session()
    t = _tenant(session)
    cliente = Customer(tenant_id=t.id, name="Sin Tel")  # sin teléfono
    session.add(cliente)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=cliente.id, folio="F-2", amount=50,
                  issued_date=date.today(), due_date=date.today())
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Hola", channel="voz", status="approved")
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "failed"  # canal listo pero falta el dato del cliente
    assert r.meta["motivo_fallo"] == "el cliente no tiene teléfono"
