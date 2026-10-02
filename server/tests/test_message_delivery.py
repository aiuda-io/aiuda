"""El composer (ficha, hilo, adjuntos) guarda el mensaje y responde al INSTANTE; el
envío por WhatsApp se agenda en segundo plano (no bloquea ~10s la consola).

- Tests de endpoint: el mensaje queda guardado y el envío se agenda con los args correctos.
- Tests de worker: la lógica real de envío (gating por canal conectado, resiliencia)."""

import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_core.config import settings
from aiuda_core.models import Base, Customer, Message, Tenant
from aiuda_server.api.main import app, get_db

HEADERS = {"X-API-Key": "k-demo"}


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


def _tenant(db_session, *, connected: bool) -> Tenant:
    config = {"api_key": "k-demo"}
    if connected:
        config["integrations"] = {"whatsapp": {"via": "wacli"}}
    t = Tenant(name="T", owner_phone="5215512345678", evolution_instance="inst", config=config)
    db_session.add(t)
    db_session.flush()
    return t


def _customer(db_session, t, phone="5215599998888") -> Customer:
    c = Customer(tenant_id=t.id, name="Cliente", phone=phone)
    db_session.add(c)
    db_session.flush()
    return c


# --- Endpoints: guardan al instante y agendan el envío en segundo plano ---


def test_mensaje_se_guarda_y_agenda_envio(client, db_session, monkeypatch):
    t = _tenant(db_session, connected=True)
    c = _customer(db_session, t)
    calls: list[tuple] = []
    monkeypatch.setattr(worker_main, "send_human_message_blocking", lambda *a: calls.append(a))
    res = client.post(f"/v1/customers/{c.id}/messages", headers=HEADERS, json={"body": "Hola"})
    assert res.status_code == 200
    assert res.json()["queued"] is True
    # El mensaje quedó guardado de inmediato (no depende del envío) y marcado pending.
    saved = db_session.scalar(select(Message).where(Message.tenant_id == t.id))
    assert saved is not None and saved.delivery == "pending"
    # El envío se agendó en segundo plano con (tenant, teléfono, cuerpo, message_id).
    tid, phone, body, mid = calls[0]
    assert (tid, phone, body) == (t.id, "5215599998888", "Hola") and mid == saved.id


def test_hilo_se_guarda_y_agenda_envio(client, db_session, monkeypatch):
    from aiuda_core.models import Conversation

    t = _tenant(db_session, connected=True)
    conv = Conversation(tenant_id=t.id, remote_phone="5215599998888", channel="whatsapp")
    db_session.add(conv)
    db_session.flush()
    calls: list[tuple] = []
    monkeypatch.setattr(worker_main, "send_human_message_blocking", lambda *a: calls.append(a))
    res = client.post(
        f"/v1/conversations/{conv.id}/messages", headers=HEADERS, json={"body": "Hey"}
    )
    assert res.status_code == 200 and res.json()["queued"] is True
    saved = db_session.scalar(select(Message).where(Message.tenant_id == t.id))
    assert saved.delivery == "pending"
    tid, phone, body, mid = calls[0]
    assert (tid, phone, body) == (t.id, "5215599998888", "Hey") and mid == saved.id


def test_adjunto_se_guarda_y_agenda_envio(client, db_session, monkeypatch):
    t = _tenant(db_session, connected=True)
    c = _customer(db_session, t)
    calls: list[tuple] = []
    monkeypatch.setattr(worker_main, "send_human_file_blocking", lambda *a: calls.append(a))
    res = client.post(
        f"/v1/customers/{c.id}/attachments",
        headers=HEADERS,
        data={"caption": "Tu factura"},
        files={"file": ("factura.pdf", b"%PDF-1.4 data", "application/pdf")},
    )
    assert res.status_code == 200 and res.json()["queued"] is True
    assert res.json()["body"] == "Tu factura"
    assert db_session.scalar(select(Message).where(Message.tenant_id == t.id)) is not None
    # (tenant, phone, tmp_path, caption, filename)
    tid, phone, tmp_path, caption, filename = calls[0]
    assert (tid, phone, caption, filename) == (t.id, "5215599998888", "Tu factura", "factura.pdf")
    # El endpoint dejó el temporal escrito (la tarea real lo borraría al enviar).
    assert os.path.exists(tmp_path)
    os.remove(tmp_path)
    os.rmdir(os.path.dirname(tmp_path))


def test_reintento_repone_pending_y_reencola(client, db_session, monkeypatch):
    from aiuda_core.models import Conversation

    t = _tenant(db_session, connected=True)
    conv = Conversation(tenant_id=t.id, remote_phone="5215599998888", channel="whatsapp")
    db_session.add(conv)
    db_session.flush()
    msg = Message(
        tenant_id=t.id, conversation_id=conv.id, direction="out",
        author="human", body="Reintenta esto", delivery="failed",
    )
    db_session.add(msg)
    db_session.flush()

    calls: list[tuple] = []
    monkeypatch.setattr(worker_main, "send_human_message_blocking", lambda *a: calls.append(a))
    res = client.post(
        f"/v1/conversations/{conv.id}/messages/{msg.id}/resend", headers=HEADERS
    )
    assert res.status_code == 200 and res.json()["delivery"] == "pending"
    db_session.refresh(msg)
    assert msg.delivery == "pending"  # repuesto para el nuevo intento
    tid, phone, body, mid = calls[0]
    assert (tid, phone, body, mid) == (t.id, "5215599998888", "Reintenta esto", msg.id)


def test_reintento_rechaza_mensaje_ajeno(client, db_session):
    from aiuda_core.models import Conversation

    t = _tenant(db_session, connected=True)
    conv = Conversation(tenant_id=t.id, remote_phone="5215599998888", channel="whatsapp")
    db_session.add(conv)
    db_session.flush()
    # Un entrante (del cliente) no es "tuyo": no se puede reintentar.
    msg = Message(tenant_id=t.id, conversation_id=conv.id, direction="in", body="hola")
    db_session.add(msg)
    db_session.flush()
    res = client.post(
        f"/v1/conversations/{conv.id}/messages/{msg.id}/resend", headers=HEADERS
    )
    assert res.status_code == 400


def test_adjunto_sin_telefono_falla(client, db_session):
    t = _tenant(db_session, connected=True)
    c = _customer(db_session, t, phone=None)
    res = client.post(
        f"/v1/customers/{c.id}/attachments",
        headers=HEADERS,
        files={"file": ("x.png", b"img", "image/png")},
    )
    assert res.status_code == 400


# --- Worker: la lógica real de envío (con session_scope y get_whatsapp_sender mockeados) ---


def _fake_scope(tenant):
    class _S:
        def get(self, model, _id):
            return tenant

    @contextmanager
    def scope():
        yield _S()

    return scope


def test_worker_envia_si_conectado(monkeypatch):
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    sent: list[tuple] = []
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda phone, text: sent.append((wa.instance, phone, text))),
    )
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")
    assert sent == [("inst", "5215599998888", "Hola")]


def test_worker_no_envia_si_no_conectado(monkeypatch):
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst", config={})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    called: list[int] = []
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda phone, text: called.append(1)),
    )
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")
    assert called == []


def test_worker_resiliente_a_error_de_envio(monkeypatch):
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))

    def boom(wa, window=None):
        def _s(phone, text):
            raise RuntimeError("lock ocupado")
        return _s

    monkeypatch.setattr(worker_main, "get_whatsapp_sender", boom)
    # No debe propagar: _safe_send atrapa y registra.
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")


def test_worker_pausa_sync_alrededor_del_envio(monkeypatch):
    """Configurados los comandos, el envío para el sync ANTES y lo reinicia DESPUÉS
    (así suelta el lock del store y el envío no espera ~30s)."""
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "echo stop")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "echo start")
    monkeypatch.setattr(settings, "wacli_sync_settle_secs", 0.0)
    events: list = []
    monkeypatch.setattr(
        worker_main.subprocess, "run",
        lambda args, **kw: events.append(("cmd", args[-1])),
    )
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda phone, text: events.append(("send", phone))),
    )
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")
    assert events == [("cmd", "stop"), ("send", "5215599998888"), ("cmd", "start")]


def test_worker_reinicia_sync_aunque_falle_el_envio(monkeypatch):
    """El sync se reanuda pase lo que pase: si el envío truena, igual reiniciamos."""
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "echo stop")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "echo start")
    monkeypatch.setattr(settings, "wacli_sync_settle_secs", 0.0)
    events: list = []
    monkeypatch.setattr(
        worker_main.subprocess, "run",
        lambda args, **kw: events.append(args[-1]),
    )

    def boom(wa, window=None):
        def _s(phone, text):
            raise RuntimeError("envío falló")
        return _s

    monkeypatch.setattr(worker_main, "get_whatsapp_sender", boom)
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")
    assert events == ["stop", "start"]  # se reinició aunque el envío falló


def test_worker_sin_sync_cmds_no_toca_el_sync(monkeypatch):
    """Por default (sin comandos) no se llama a subprocess: el envío cae al --lock-wait."""
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    cmds: list = []
    monkeypatch.setattr(worker_main.subprocess, "run", lambda *a, **k: cmds.append(a))
    sent: list = []
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda phone, text: sent.append(phone)),
    )
    worker_main.send_human_message_blocking("tid", "5215599998888", "Hola")
    assert sent == ["5215599998888"] and cmds == []


def test_worker_archivo_borra_temporal(monkeypatch, tmp_path):
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    monkeypatch.setattr(worker_main, "session_scope", _fake_scope(t))
    monkeypatch.setattr(settings, "whatsapp_provider", "wacli")
    import aiuda_core.connectors.wacli as wacli_mod
    sent: list[tuple] = []
    monkeypatch.setattr(
        wacli_mod.WacliClient, "send_file",
        lambda self, phone, file_path, caption="", filename=None: sent.append((phone, file_path)),
    )
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4")
    worker_main.send_human_file_blocking("tid", "5215599998888", str(f), "cap", "doc.pdf")
    assert sent and sent[0][0] == "5215599998888"
    assert not f.exists()  # el temporal se borró


def test_worker_reconoce_al_dueno_por_ultimos_10_digitos(monkeypatch):
    """El dueño se reconoce aunque owner_phone y el teléfono del webhook vengan en formatos
    distintos (52 vs 521): la igualdad exacta fallaría, match_key (últimos 10) acierta."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from aiuda_core.models import Conversation, Message

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    t = Tenant(name="T", owner_phone="525512345678", evolution_instance="inst", config={})
    session.add(t)
    session.flush()
    conv = Conversation(tenant_id=t.id, remote_phone="5215512345678")  # mismos 10 dígitos
    session.add(conv)
    session.flush()
    msg = Message(tenant_id=t.id, conversation_id=conv.id, direction="in", body="ok")
    session.add(msg)
    session.flush()

    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(worker_main, "session_scope", scope)
    sent: list = []
    monkeypatch.setattr(
        worker_main,
        "_build_engine",
        lambda s, tenant, run=None: SimpleNamespace(send_whatsapp=lambda p, txt: sent.append((p, txt))),
    )
    called: list = []
    monkeypatch.setattr(
        "aiuda_core.engine.owner.handle_owner_command",
        lambda s, tenant, body: called.append(body)
        or SimpleNamespace(text="Aprobado", send_reminders=[]),
    )

    worker_main.process_incoming_message_blocking(t.id, msg.id)

    assert called == ["ok"]  # el dueño fue reconocido pese al formato distinto
    assert sent == [("525512345678", "Aprobado")]  # responde al owner_phone del tenant


# --- Estado de entrega (pending/sent/failed) + barrido de recuperación ---


def _real_session():
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


def _pending_out_msg(session, t, *, body="Hola", minutes_ago=0):
    from datetime import datetime, timedelta, timezone

    from aiuda_core.models import Conversation

    conv = session.scalar(select(Conversation).where(Conversation.tenant_id == t.id))
    if conv is None:
        conv = Conversation(tenant_id=t.id, remote_phone="5215599998888", channel="whatsapp")
        session.add(conv)
        session.flush()
    m = Message(
        tenant_id=t.id, conversation_id=conv.id, direction="out",
        author="human", body=body, delivery="pending",
    )
    session.add(m)
    session.flush()
    if minutes_ago:
        m.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        session.add(m)
        session.flush()
    return m


def test_delivery_marca_sent_al_enviar(monkeypatch):
    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    m = _pending_out_msg(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(worker_main, "get_whatsapp_sender", lambda wa, window=None: (lambda p, txt: None))
    worker_main.send_human_message_blocking(t.id, "5215599998888", "Hola", m.id)
    # El scope de prueba no commitea; _mark_delivery muta el mismo objeto (identity map).
    assert m.delivery == "sent"


def test_delivery_marca_failed_si_truena(monkeypatch):
    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    m = _pending_out_msg(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    def boom(wa, window=None):
        def _s(p, txt):
            raise RuntimeError("lock ocupado")
        return _s

    monkeypatch.setattr(worker_main, "get_whatsapp_sender", boom)
    worker_main.send_human_message_blocking(t.id, "5215599998888", "Hola", m.id)
    assert m.delivery == "failed"


def test_delivery_marca_failed_si_no_hay_canal(monkeypatch):
    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst", config={})  # sin whatsapp
    session.add(t)
    session.flush()
    m = _pending_out_msg(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    worker_main.send_human_message_blocking(t.id, "5215599998888", "Hola", m.id)
    assert m.delivery == "failed"


def test_send_reminder_falla_marca_failed_sin_propagar(monkeypatch):
    """Bug que reportó José: al aprobar+enviar, el recordatorio se quedaba atorado. Causa: si el
    envío truena, la excepción propagaba y session_scope hacía rollback, perdiendo el estado. Fix:
    send_reminder_blocking atrapa el fallo, marca 'failed' y NO propaga."""
    from datetime import date

    from aiuda_core.models import Invoice, Reminder

    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    c = Customer(tenant_id=t.id, name="C", phone="5215599998888")
    session.add(c)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=c.id, folio="F-1", amount=100, currency="MXN",
                  issued_date=date.today(), due_date=date.today(), status="open")
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, agent="mariana", bucket="vence_pronto",
                 tone="amable", message="Recordatorio", channel="whatsapp", status="approved")
    session.add(r)
    session.flush()

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")

    def boom_sender(channel, wa, window=None):
        def _s(phone, text):
            raise RuntimeError("wacli caído")
        return _s

    monkeypatch.setattr(worker_main, "get_channel_sender", boom_sender)

    class _FakeEngine:
        def send(self, reminder, recipient, sender):
            from aiuda_core.agents.cleo.tools import send_approved_reminder

            return send_approved_reminder(reminder, lambda text: sender(recipient, text))

    monkeypatch.setattr(worker_main, "_build_engine", lambda s, tenant, run=None: _FakeEngine())

    worker_main.send_reminder_blocking(t.id, r.id)  # no debe lanzar
    assert r.status == "failed"
    # El motivo queda VISIBLE para la UI (qué pasó y por dónde), no un failed mudo.
    assert "wacli caído" in r.meta["motivo_fallo"]
    assert r.sent_at is None


def test_send_reminder_sin_canal_queda_aprobado_no_failed(monkeypatch):
    """Sin canal conectado no hay intento: el recordatorio queda APROBADO con su aviso
    ("se enviará cuando conectes WhatsApp") y el barrido lo despacha cuando haya canal.
    Antes se marcaba 'failed' y la UI lo pintaba en Enviados: doble mentira."""
    from datetime import date

    from aiuda_core.models import Invoice, Reminder

    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={})  # SIN integrations.whatsapp: canal no conectado
    session.add(t)
    session.flush()
    c = Customer(tenant_id=t.id, name="C", phone="5215599998888")
    session.add(c)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=c.id, folio="F-1", amount=100, currency="MXN",
                  issued_date=date.today(), due_date=date.today(), status="open")
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, agent="mariana", bucket="vence_pronto",
                 tone="amable", message="Recordatorio", channel="whatsapp", status="approved",
                 meta={"motivo_fallo": "resto de un intento viejo"})
    session.add(r)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))

    worker_main.send_reminder_blocking(t.id, r.id)

    assert r.status == "approved"  # no es un fallo: no se intentó nada
    assert r.sent_at is None
    assert "conectes WhatsApp" in r.meta["pendiente_canal"]
    assert "motivo_fallo" not in r.meta  # el veredicto viejo no contamina la espera


def test_barrido_aprobados_varados_despacha_cuando_hay_canal(monkeypatch):
    """El barrido horario re-dispara los 'approved' varados (aprobados sin canal en su
    momento): viejos sí, recientes no (evita chocar con el envío en background del
    approve), sombra no (retenidos a propósito), 'failed' jamás (ya hubo veredicto)."""
    from datetime import date, datetime, timedelta, timezone

    from aiuda_core.models import Invoice, Reminder

    session = _real_session()
    hace_30 = datetime.now(timezone.utc) - timedelta(minutes=30)

    def negocio(nombre, instancia, *, sombra=False):
        cfg = {"integrations": {"whatsapp": {"via": "wacli"}}}
        if sombra:
            cfg["modo_sombra"] = True
        t = Tenant(name=nombre, owner_phone="1", evolution_instance=instancia, config=cfg)
        session.add(t)
        session.flush()
        return t

    seq = iter(range(100, 200))

    def recordatorio(t, status, *, updated_at=hace_30):
        n = next(seq)
        c = Customer(tenant_id=t.id, name="C", phone=f"52155000000{n}")
        session.add(c)
        session.flush()
        inv = Invoice(tenant_id=t.id, customer_id=c.id, folio=f"F-{n}", amount=10, currency="MXN",
                      issued_date=date.today(), due_date=date.today(), status="open")
        session.add(inv)
        session.flush()
        r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                     message="m", channel="whatsapp", status=status)
        session.add(r)
        session.flush()
        r.updated_at = updated_at
        session.add(r)
        session.flush()
        return r

    normal = negocio("Normal", "i-1")
    en_sombra = negocio("Sombra", "i-2", sombra=True)
    viejo = recordatorio(normal, "approved")
    recordatorio(normal, "approved", updated_at=datetime.now(timezone.utc))  # reciente
    recordatorio(normal, "failed")  # ya con veredicto
    recordatorio(en_sombra, "approved")  # retenido por sombra

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    disparados: list = []
    monkeypatch.setattr(
        worker_main, "send_reminder_blocking",
        lambda tenant_id, reminder_id: disparados.append(reminder_id),
    )

    n = worker_main._sweep_stranded_approved(datetime.now(timezone.utc))

    assert n == 1
    assert disparados == [viejo.id]  # ni el reciente, ni el failed, ni el de sombra


def test_barrido_reintenta_pendientes_viejos_no_recientes_ni_fallidos(monkeypatch):
    from datetime import datetime, timezone

    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    viejo = _pending_out_msg(session, t, body="viejo", minutes_ago=30)
    reciente = _pending_out_msg(session, t, body="reciente", minutes_ago=1)
    fallido = _pending_out_msg(session, t, body="fallido", minutes_ago=30)
    fallido.delivery = "failed"
    session.add(fallido)
    session.flush()

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    sent: list = []
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda p, txt: sent.append(txt)),
    )
    n = worker_main._sweep_pending_sends(datetime.now(timezone.utc))
    assert n == 1  # solo el viejo pendiente
    assert sent == ["viejo"]
    assert viejo.delivery == "sent"        # reintentado y enviado
    assert reciente.delivery == "pending"  # muy nuevo: no se toca
    assert fallido.delivery == "failed"    # ya tuvo veredicto: no se reintenta


# --- Modo sombra: NADA sale a clientes reales, tampoco lo que escribe el humano ---


def test_sombra_retiene_mensaje_humano(monkeypatch):
    """La consola promete "Modo sombra activado: nada sale a clientes reales" y
    este camino la volvía mentira: el mensaje humano de la ficha/hilo salía por
    WhatsApp con la sombra prendida. Queda 'held' y el canal no se toca."""
    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"modo_sombra": True, "integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    m = _pending_out_msg(session, t)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    sent: list = []
    monkeypatch.setattr(
        worker_main, "get_whatsapp_sender",
        lambda wa, window=None: (lambda p, txt: sent.append(txt)),
    )
    worker_main.send_human_message_blocking(t.id, "5215599998888", m.body, m.id)
    assert sent == []  # no salió nada
    assert m.delivery == "held"  # y el hilo lo dice ('held' no se barre como pending)


def test_sombra_retiene_adjunto_humano(monkeypatch, tmp_path):
    """El adjunto no pasa por get_whatsapp_sender (usa WacliClient directo), así
    que aquí se observa _safe_send: con sombra el flujo NUNCA llega al canal."""
    session = _real_session()
    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"modo_sombra": True, "integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    intentos: list = []
    monkeypatch.setattr(worker_main, "_safe_send", lambda label, fn: intentos.append(label))
    carpeta = tmp_path / "att"
    carpeta.mkdir()
    archivo = carpeta / "factura.pdf"
    archivo.write_bytes(b"%PDF-1.4")
    worker_main.send_human_file_blocking(t.id, "5215599998888", str(archivo), "", "factura.pdf")
    assert intentos == []  # ni un intento de envío
    assert not archivo.exists()  # el temporal se limpia igual


# --- Bitácora: escribirle a un cliente deja rastro de quién lo hizo ---


def test_escribirle_al_cliente_deja_bitacora(client, db_session, monkeypatch):
    from aiuda_core.models import AuditLog

    t = _tenant(db_session, connected=True)
    c = _customer(db_session, t)
    monkeypatch.setattr(worker_main, "send_human_message_blocking", lambda *a: None)
    res = client.post(f"/v1/customers/{c.id}/messages", headers=HEADERS, json={"body": "Hola"})
    assert res.status_code == 200
    fila = db_session.scalar(select(AuditLog).where(AuditLog.action == "message.send"))
    assert fila is not None
    assert fila.tenant_id == t.id and fila.entity_id == c.id


def test_quitar_una_baja_deja_bitacora(client, db_session):
    from aiuda_core.models import AuditLog
    from aiuda_core.optout import mark_opt_out, opted_out

    t = _tenant(db_session, connected=True)
    c = _customer(db_session, t)
    mark_opt_out(db_session, t, c.phone)
    db_session.add(t)
    db_session.flush()

    res = client.post(f"/v1/customers/{c.id}/optout", headers=HEADERS, json={"activo": False})
    assert res.status_code == 200
    assert opted_out(db_session, t, c.phone) is None
    fila = db_session.scalar(select(AuditLog).where(AuditLog.action == "customer.optout_clear"))
    assert fila is not None and fila.entity_id == c.id


# --- Idempotencia del envío de recordatorios: el cobro no sale dos veces ---


def _reminder_listo(session, *, meta=None):
    from datetime import date

    from aiuda_core.models import Invoice, Reminder

    t = Tenant(name="T", owner_phone="1", evolution_instance="inst",
               config={"integrations": {"whatsapp": {"via": "wacli"}}})
    session.add(t)
    session.flush()
    c = Customer(tenant_id=t.id, name="C", phone="5215599998888")
    session.add(c)
    session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=c.id, folio="F-1", amount=100, currency="MXN",
                  issued_date=date.today(), due_date=date.today(), status="open")
    session.add(inv)
    session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, agent="mariana", bucket="vence_pronto",
                 tone="amable", message="Recordatorio", channel="whatsapp", status="approved",
                 meta=meta or {})
    session.add(r)
    session.flush()
    return t, r


class _EngineDirecto:
    """Engine mínimo: el camino real de envío (send_approved_reminder) sin LLM."""

    def send(self, reminder, recipient, sender):
        from aiuda_core.agents.cleo.tools import send_approved_reminder

        return send_approved_reminder(reminder, lambda text: sender(recipient, text))


def test_doble_disparo_no_manda_el_cobro_dos_veces(monkeypatch):
    """Dos clics en "Enviar ahora" agendan DOS tareas y ambas leían 'approved':
    el cliente recibía el mismo cobro dos veces (wacli tarda ~10s, la ventana es
    real). Con el candado en proceso, la tarea encimada ve el envío en curso y
    se va sin tocar el canal ni el estado; libre el vuelo, sale UNA vez."""
    session = _real_session()
    t, r = _reminder_listo(session)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    monkeypatch.setattr(worker_main, "_build_engine", lambda s, tenant, run=None: _EngineDirecto())

    sent: list = []
    monkeypatch.setattr(
        worker_main, "get_channel_sender",
        lambda channel, wa, window=None: (lambda phone, text: sent.append(text)),
    )

    # Otra tarea ya tiene este recordatorio en vuelo: la encimada no hace nada.
    worker_main._envios_en_curso.add(r.id)
    try:
        worker_main.send_reminder_blocking(t.id, r.id)
    finally:
        worker_main._envios_en_curso.discard(r.id)
    assert sent == []
    assert r.status == "approved"

    # Liberado el vuelo, el envío sale una sola vez.
    worker_main.send_reminder_blocking(t.id, r.id)
    assert sent == ["Recordatorio"]
    assert r.status == "sent"


def test_marca_en_vuelo_no_reenvia_a_ciegas(monkeypatch):
    """Un apagón entre el envío y el 'sent' dejaba el recordatorio 'approved' y el
    barrido de varados lo RE-DISPARABA: mismo cobro dos veces. La marca durable de
    en-vuelo lo vuelve 'failed' con motivo visible: tras una interrupción ambigua,
    reenviar es decisión del dueño, no del barrido."""
    session = _real_session()
    t, r = _reminder_listo(session, meta={"envio_en_curso": "2026-07-27T09:00:00+00:00"})
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    monkeypatch.setattr(worker_main, "_build_engine", lambda s, tenant, run=None: _EngineDirecto())
    sent: list = []
    monkeypatch.setattr(
        worker_main, "get_channel_sender",
        lambda channel, wa, window=None: (lambda phone, text: sent.append(text)),
    )
    worker_main.send_reminder_blocking(t.id, r.id)
    assert sent == []  # no se reenvió a ciegas
    assert r.status == "failed"
    assert "interrumpi" in r.meta["motivo_fallo"]
    assert "envio_en_curso" not in r.meta  # la marca no se queda pegada


def test_envio_normal_pone_y_limpia_la_marca_en_vuelo(monkeypatch):
    """La marca existe (y ya está commiteada) MIENTRAS el mensaje viaja — es lo
    que un apagón dejaría atrás — y se limpia al obtener veredicto."""
    session = _real_session()
    t, r = _reminder_listo(session)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(session))
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    monkeypatch.setattr(worker_main, "_build_engine", lambda s, tenant, run=None: _EngineDirecto())
    en_vuelo: list = []

    def sender(channel, wa, window=None):
        def _s(phone, text):
            en_vuelo.append((r.meta or {}).get("envio_en_curso"))
        return _s

    monkeypatch.setattr(worker_main, "get_channel_sender", sender)
    worker_main.send_reminder_blocking(t.id, r.id)
    assert en_vuelo and en_vuelo[0]  # la marca estaba puesta durante el vuelo
    assert r.status == "sent"
    assert "envio_en_curso" not in (r.meta or {})  # y se limpió con el veredicto
