"""Canal de correo de punta a punta (cloud): el worker envía recordatorios por SMTP
enhebrados al hilo, la respuesta del humano sale con Re:/In-Reply-To, el agente
PROPONE respuestas a entrantes (HITL, nunca contesta solo) y la bandeja expone el
canal. El SMTP real se prueba en core (servidor local); aquí se intercepta el
conector para verificar el cableado."""

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_core.connectors.correo import CorreoClient, clave_hilo
from aiuda_core.engine.correo import CORREO_HILOS_KEY, CORREO_PENDIENTES_KEY
from aiuda_core.models import (
    Base,
    Conversation,
    Customer,
    Invoice,
    Message,
    Reminder,
    Tenant,
)
from aiuda_server.api.main import app, get_db

HEADERS = {"X-API-Key": "k-demo"}

EMAIL_CFG = {
    "provider": "imap",
    "email": "cobranza@negocio.mx",
    "password": "app-pass",
    "imap_host": "imap.negocio.mx",
    "smtp_host": "smtp.negocio.mx",
    "smtp_port": "465",
}


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


@pytest.fixture()
def db_session():
    s = _session()
    yield s
    s.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _tenant(session, *, correo=True, extra_config=None) -> Tenant:
    config = {"api_key": "k-demo"}
    if correo:
        config["integrations"] = {"email": dict(EMAIL_CFG)}
    config.update(extra_config or {})
    t = Tenant(name="La Bonita", owner_phone="5215512345678",
               evolution_instance="inst-correo", config=config)
    session.add(t)
    session.flush()
    return t


def _ana(session, t, *, phone=None) -> Customer:
    c = Customer(tenant_id=t.id, name="Ana López", email="ana@cliente.mx", phone=phone)
    session.add(c)
    session.flush()
    return c


def _smtp_interceptado(monkeypatch) -> list[dict]:
    """Intercepta CorreoClient.send (el protocolo real ya se probó en core)."""
    enviados: list[dict] = []

    def fake_send(self, para, asunto, texto, in_reply_to="", references=(), de_nombre=""):
        enviados.append({
            "para": para, "asunto": asunto, "texto": texto,
            "irt": in_reply_to, "refs": tuple(references), "nombre": de_nombre,
        })
        return f"<out-{len(enviados)}@negocio.mx>"

    monkeypatch.setattr(CorreoClient, "send", fake_send)
    return enviados


def _hilo_correo(session, t, *, de="ana@cliente.mx", asunto="Factura F-102") -> Conversation:
    conv = Conversation(
        tenant_id=t.id, remote_phone=clave_hilo(de, asunto), channel="correo"
    )
    session.add(conv)
    session.flush()
    session.add(Message(
        tenant_id=t.id, conversation_id=conv.id, direction="in",
        body="¿Me reenvías la factura?", wa_message_id="<m1@cliente.mx>",
    ))
    cfg = dict(t.config or {})
    cfg[CORREO_HILOS_KEY] = {
        conv.id: {"de": de, "nombre": "Ana López", "asunto": asunto}
    }
    t.config = cfg
    session.add(t)
    session.flush()
    return conv


# ---------- worker: recordatorio aprobado sale por correo ----------


def test_recordatorio_por_correo_sale_y_queda_en_el_hilo(monkeypatch):
    session = _session()
    t = _tenant(session)
    ana = _ana(session, t)
    inv = Invoice(tenant_id=t.id, customer_id=ana.id, folio="F-102", amount=100,
                  issued_date=date.today(), due_date=date.today())
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Hola Ana, tu factura F-102 sigue pendiente.",
                 channel="correo", status="approved")
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "sent"
    [e] = enviados
    assert e["para"] == "ana@cliente.mx"
    assert e["asunto"] == "Recordatorio de pago · Factura F-102"
    assert e["nombre"] == "La Bonita"
    # El envío quedó en un hilo de correo con su Message-ID: la respuesta de Ana
    # enhebra a esta MISMA conversación.
    conv = session.scalar(select(Conversation).where(Conversation.tenant_id == t.id))
    assert conv.channel == "correo"
    out = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    assert out.direction == "out" and out.wa_message_id == "<out-1@negocio.mx>"
    assert out.delivery == "sent"


def test_recordatorio_correo_sin_smtp_queda_aprobado_esperando_canal(monkeypatch):
    """Sin la cuenta de correo conectada NO hay intento de envío: no es un fallo.
    Queda aprobado con el aviso honesto y sale cuando el dueño conecte el canal
    (barrido horario). 'failed' es solo para un intento real que tronó."""
    session = _session()
    t = _tenant(session, correo=False)  # sin conexión de correo
    ana = _ana(session, t)
    inv = Invoice(tenant_id=t.id, customer_id=ana.id, folio="F-1", amount=50,
                  issued_date=date.today(), due_date=date.today())
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Hola", channel="correo", status="approved")
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "approved"  # sin canal no hay intento: no es 'failed'
    assert r.sent_at is None
    assert "conectes el correo" in r.meta["pendiente_canal"]


def test_recordatorio_correo_sin_destinatario_falla_con_motivo(monkeypatch):
    """Canal conectado pero el cliente NO tiene correo: eso sí pide acción del dueño
    (capturar el dato) y conectar canales no lo arregla. Failed con motivo visible."""
    session = _session()
    t = _tenant(session)  # correo conectado
    cliente = Customer(tenant_id=t.id, name="Sin Correo SA")  # sin email
    session.add(cliente)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=cliente.id, folio="F-2", amount=80,
                  issued_date=date.today(), due_date=date.today())
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Hola", channel="correo", status="approved")
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "failed"
    assert r.meta["motivo_fallo"] == "el cliente no tiene correo"


def test_respuesta_aprobada_sale_con_re_e_in_reply_to(monkeypatch):
    """El flujo HITL completo del lado del envío: la propuesta (channel=correo,
    meta.correo.conversation_id) aprobada sale como respuesta del hilo."""
    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    r = Reminder(tenant_id=t.id, bucket="respuesta_correo", tone="amable",
                 title="Correo de Ana López",
                 message="Claro Ana, aquí va de nuevo la factura.",
                 channel="correo", status="approved",
                 meta={"correo": {"para": "ana@cliente.mx", "conversation_id": conv.id}})
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "sent"
    [e] = enviados
    assert e["asunto"] == "Re: Factura F-102"
    assert e["irt"] == "<m1@cliente.mx>"
    assert "<m1@cliente.mx>" in e["refs"]
    msgs = session.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).all()
    assert [m.direction for m in msgs] == ["in", "out"]


# ---------- worker: respuesta del humano en el hilo ----------


def test_respuesta_humana_sale_por_smtp_con_threading(monkeypatch):
    session = _session()
    t = _tenant(session)
    conv = _hilo_correo(session, t)
    out = Message(tenant_id=t.id, conversation_id=conv.id, direction="out",
                  author="human", body="Va de nuevo, saludos.", delivery="pending")
    session.add(out)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)

    worker_main.send_correo_reply_blocking(t.id, conv.id, out.id)

    assert out.delivery == "sent"
    assert out.wa_message_id == "<out-1@negocio.mx>"  # enhebra la siguiente respuesta
    [e] = enviados
    assert e["para"] == "ana@cliente.mx" and e["asunto"] == "Re: Factura F-102"
    assert e["irt"] == "<m1@cliente.mx>"


def test_barrido_rescata_pendiente_de_correo_por_smtp(monkeypatch):
    """Un saliente humano de un hilo de CORREO que quedó en pending (proceso muerto)
    se reintenta por SMTP enhebrado — jamás por WhatsApp con la clave del hilo."""
    from datetime import datetime, timedelta, timezone

    session = _session()
    t = _tenant(session)
    conv = _hilo_correo(session, t)
    out = Message(tenant_id=t.id, conversation_id=conv.id, direction="out",
                  author="human", body="Va de nuevo.", delivery="pending")
    session.add(out)
    session.flush()
    out.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    session.add(out)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)
    whatsapp: list = []
    monkeypatch.setattr(
        worker_main, "send_human_message_blocking", lambda *a: whatsapp.append(a)
    )

    n = worker_main._sweep_pending_sends(datetime.now(timezone.utc))

    assert n == 1 and whatsapp == []
    assert out.delivery == "sent"
    [e] = enviados
    assert e["para"] == "ana@cliente.mx" and e["asunto"] == "Re: Factura F-102"


def test_respuesta_humana_sin_canal_marca_failed(monkeypatch):
    session = _session()
    t = _tenant(session, correo=False)
    conv = _hilo_correo(session, t)
    out = Message(tenant_id=t.id, conversation_id=conv.id, direction="out",
                  author="human", body="Hola", delivery="pending")
    session.add(out)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_correo_reply_blocking(t.id, conv.id, out.id)

    assert out.delivery == "failed"


# ---------- worker: el agente PROPONE la respuesta (HITL) ----------


class _FakeEngine:
    def __init__(self, respuesta="Hola Ana, con gusto te la reenvío."):
        self.respuesta = respuesta
        self.llamadas: list[dict] = []

    def handle_incoming(self, remote, body, today, history="", origen=None):
        self.llamadas.append({
            "remote": remote, "body": body, "history": history, "origen": origen,
        })
        return self.respuesta


def _encolar(session, t, conv, msg) -> None:
    cfg = dict(t.config or {})
    cfg[CORREO_PENDIENTES_KEY] = [msg.id]
    t.config = cfg
    session.add(t)
    session.flush()


def test_entrante_genera_propuesta_pending_approval(monkeypatch):
    session = _session()
    t = _tenant(session)
    _ana(session, t, phone="5215599998888")
    conv = _hilo_correo(session, t)
    msg = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    _encolar(session, t, conv, msg)
    engine = _FakeEngine()

    n = worker_main.procesar_correo_pendientes(session, t, engine)

    assert n == 1
    r = session.scalar(select(Reminder).where(Reminder.tenant_id == t.id))
    assert r.status == "pending_approval"  # PROPONE; el humano aprueba — nunca sale solo
    assert r.channel == "correo" and r.bucket == "respuesta_correo"
    assert r.meta["correo"]["para"] == "ana@cliente.mx"
    assert r.meta["correo"]["conversation_id"] == conv.id
    assert r.message == "Hola Ana, con gusto te la reenvío."
    # Las tools quedaron atadas al CLIENTE (su teléfono), y el prompt dice que es correo.
    [ll] = engine.llamadas
    assert ll["remote"] == "5215599998888"
    assert "Correo de" in ll["origen"] and "ana@cliente.mx" in ll["origen"]
    # La cola quedó vacía (no re-propone en la siguiente corrida).
    assert t.config[CORREO_PENDIENTES_KEY] == []


def test_hilo_tomado_por_humano_no_genera_propuesta(monkeypatch):
    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    conv.human_takeover = True
    msg = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    _encolar(session, t, conv, msg)

    n = worker_main.procesar_correo_pendientes(session, t, _FakeEngine())

    assert n == 0
    assert session.scalar(select(Reminder)) is None
    assert t.config[CORREO_PENDIENTES_KEY] == []


def test_propuesta_abierta_no_se_duplica_y_reencola(monkeypatch):
    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    session.add(Reminder(
        tenant_id=t.id, bucket="respuesta_correo", tone="amable", message="previa",
        channel="correo", status="pending_approval",
        meta={"correo": {"para": "ana@cliente.mx", "conversation_id": conv.id}},
    ))
    msg = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    _encolar(session, t, conv, msg)

    n = worker_main.procesar_correo_pendientes(session, t, _FakeEngine())

    assert n == 0
    # El entrante se re-encola: resuelta la propuesta previa, la próxima corrida propone.
    assert t.config[CORREO_PENDIENTES_KEY] == [msg.id]


def test_baja_por_correo_marca_optout_y_confirma_sin_llm(monkeypatch):
    from aiuda_core.optout import OPT_OUT_CONFIRMATION, opted_out

    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    msg = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    msg.body = "BAJA"
    _encolar(session, t, conv, msg)
    enviados = _smtp_interceptado(monkeypatch)
    engine = _FakeEngine()

    n = worker_main.procesar_correo_pendientes(session, t, engine)

    assert n == 0 and engine.llamadas == []  # sin LLM
    assert opted_out(session, t, "ana@cliente.mx") is not None
    [e] = enviados
    assert e["texto"] == OPT_OUT_CONFIRMATION and e["para"] == "ana@cliente.mx"
    # La confirmación quedó en el hilo.
    out = session.scalar(select(Message).where(
        Message.conversation_id == conv.id, Message.direction == "out"
    ))
    assert out is not None and out.body == OPT_OUT_CONFIRMATION


def test_optout_por_correo_bloquea_el_envio_aprobado(monkeypatch):
    """Si Ana pidió BAJA por correo, una propuesta aprobada NO sale: engine.send
    lanza OptedOut y el worker marca failed con motivo (mismo trato que WhatsApp)."""
    from aiuda_core.optout import mark_opt_out

    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    mark_opt_out(session, t, "ana@cliente.mx", via="correo")
    r = Reminder(tenant_id=t.id, bucket="respuesta_correo", tone="amable",
                 message="Hola", channel="correo", status="approved",
                 meta={"correo": {"para": "ana@cliente.mx", "conversation_id": conv.id}})
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)

    worker_main.send_reminder_blocking(t.id, r.id)

    assert enviados == []
    assert r.status == "failed" and r.meta["motivo_fallo"] == "opt-out"


def test_hitl_completo_propuesta_aprobada_sale_enhebrada(monkeypatch):
    """La costura entera: entrante → propuesta del agente (pending_approval) →
    aprobación humana → envío SMTP como respuesta del hilo (Re: + In-Reply-To) →
    el enviado queda en la MISMA conversación. Sin tocar los metadatos a mano."""
    from aiuda_core.engine import approval

    session = _session()
    t = _tenant(session)
    _ana(session, t)
    conv = _hilo_correo(session, t)
    msg = session.scalar(select(Message).where(Message.conversation_id == conv.id))
    _encolar(session, t, conv, msg)

    assert worker_main.procesar_correo_pendientes(session, t, _FakeEngine()) == 1
    r = session.scalar(select(Reminder).where(Reminder.tenant_id == t.id))
    approval.advance(r, "approved")  # la decisión del humano
    session.flush()

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    enviados = _smtp_interceptado(monkeypatch)
    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "sent"
    [e] = enviados
    assert e["para"] == "ana@cliente.mx"
    assert e["asunto"] == "Re: Factura F-102" and e["irt"] == "<m1@cliente.mx>"
    msgs = session.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).all()
    assert [m.direction for m in msgs] == ["in", "out"]
    assert msgs[-1].body == r.message and msgs[-1].wa_message_id == "<out-1@negocio.mx>"


# ---------- API: bandeja con canal y respuesta desde el hilo ----------


def test_bandeja_muestra_canal_y_cliente_por_email(client, db_session):
    t = _tenant(db_session)
    _ana(db_session, t)
    conv = _hilo_correo(db_session, t)

    rows = client.get("/v1/conversations", headers=HEADERS).json()
    [row] = rows
    assert row["channel"] == "correo"
    assert row["correo"] == {"de": "ana@cliente.mx", "nombre": "Ana López", "asunto": "Factura F-102"}
    assert row["status"] == "identificado" and row["customer"] == "Ana López"

    detail = client.get(f"/v1/conversations/{conv.id}", headers=HEADERS).json()
    assert detail["channel"] == "correo" and detail["correo"]["asunto"] == "Factura F-102"
    assert detail["customer"] == "Ana López"


def test_responder_hilo_de_correo_agenda_smtp(client, db_session, monkeypatch):
    t = _tenant(db_session)
    conv = _hilo_correo(db_session, t)
    calls: list[tuple] = []
    monkeypatch.setattr(worker_main, "send_correo_reply_blocking", lambda *a: calls.append(a))

    res = client.post(
        f"/v1/conversations/{conv.id}/messages", headers=HEADERS, json={"body": "Va de nuevo."}
    )
    assert res.status_code == 200 and res.json()["queued"] is True
    saved = db_session.scalar(select(Message).where(
        Message.tenant_id == t.id, Message.direction == "out"
    ))
    assert saved.delivery == "pending" and saved.author == "human"
    assert calls == [(t.id, conv.id, saved.id)]  # va por SMTP, no por WhatsApp


def test_registrar_cliente_en_hilo_de_correo_usa_el_remitente(client, db_session):
    t = _tenant(db_session)
    conv = _hilo_correo(db_session, t, de="nuevo@cliente.mx", asunto="Pedido")

    res = client.post(
        f"/v1/conversations/{conv.id}/registrar-cliente",
        headers=HEADERS, json={"name": "Cliente Nuevo"},
    )
    assert res.status_code == 200 and res.json()["created"] is True
    cust = db_session.scalar(select(Customer).where(Customer.tenant_id == t.id))
    assert cust.email == "nuevo@cliente.mx"
    assert cust.phone is None  # jamás la clave del hilo como teléfono
    # Y de ahí en adelante el hilo cruza solo.
    [row] = client.get("/v1/conversations", headers=HEADERS).json()
    assert row["status"] == "identificado"


def test_canal_correo_disponible_en_recordatorios_solo_si_conectado(client, db_session):
    t = _tenant(db_session)
    ana = _ana(db_session, t)
    inv = Invoice(tenant_id=t.id, customer_id=ana.id, folio="F-9", amount=10,
                  issued_date=date.today(), due_date=date.today())
    db_session.add(inv)
    db_session.flush()
    db_session.add(Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida",
                            tone="firme", message="hola", status="pending_approval"))
    db_session.flush()

    [r] = client.get("/v1/reminders", headers=HEADERS).json()
    canales = {c["key"]: c["connected"] for c in r["channels"]}
    assert canales["correo"] is True  # conectado Y el cliente tiene email
    assert canales["whatsapp"] is False  # Ana no tiene teléfono
