import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.models import Base, Invoice, Message, Reminder, Tenant, Customer
from aiuda_server.api.main import app, get_db


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
    monkeypatch.setattr(settings, "evolution_webhook_token", "secreto")
    app.dependency_overrides[get_db] = lambda: db_session
    # Modo inline: el trabajo se difiere con BackgroundTasks, no a una
    # cola. Mockeamos las funciones _blocking para registrar la llamada sin tocar el
    # LLM; el TestClient ejecuta las BackgroundTasks tras responder.
    import aiuda_server.worker.main as worker

    jobs: list[tuple[str, tuple]] = []
    monkeypatch.setattr(
        worker, "process_incoming_message_blocking",
        lambda *a: jobs.append(("process_incoming_message", a)),
    )
    monkeypatch.setattr(
        worker, "send_reminder_blocking",
        lambda *a: jobs.append(("send_reminder", a)),
    )
    monkeypatch.setattr(
        worker, "send_human_message_blocking",
        lambda *a: jobs.append(("send_human_message", a)),
    )
    monkeypatch.setattr(
        worker, "send_human_file_blocking",
        lambda *a: jobs.append(("send_human_file", a)),
    )
    app.state.queue = None
    app.state.test_jobs = jobs
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant(db_session):
    t = Tenant(
        name="Demo SA",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={"api_key": "k-demo"},
    )
    db_session.add(t)
    db_session.flush()
    return t


WEBHOOK_PAYLOAD = {
    "event": "messages.upsert",
    "instance": "demo",
    "data": {
        "key": {"remoteJid": "5215587654321@s.whatsapp.net", "fromMe": False, "id": "MSG1"},
        "message": {"conversation": "hola, ¿cuánto debo?"},
    },
}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_webhook_rechaza_token_invalido(client, tenant):
    response = client.post("/v1/webhooks/evolution?token=malo", json=WEBHOOK_PAYLOAD)
    assert response.status_code == 401


def test_webhook_persiste_y_procesa_inline(client, db_session, tenant):
    response = client.post("/v1/webhooks/evolution?token=secreto", json=WEBHOOK_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    message = db_session.scalar(select(Message).where(Message.tenant_id == tenant.id))
    assert message.body == "hola, ¿cuánto debo?"
    # La BackgroundTask se disparó tras responder (procesamiento inline, sin cola).
    assert app.state.test_jobs[0][0] == "process_incoming_message"


def test_webhook_es_idempotente(client, db_session, tenant):
    client.post("/v1/webhooks/evolution?token=secreto", json=WEBHOOK_PAYLOAD)
    response = client.post("/v1/webhooks/evolution?token=secreto", json=WEBHOOK_PAYLOAD)
    assert response.json()["status"] == "duplicate"
    messages = db_session.scalars(select(Message).where(Message.tenant_id == tenant.id)).all()
    assert len(messages) == 1


def test_webhook_wacli_normaliza_el_telefono(client, db_session, tenant):
    from aiuda_core.models import Conversation

    res = client.post(
        "/v1/webhooks/wacli?token=secreto",
        json={"phone": "55 1234 5678", "message": "hola", "id": "W1"},
    )
    assert res.status_code == 200 and res.json()["status"] == "accepted"
    conv = db_session.scalar(select(Conversation).where(Conversation.tenant_id == tenant.id))
    # "55 1234 5678" (local de 10) → "5215512345678": dígitos país+número canónicos.
    assert conv.remote_phone == "5215512345678"


def test_modo_sombra_toggle(client, db_session, tenant):
    headers = {"X-API-Key": "k-demo"}
    assert client.get("/v1/settings/modo-sombra", headers=headers).json()["modo_sombra"] is False
    put = client.put("/v1/settings/modo-sombra", headers=headers, json={"activo": True})
    assert put.status_code == 200 and put.json()["modo_sombra"] is True
    assert client.get("/v1/settings/modo-sombra", headers=headers).json()["modo_sombra"] is True
    db_session.refresh(tenant)
    assert tenant.config.get("modo_sombra") is True


def _make_reminder(db_session, tenant, status="pending_approval"):
    from datetime import date

    customer = Customer(tenant_id=tenant.id, name="C", phone="5215500000000")
    db_session.add(customer)
    db_session.flush()
    invoice = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio="F-1",
        amount=100,
        issued_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
    )
    db_session.add(invoice)
    db_session.flush()
    reminder = Reminder(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        bucket="vencida",
        tone="firme",
        message="Recordatorio",
        status=status,
    )
    db_session.add(reminder)
    db_session.flush()
    return reminder


def test_conciliacion_propone_y_confirma(client, db_session, tenant):
    """Diego propone; el humano confirma; la factura se marca pagada (no antes)."""
    from datetime import date

    from aiuda_core.models import Payment

    headers = {"X-API-Key": "k-demo"}
    cust = Customer(tenant_id=tenant.id, name="Papelería Bic", phone="5215511110001")
    db_session.add(cust)
    db_session.flush()
    inv = Invoice(
        tenant_id=tenant.id, customer_id=cust.id, folio="M-104", amount=17073.60,
        issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open",
    )
    db_session.add(inv)
    db_session.flush()
    pay = Payment(
        tenant_id=tenant.id, amount=17073.60, currency="MXN", paid_at=date(2026, 6, 15),
        source="stripe", counterparty="PAPELERIA BIC", status="pendiente",
    )
    db_session.add(pay)
    db_session.flush()

    listed = client.get("/v1/reconciliation", headers=headers).json()
    assert listed["count"] == 1
    item = listed["pending"][0]
    assert item["proposal"]["folio"] == "M-104"
    assert item["proposal"]["cuadra"] is True

    # La factura sigue abierta hasta que el humano confirma.
    db_session.refresh(inv)
    assert inv.status == "open"

    res = client.post(
        f"/v1/reconciliation/{pay.id}/confirm",
        headers=headers,
        json={"invoice_id": inv.id},
    )
    assert res.status_code == 200
    assert res.json()["invoice"]["status"] == "paid"
    db_session.refresh(inv)
    db_session.refresh(pay)
    assert inv.status == "paid" and inv.paid_source == "stripe"
    assert pay.status == "conciliado" and pay.invoice_id == inv.id

    # Ya conciliado: no se puede de nuevo.
    again = client.post(
        f"/v1/reconciliation/{pay.id}/confirm", headers=headers, json={"invoice_id": inv.id}
    )
    assert again.status_code == 409


def test_conciliacion_ignorar(client, db_session, tenant):
    from datetime import date

    from aiuda_core.models import Payment

    headers = {"X-API-Key": "k-demo"}
    pay = Payment(
        tenant_id=tenant.id, amount=50, currency="MXN", paid_at=date(2026, 6, 15),
        source="banco", status="pendiente",
    )
    db_session.add(pay)
    db_session.flush()
    res = client.post(f"/v1/reconciliation/{pay.id}/ignore", headers=headers)
    assert res.status_code == 200 and res.json()["status"] == "ignorado"
    # Ya no aparece en la bandeja.
    assert client.get("/v1/reconciliation", headers=headers).json()["count"] == 0


def test_listar_y_aprobar_recordatorio(client, db_session, tenant):
    reminder = _make_reminder(db_session, tenant)
    headers = {"X-API-Key": "k-demo"}

    listed = client.get("/v1/reminders", headers=headers).json()
    assert [r["id"] for r in listed] == [reminder.id]

    approved = client.post(f"/v1/reminders/{reminder.id}/approve", headers=headers)
    assert approved.json()["status"] == "approved"
    assert ("send_reminder", (tenant.id, reminder.id)) in app.state.test_jobs


def test_aprobar_sin_canal_responde_estado_final_honesto(client, db_session, tenant):
    """El tenant no tiene canal conectado: la respuesta del approve lo dice de una
    (aprobado, pendiente de canal, con el aviso para el toast), en vez de fingir que
    el envío va en camino y amanecer 'failed'."""
    reminder = _make_reminder(db_session, tenant)
    res = client.post(f"/v1/reminders/{reminder.id}/approve", headers={"X-API-Key": "k-demo"})
    body = res.json()
    assert body["status"] == "approved"
    assert body["delivery"] == "pendiente_canal"
    assert "conectes WhatsApp" in body["aviso"]


def test_lista_expone_sent_at_solo_en_enviados(client, db_session, tenant):
    """La pestaña "Enviados" de la consola deriva de sent_at REAL: la lista lo expone
    y solo lo que salió de verdad lo trae; un aprobado retenido viene sin sent_at."""
    from aiuda_core.models import utcnow

    enviado = _make_reminder(db_session, tenant, status="sent")
    enviado.sent_at = utcnow()
    aprobado = Reminder(
        tenant_id=tenant.id, bucket="vencida", tone="firme",
        message="m", status="approved",
    )
    db_session.add(aprobado)
    db_session.flush()
    headers = {"X-API-Key": "k-demo"}
    [s] = client.get("/v1/reminders?status=sent", headers=headers).json()
    assert s["sent_at"] is not None
    [a] = client.get("/v1/reminders?status=approved", headers=headers).json()
    assert a["sent_at"] is None and a["motivo_fallo"] is None and a["pendiente"] is None


def test_enviar_aprobado_varado_dispara_envio(client, db_session, tenant):
    """Un aprobado que quedó sin salir (retenido en sombra y luego apagada) se puede
    reenviar sin re-aprobar: /send re-dispara send_reminder_blocking. No cambia de
    estado (sigue 'approved' hasta que el envío en background lo marque 'sent')."""
    reminder = _make_reminder(db_session, tenant, status="approved")
    res = client.post(f"/v1/reminders/{reminder.id}/send", headers={"X-API-Key": "k-demo"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert ("send_reminder", (tenant.id, reminder.id)) in app.state.test_jobs


def test_enviar_rechaza_si_no_esta_aprobado(client, db_session, tenant):
    """Solo un 'approved' puede reenviarse: un pending_approval no dispara envío (409)."""
    reminder = _make_reminder(db_session, tenant, status="pending_approval")
    res = client.post(f"/v1/reminders/{reminder.id}/send", headers={"X-API-Key": "k-demo"})
    assert res.status_code == 409
    assert ("send_reminder", (tenant.id, reminder.id)) not in app.state.test_jobs


def test_aprobar_con_edicion_captura_la_correccion(client, db_session, tenant):
    """El humano edita el borrador antes de enviar: se envía SU versión y se guarda la señal."""
    from sqlalchemy import select

    from aiuda_core.models import AgentFeedback

    reminder = _make_reminder(db_session, tenant)
    headers = {"X-API-Key": "k-demo"}
    editado = "Qué tal, ¿le ayudo a ponerse al corriente con su saldo?"
    res = client.post(
        f"/v1/reminders/{reminder.id}/approve", headers=headers, json={"message": editado}
    )
    assert res.json()["status"] == "approved"
    db_session.refresh(reminder)
    assert reminder.message == editado  # se envía la versión del humano
    fb = db_session.scalars(
        select(AgentFeedback).where(AgentFeedback.reminder_id == reminder.id)
    ).one()
    assert fb.decision == "edited"
    assert fb.draft_original == "Recordatorio" and fb.final_text == editado


def test_aprobar_sin_edicion_queda_approved(client, db_session, tenant):
    from sqlalchemy import select

    from aiuda_core.models import AgentFeedback

    reminder = _make_reminder(db_session, tenant)
    client.post(f"/v1/reminders/{reminder.id}/approve", headers={"X-API-Key": "k-demo"})
    fb = db_session.scalars(
        select(AgentFeedback).where(AgentFeedback.reminder_id == reminder.id)
    ).one()
    assert fb.decision == "approved" and fb.final_text == "Recordatorio"


def test_rechazar_captura_senal(client, db_session, tenant):
    from sqlalchemy import select

    from aiuda_core.models import AgentFeedback

    reminder = _make_reminder(db_session, tenant)
    client.post(f"/v1/reminders/{reminder.id}/reject", headers={"X-API-Key": "k-demo"})
    fb = db_session.scalars(
        select(AgentFeedback).where(AgentFeedback.reminder_id == reminder.id)
    ).one()
    assert fb.decision == "rejected" and fb.final_text is None


def test_rechazado_se_puede_corregir_y_enviar(client, db_session, tenant):
    """Rechazar no es un callejón sin salida: el dueño corrige el borrador y lo envía."""
    reminder = _make_reminder(db_session, tenant)
    headers = {"X-API-Key": "k-demo"}
    client.post(f"/v1/reminders/{reminder.id}/reject", headers=headers)
    db_session.refresh(reminder)
    assert reminder.status == "rejected"  # queda visible, no desaparece
    res = client.post(
        f"/v1/reminders/{reminder.id}/approve", headers=headers, json={"message": "Versión corregida"}
    )
    assert res.status_code == 200
    db_session.refresh(reminder)
    assert reminder.status == "approved" and reminder.message == "Versión corregida"


def test_learning_summary_refleja_aprendizaje(client, db_session, tenant):
    headers = {"X-API-Key": "k-demo"}

    def bare(msg):  # recordatorio sin cliente (evita el teléfono único del helper)
        r = Reminder(
            tenant_id=tenant.id, bucket="vencida", tone="firme",
            message=msg, status="pending_approval",
        )
        db_session.add(r)
        db_session.flush()
        return r

    r1 = bare("Recordatorio uno")
    client.post(f"/v1/reminders/{r1.id}/approve", headers=headers, json={"message": "otra redacción"})
    r2 = bare("Recordatorio dos")
    client.post(f"/v1/reminders/{r2.id}/approve", headers=headers)
    s = client.get("/v1/learning/summary", headers=headers).json()
    assert s["edited"] == 1 and s["approved"] == 1
    assert s["tasaSinEditar"] == 0.5  # 1 sin editar de 2 enviados
    assert len(s["recientes"]) == 1


def _open_invoice(db_session, tenant):
    from datetime import date

    customer = Customer(tenant_id=tenant.id, name="C", phone="5215500000000")
    db_session.add(customer)
    db_session.flush()
    invoice = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio="F-1",
        amount=100,
        issued_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        status="open",
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def _patch_draft(monkeypatch, status):
    """Sustituye draft_reminder para no tocar el LLM; devuelve un reminder con el estado dado."""
    from aiuda_core.engine.engine import CleoEngine

    def fake_draft(self, invoice, customer, today, broken_promise=None):
        r = Reminder(
            tenant_id=self.tenant.id,
            invoice_id=invoice.id,
            bucket="vencida",
            tone="firme",
            message="Recordatorio",
            status=status,
        )
        self.session.add(r)
        self.session.flush()
        return r

    monkeypatch.setattr(CleoEngine, "draft_reminder", fake_draft)


def test_recordar_ahora_auto_aprobado_encola_el_envio(client, db_session, tenant, monkeypatch):
    # Si el auto-envío del tenant deja el recordatorio aprobado, el endpoint debe encolar el
    # envío; si no, la corrida diaria lo ve "activo" y lo salta, y nunca sale.
    invoice = _open_invoice(db_session, tenant)
    _patch_draft(monkeypatch, status="approved")

    res = client.post(f"/v1/invoices/{invoice.id}/remind", headers={"X-API-Key": "k-demo"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert ("send_reminder", (tenant.id, res.json()["id"])) in app.state.test_jobs


def test_recordar_ahora_pendiente_no_encola(client, db_session, tenant, monkeypatch):
    # El caso normal (sin auto-envío): queda en pending_approval y NO se encola nada.
    invoice = _open_invoice(db_session, tenant)
    _patch_draft(monkeypatch, status="pending_approval")

    res = client.post(f"/v1/invoices/{invoice.id}/remind", headers={"X-API-Key": "k-demo"})
    assert res.status_code == 200
    assert res.json()["status"] == "pending_approval"
    assert not any(j[0] == "send_reminder" for j in app.state.test_jobs)


def test_reminders_y_promises_traen_customer_id(client, db_session, tenant):
    """Centro de mando usa customer_id para el panel de contexto (api.customerDetail)."""
    from datetime import date

    from aiuda_core.models import PaymentPromise

    headers = {"X-API-Key": "k-demo"}
    reminder = _make_reminder(db_session, tenant)
    r = client.get("/v1/reminders", headers=headers).json()[0]
    assert r["customer_id"] is not None
    assert r["invoice_id"] is not None

    promise = PaymentPromise(
        tenant_id=tenant.id, invoice_id=reminder.invoice_id,
        promised_date=date(2026, 6, 30), note="paga el viernes",
    )
    db_session.add(promise)
    db_session.flush()
    p = client.get("/v1/promises", headers=headers).json()[0]
    assert p["customer_id"] == r["customer_id"]


def test_aprobar_dos_veces_da_409(client, db_session, tenant):
    reminder = _make_reminder(db_session, tenant)
    headers = {"X-API-Key": "k-demo"}
    client.post(f"/v1/reminders/{reminder.id}/approve", headers=headers)
    second = client.post(f"/v1/reminders/{reminder.id}/approve", headers=headers)
    assert second.status_code == 409


def test_endpoints_locales_sin_api_key(client, db_session, tenant):
    # En local no hay API keys: el workspace único responde directo.
    assert client.get("/v1/reminders").status_code == 200


def test_customer_detail_y_mensaje(client, db_session, tenant):
    from datetime import date

    headers = {"X-API-Key": "k-demo"}
    cust = Customer(tenant_id=tenant.id, name="Ferreteria", phone="5215511112222")
    db_session.add(cust)
    db_session.flush()
    db_session.add(
        Invoice(
            tenant_id=tenant.id,
            customer_id=cust.id,
            folio="F-9",
            amount=500,
            issued_date=date(2026, 5, 1),
            due_date=date(2026, 5, 31),
        )
    )
    db_session.flush()

    detail = client.get(f"/v1/customers/{cust.id}", headers=headers).json()
    assert detail["name"] == "Ferreteria"
    assert len(detail["invoices"]) == 1
    assert detail["conversation_id"] is None  # aun sin hilo

    # Escribirle crea la conversacion y guarda el mensaje
    sent = client.post(
        f"/v1/customers/{cust.id}/messages",
        headers=headers,
        json={"body": "Hola, le recordamos su saldo."},
    ).json()
    assert sent["author"] == "human" and sent["direction"] == "out"

    again = client.get(f"/v1/customers/{cust.id}", headers=headers).json()
    assert again["conversation_id"] is not None
    assert len(again["messages"]) == 1


def test_editar_cliente_guarda_datos_extra(client, db_session, tenant):
    """La edición es tan flexible como el importador: los datos extra (meta) se
    editan/agregan, y NO se inyectan al maestro (son atributos propios)."""
    headers = {"X-API-Key": "k-demo"}
    cust = Customer(
        tenant_id=tenant.id, name="Joyería", phone="5215512345678",
        meta={"RFC": "ABC800101", "Zona": "Norte"},
    )
    db_session.add(cust)
    db_session.flush()

    res = client.put(
        f"/v1/customers/{cust.id}",
        headers=headers,
        json={"meta": {"RFC": "ABC800101", "Zona": "Sur", "Vendedor": "Luis"}},
    )
    assert res.status_code == 200
    assert res.json()["writeback"] == []  # meta no va al write-back

    detail = client.get(f"/v1/customers/{cust.id}", headers=headers).json()
    assert detail["meta"]["Zona"] == "Sur"
    assert detail["meta"]["Vendedor"] == "Luis"
    # Valor vacío se descarta (quitar un campo = dejarlo en blanco)
    res2 = client.put(
        f"/v1/customers/{cust.id}", headers=headers,
        json={"meta": {"RFC": "ABC800101", "Zona": "Sur"}},
    )
    assert res2.status_code == 200
    assert "Vendedor" not in client.get(f"/v1/customers/{cust.id}", headers=headers).json()["meta"]


def test_canales_registro_y_no_vivos():
    from aiuda_core.connectors.channel import CHANNELS, LIVE_CHANNELS, get_channel_sender

    assert {"whatsapp", "correo", "sms"} <= set(CHANNELS)
    assert LIVE_CHANNELS == {"whatsapp"}  # solo WhatsApp tiene sender hoy
    assert get_channel_sender("correo", "inst") is None  # por conectar
    assert get_channel_sender("sms", "inst") is None


def test_canales_disponibles_por_recordatorio():
    from aiuda_server.api.main import _available_channels

    cust = Customer(tenant_id="t", name="X", phone="5215512345678", email="x@y.com")
    chs = {c["key"]: c for c in _available_channels(cust, None)}
    assert chs["whatsapp"]["connected"] is True  # vivo + tiene teléfono
    assert chs["correo"]["connected"] is False  # tiene correo pero sin sender
    assert chs["sms"]["connected"] is False

    sin_tel = Customer(tenant_id="t", name="Y", phone="", email=None)
    chs2 = {c["key"]: c for c in _available_channels(sin_tel, None)}
    assert chs2["whatsapp"]["connected"] is False  # sin dato de contacto
def test_editar_cliente_encola_writeback(client, db_session, tenant):
    from aiuda_core.models import OutboxEntry
    headers = {"X-API-Key": "k-demo"}
    cust = Customer(
        tenant_id=tenant.id,
        name="Odoo Cliente",
        phone="5215533334444",
        presence={"odoo": {"ref": "res.partner/12"}},
    )
    db_session.add(cust)
    db_session.flush()

    res = client.put(
        f"/v1/customers/{cust.id}",
        headers=headers,
        json={"name": "Odoo Cliente SA"},
    ).json()
    assert res["name"] == "Odoo Cliente SA"
    assert res["writeback"] == ["odoo"]

    outbox = db_session.scalars(
        OutboxEntry.__table__.select().where(OutboxEntry.action == "actualizar_cliente")
    ).all()
    assert len(outbox) == 1


def test_editar_cliente_telefono_duplicado_409(client, db_session, tenant):
    headers = {"X-API-Key": "k-demo"}
    a = Customer(tenant_id=tenant.id, name="A", phone="5215500001111")
    b = Customer(tenant_id=tenant.id, name="B", phone="5215500002222")
    db_session.add_all([a, b])
    db_session.flush()
    res = client.put(f"/v1/customers/{b.id}", headers=headers, json={"phone": "5215500001111"})
    assert res.status_code == 409


def test_systems_del_ayudante(client, tenant):
    """A qué sistemas llega un ayudante. Sale de sus aiuditas, no de un rol de fábrica."""
    a = client.post(
        "/v1/ayudantes",
        json={"name": "Male", "aiuditas": ["cobranza.consultar_cartera"]},
        headers={"X-API-Key": "k-demo"},
    ).json()
    res = client.get(f"/v1/ayudantes/{a['id']}/systems", headers={"X-API-Key": "k-demo"})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Male"
    assert any(s["key"] == "odoo" for s in body["systems"])
    assert client.get("/v1/ayudantes/zzz/systems", headers={"X-API-Key": "k-demo"}).status_code == 404
