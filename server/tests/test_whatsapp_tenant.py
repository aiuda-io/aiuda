"""Canal WhatsApp por tenant, de punta a punta con fakes de wacli/HTTP.

El criterio del backlog (§5): dos tenants con números/instancias distintas mandan
y reciben SIN cruzarse. Cubre:
- inbound wacli ruteado por instancia (y rechazo honesto del routing ambiguo),
- envío saliente por el store PROPIO de cada tenant (argv de wacli),
- opt-out por BAJA entrante (marca + confirmación determinista, sin LLM),
- recordatorio a cliente dado de baja → 'failed' con motivo, sin reintento solo,
- webhook oficial (Cloud API): verificación, firma obligatoria y routing por
  phone_number_id al tenant dueño del número.
"""

import hashlib
import hmac
import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_core.config import settings
from aiuda_core.connectors import wacli as wacli_mod
from aiuda_core.models import Base, Conversation, Customer, Message, Tenant
from aiuda_server.api.main import app, get_db

WEBHOOK_TOKEN = "secreto"


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
    monkeypatch.setattr(settings, "evolution_webhook_token", WEBHOOK_TOKEN)
    app.dependency_overrides[get_db] = lambda: db_session
    jobs: list[tuple] = []
    monkeypatch.setattr(
        worker_main, "process_incoming_message_blocking",
        lambda *a: jobs.append(("process_incoming_message", a)),
    )
    app.state.test_jobs = jobs
    yield TestClient(app)
    app.dependency_overrides.clear()


def _tenant(db, name, instance, *, connected=True) -> Tenant:
    config = {"api_key": f"k-{instance}"}
    if connected:
        config["integrations"] = {"whatsapp": {"via": "wacli", "instance": instance}}
    t = Tenant(name=name, owner_phone="5215500000000", evolution_instance=instance, config=config)
    db.add(t)
    db.flush()
    return t


def _scope_of(session):
    @contextmanager
    def scope():
        yield session

    return scope


# ---------- inbound wacli ruteado por instancia ----------

def test_inbound_con_instancia_cae_al_tenant_correcto(client, db_session):
    a = _tenant(db_session, "Negocio A", "inst-a")
    b = _tenant(db_session, "Negocio B", "inst-b")
    r1 = client.post(
        f"/v1/webhooks/wacli?token={WEBHOOK_TOKEN}",
        json={"phone": "5215511110001", "message": "hola A", "id": "W-A1", "instance": "inst-a"},
    )
    r2 = client.post(
        f"/v1/webhooks/wacli?token={WEBHOOK_TOKEN}",
        json={"phone": "5215522220002", "message": "hola B", "id": "W-B1", "instance": "inst-b"},
    )
    assert r1.json()["status"] == "accepted" and r2.json()["status"] == "accepted"
    conv_a = db_session.scalars(select(Conversation).where(Conversation.tenant_id == a.id)).all()
    conv_b = db_session.scalars(select(Conversation).where(Conversation.tenant_id == b.id)).all()
    assert [c.remote_phone for c in conv_a] == ["5215511110001"]
    assert [c.remote_phone for c in conv_b] == ["5215522220002"]  # sin cruzarse


def test_inbound_instancia_desconocida_404(client, db_session):
    _tenant(db_session, "Negocio A", "inst-a")
    r = client.post(
        f"/v1/webhooks/wacli?token={WEBHOOK_TOKEN}",
        json={"phone": "5215511110001", "message": "x", "instance": "inst-fantasma"},
    )
    assert r.status_code == 404


def test_inbound_sin_instancia_con_dos_conectados_es_ambiguo(client, db_session):
    """Con más de un negocio conectado NO se adivina el destinatario: entregar la
    conversación al negocio equivocado sería la fuga cross-tenant original."""
    _tenant(db_session, "Negocio A", "inst-a")
    _tenant(db_session, "Negocio B", "inst-b")
    r = client.post(
        f"/v1/webhooks/wacli?token={WEBHOOK_TOKEN}",
        json={"phone": "5215511110001", "message": "x"},
    )
    assert r.status_code == 409
    assert db_session.scalars(select(Message)).all() == []  # no cayó en ningún lado


def test_inbound_sin_instancia_con_uno_conectado_va_a_ese(client, db_session):
    _tenant(db_session, "Sin canal", "inst-x", connected=False)
    b = _tenant(db_session, "Conectado", "inst-b")
    r = client.post(
        f"/v1/webhooks/wacli?token={WEBHOOK_TOKEN}",
        json={"phone": "5215511110001", "message": "hola"},
    )
    assert r.json()["status"] == "accepted"
    msg = db_session.scalar(select(Message))
    assert msg.tenant_id == b.id


# ---------- envío: cada tenant por SU store, sin cruzarse ----------

def test_dos_tenants_envian_por_sus_stores_sin_cruzarse(db_session, monkeypatch):
    """Flujo REAL worker → channel → wacli (subprocess fake): el argv de cada envío
    lleva el --store de SU tenant. Ninguno sale por la sesión del otro."""
    monkeypatch.setattr(settings, "wacli_store_root", "/stores")
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    a = _tenant(db_session, "Negocio A", "inst-a")
    b = _tenant(db_session, "Negocio B", "inst-b")
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(db_session))

    class _Ok:
        returncode = 0
        stderr = ""
        stdout = ""

    commands: list[list[str]] = []
    monkeypatch.setattr(
        wacli_mod.subprocess, "run", lambda cmd, **kw: commands.append(cmd) or _Ok()
    )
    worker_main.send_human_message_blocking(a.id, "5215511110001", "Hola de A")
    worker_main.send_human_message_blocking(b.id, "5215522220002", "Hola de B")

    stores = [cmd[cmd.index("--store") + 1] for cmd in commands]
    assert stores == ["/stores/inst-a", "/stores/inst-b"]
    # y el destinatario de cada uno es el suyo
    assert "5215511110001@s.whatsapp.net" in commands[0]
    assert "5215522220002@s.whatsapp.net" in commands[1]


def test_tenant_sin_canal_no_sale_por_el_numero_de_otro(db_session, monkeypatch):
    """El corazón del fix cross-tenant: un negocio SIN WhatsApp conectado no envía
    nada, aunque otro negocio del mismo servidor sí tenga canal."""
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    _tenant(db_session, "Conectado", "inst-a")
    sin_canal = _tenant(db_session, "Sin canal", "inst-b", connected=False)
    monkeypatch.setattr(worker_main, "session_scope", _scope_of(db_session))
    llamadas: list = []
    monkeypatch.setattr(wacli_mod.subprocess, "run", lambda cmd, **kw: llamadas.append(cmd))

    conv = Conversation(tenant_id=sin_canal.id, remote_phone="5215599990000")
    db_session.add(conv)
    db_session.flush()
    m = Message(tenant_id=sin_canal.id, conversation_id=conv.id, direction="out",
                author="human", body="Hola", delivery="pending")
    db_session.add(m)
    db_session.flush()

    worker_main.send_human_message_blocking(sin_canal.id, "5215599990000", "Hola", m.id)
    assert llamadas == []  # wacli ni se tocó
    assert m.delivery == "failed"  # veredicto honesto, no silencio


# ---------- opt-out end-to-end ----------

def test_inbound_baja_marca_optout_y_confirma_sin_llm(db_session, monkeypatch):
    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    t = _tenant(db_session, "Negocio", "inst-a")
    conv = Conversation(tenant_id=t.id, remote_phone="5215587654321")
    db_session.add(conv)
    db_session.flush()
    msg = Message(tenant_id=t.id, conversation_id=conv.id, direction="in", body="BAJA")
    db_session.add(msg)
    db_session.flush()

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(db_session))

    class _Ok:
        returncode = 0
        stderr = ""
        stdout = ""

    enviados: list[list[str]] = []
    monkeypatch.setattr(
        wacli_mod.subprocess, "run", lambda cmd, **kw: enviados.append(cmd) or _Ok()
    )
    worker_main.process_incoming_message_blocking(t.id, msg.id)

    # Quedó registrado por match_key, en su propia tabla (ya no en el blob de config,
    # donde dos hilos escribiendo el mismo JSON podían borrar la baja).
    from aiuda_core.optout import claves_dadas_de_baja

    assert "5587654321" in claves_dadas_de_baja(db_session, t)
    # Confirmación determinista enviada y registrada en el hilo (sin tocar el LLM).
    assert len(enviados) == 1
    out = db_session.scalars(
        select(Message).where(Message.tenant_id == t.id, Message.direction == "out")
    ).all()
    assert len(out) == 1 and "recordatorios" in out[0].body


def test_recordatorio_a_cliente_dado_de_baja_falla_con_motivo(db_session, monkeypatch):
    from datetime import date

    from aiuda_core.models import Invoice, Reminder
    from aiuda_core.optout import mark_opt_out

    monkeypatch.setattr(settings, "wacli_sync_stop_cmd", "")
    monkeypatch.setattr(settings, "wacli_sync_start_cmd", "")
    t = _tenant(db_session, "Negocio", "inst-a")
    c = Customer(tenant_id=t.id, name="Cliente", phone="5215587654321")
    db_session.add(c)
    db_session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=c.id, folio="F-1", amount=100,
                  issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open")
    db_session.add(inv)
    db_session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Recordatorio", status="approved")
    db_session.add(r)
    db_session.flush()
    mark_opt_out(db_session, t, c.phone)

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(db_session))
    llamadas: list = []
    monkeypatch.setattr(wacli_mod.subprocess, "run", lambda cmd, **kw: llamadas.append(cmd))

    worker_main.send_reminder_blocking(t.id, r.id)
    assert llamadas == []  # no salió nada
    assert r.status == "failed"
    assert r.meta.get("motivo_fallo") == "opt-out"


# ---------- webhook oficial (Cloud API) ----------

def _waba_payload(phone_number_id="111222333", body="hola", wamid="wamid.T1"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA-ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [
                                {"profile": {"name": "Cliente"}, "wa_id": "5215587654321"}
                            ],
                            "messages": [
                                {
                                    "from": "5215587654321",
                                    "id": wamid,
                                    "timestamp": "1750000000",
                                    "text": {"body": body},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _firmado(body: dict, secret: str) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}


def test_waba_verificacion_get(client, monkeypatch):
    monkeypatch.setattr(settings, "waba_verify_token", "verifica-me")
    ok = client.get(
        "/v1/webhooks/whatsapp-cloud",
        params={"hub.mode": "subscribe", "hub.verify_token": "verifica-me", "hub.challenge": "123abc"},
    )
    assert ok.status_code == 200 and ok.text == "123abc"
    mal = client.get(
        "/v1/webhooks/whatsapp-cloud",
        params={"hub.mode": "subscribe", "hub.verify_token": "otra-cosa", "hub.challenge": "x"},
    )
    assert mal.status_code == 403


def test_waba_verificacion_sin_token_configurado_rechaza(client, monkeypatch):
    monkeypatch.setattr(settings, "waba_verify_token", "")
    r = client.get(
        "/v1/webhooks/whatsapp-cloud",
        params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"},
    )
    assert r.status_code == 403


def test_waba_post_sin_firma_valida_rechaza(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "waba_app_secret", "app-secreto")
    raw = json.dumps(_waba_payload()).encode()
    r = client.post(
        "/v1/webhooks/whatsapp-cloud",
        content=raw,
        headers={"X-Hub-Signature-256": "sha256=firma-falsa", "Content-Type": "application/json"},
    )
    assert r.status_code == 403
    # Y sin app secret configurado tampoco entra nada (no hay firma que validar).
    monkeypatch.setattr(settings, "waba_app_secret", "")
    r2 = client.post("/v1/webhooks/whatsapp-cloud", content=raw,
                     headers={"Content-Type": "application/json"})
    assert r2.status_code == 403


def test_waba_post_firmado_rutea_por_phone_number_id(client, db_session, monkeypatch):
    from aiuda_core.connectors.credentials import set_credential

    monkeypatch.setattr(settings, "waba_app_secret", "app-secreto")
    a = _tenant(db_session, "Oficial A", "inst-a", connected=False)
    b = _tenant(db_session, "Oficial B", "inst-b", connected=False)
    set_credential(db_session, a.id, "whatsapp_cloud",
                   {"access_token": "tokA", "phone_number_id": "111222333"})
    set_credential(db_session, b.id, "whatsapp_cloud",
                   {"access_token": "tokB", "phone_number_id": "999888777"})

    raw, headers = _firmado(_waba_payload(phone_number_id="999888777", body="hola B"), "app-secreto")
    r = client.post("/v1/webhooks/whatsapp-cloud", content=raw, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "accepted"

    msgs_a = db_session.scalars(select(Message).where(Message.tenant_id == a.id)).all()
    msgs_b = db_session.scalars(select(Message).where(Message.tenant_id == b.id)).all()
    assert msgs_a == [] and len(msgs_b) == 1  # cayó SOLO al dueño del número
    assert msgs_b[0].body == "hola B"
    # y el procesamiento se agendó para el tenant correcto
    assert app.state.test_jobs[-1][1][0] == b.id


def test_waba_post_es_idempotente(client, db_session, monkeypatch):
    from aiuda_core.connectors.credentials import set_credential

    monkeypatch.setattr(settings, "waba_app_secret", "app-secreto")
    a = _tenant(db_session, "Oficial", "inst-a", connected=False)
    set_credential(db_session, a.id, "whatsapp_cloud",
                   {"access_token": "tok", "phone_number_id": "111222333"})
    raw, headers = _firmado(_waba_payload(wamid="wamid.DUP"), "app-secreto")
    client.post("/v1/webhooks/whatsapp-cloud", content=raw, headers=headers)
    r2 = client.post("/v1/webhooks/whatsapp-cloud", content=raw, headers=headers)
    assert r2.json()["status"] == "ignored"
    assert len(db_session.scalars(select(Message).where(Message.tenant_id == a.id)).all()) == 1


def test_waba_numero_sin_negocio_se_ignora(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "waba_app_secret", "app-secreto")
    raw, headers = _firmado(_waba_payload(phone_number_id="000000000"), "app-secreto")
    r = client.post("/v1/webhooks/whatsapp-cloud", content=raw, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "ignored"


# ---------- activar la vía oficial ----------

def test_activar_cloud_sin_credenciales_409(client, db_session):
    _tenant(db_session, "Negocio", "inst-a", connected=False)
    r = client.post(
        "/v1/integrations/whatsapp-cloud/activate", headers={"X-API-Key": "k-inst-a"}
    )
    assert r.status_code == 409


def test_activar_cloud_marca_la_via(client, db_session):
    from aiuda_core.connectors.credentials import set_credential

    t = _tenant(db_session, "Negocio", "inst-a", connected=False)
    set_credential(db_session, t.id, "whatsapp_cloud",
                   {"access_token": "tok", "phone_number_id": "111"})
    r = client.post(
        "/v1/integrations/whatsapp-cloud/activate", headers={"X-API-Key": "k-inst-a"}
    )
    assert r.status_code == 200
    via = ((t.config or {}).get("integrations") or {}).get("whatsapp", {})
    assert via.get("via") == "whatsapp_cloud" and via.get("instance") == "inst-a"


# ---------- emparejar wacli: el store default es de UN solo negocio ----------

def test_qr_en_modo_mono_rechaza_al_segundo_negocio(client, db_session, monkeypatch):

    monkeypatch.setattr(settings, "wacli_store_root", "")  # modo mono: un solo store
    _tenant(db_session, "Dueño del número", "inst-a")  # ya conectado via wacli
    segundo = _tenant(db_session, "Segundo", "inst-b", connected=False)
    monkeypatch.setattr(settings, "workspace_id", segundo.id)
    r = client.post("/v1/integrations/whatsapp/qr")
    assert r.status_code == 409
    assert "otro negocio" in r.json()["detail"]


def test_qr_en_modo_multi_no_hay_conflicto(client, db_session, monkeypatch):
    import aiuda_server.api.whatsapp as wa_api

    monkeypatch.setattr(settings, "wacli_store_root", "/stores")
    _tenant(db_session, "A", "inst-a")
    b = _tenant(db_session, "B", "inst-b", connected=False)
    monkeypatch.setattr(settings, "workspace_id", b.id)
    # Con store propio no hay dueño único que defender; el QR sigue su curso normal
    # (aquí wacli no está en el PATH del test: 502 honesto, NO el 409 de conflicto).
    monkeypatch.setattr(wa_api, "_is_authenticated", lambda tenant: False)
    monkeypatch.setattr(wa_api, "_capture_qr", lambda tenant, deadline_s=15.0: None)
    r = client.post("/v1/integrations/whatsapp/qr")
    assert r.status_code == 502


# ---------- visibilidad y perillas: ficha, ajustes y prueba de conexión ----------

def test_ficha_muestra_opt_out_y_el_dueno_puede_reactivar(client, db_session):
    from aiuda_core.optout import mark_opt_out

    t = _tenant(db_session, "Negocio", "inst-a")
    c = Customer(tenant_id=t.id, name="Cliente", phone="5215587654321")
    db_session.add(c)
    db_session.flush()
    mark_opt_out(db_session, t, c.phone)
    db_session.add(t)
    db_session.flush()

    headers = {"X-API-Key": "k-inst-a"}
    ficha = client.get(f"/v1/customers/{c.id}", headers=headers).json()
    assert ficha["opt_out"] is not None and ficha["opt_out"]["via"] == "whatsapp"

    # Reactivar desde la ficha (decisión del dueño) y volver a dar de baja.
    r = client.post(f"/v1/customers/{c.id}/optout", headers=headers, json={"activo": False})
    assert r.json()["opt_out"] is None
    r = client.post(f"/v1/customers/{c.id}/optout", headers=headers, json={"activo": True})
    assert r.json()["opt_out"]["via"] == "consola"


def test_optout_de_cliente_sin_telefono_400(client, db_session):
    t = _tenant(db_session, "Negocio", "inst-a")
    c = Customer(tenant_id=t.id, name="Sin tel", phone=None)
    db_session.add(c)
    db_session.flush()
    r = client.post(
        f"/v1/customers/{c.id}/optout", headers={"X-API-Key": "k-inst-a"}, json={"activo": True}
    )
    assert r.status_code == 400


def test_ventana_envio_get_put_y_validacion(client, db_session):
    t = _tenant(db_session, "Negocio", "inst-a")
    headers = {"X-API-Key": "k-inst-a"}
    assert client.get("/v1/settings/ventana-envio", headers=headers).json()["ventana"] == ""
    ok = client.put(
        "/v1/settings/ventana-envio", headers=headers, json={"ventana": "09:00-20:00"}
    )
    assert ok.status_code == 200 and ok.json()["ventana"] == "09:00-20:00"
    assert (t.config or {}).get("ventana_envio") == "09:00-20:00"
    mal = client.put("/v1/settings/ventana-envio", headers=headers, json={"ventana": "temprano"})
    assert mal.status_code == 422
    off = client.put("/v1/settings/ventana-envio", headers=headers, json={"ventana": ""})
    assert off.status_code == 200 and (t.config or {}).get("ventana_envio") == ""


def test_probar_conexion_whatsapp_cloud_pega_a_meta(client, db_session, monkeypatch):
    """El tester convierte 'pendiente de verificar en vivo' en veredicto real: aquí
    con la Graph API simulada (fixture de la doc); en producción, contra Meta."""
    import httpx

    from aiuda_core.connectors import waba as waba_mod
    from aiuda_core.connectors.credentials import set_credential

    t = _tenant(db_session, "Negocio", "inst-a", connected=False)
    set_credential(db_session, t.id, "whatsapp_cloud",
                   {"access_token": "tok", "phone_number_id": "111222333"})
    monkeypatch.setattr(
        waba_mod.httpx, "get",
        lambda url, params=None, headers=None, timeout=None: httpx.Response(
            200, json={"verified_name": "Negocio", "display_phone_number": "+52 1 55 0000 0000"}
        ),
    )
    r = client.post("/v1/integrations/whatsapp_cloud/test", headers={"X-API-Key": "k-inst-a"})
    body = r.json()
    assert body["ok"] is True and "Negocio" in body["message"]

    # El veredicto queda persistido: el catálogo lo muestra como verificado.
    graph = client.get("/v1/integrations", headers={"X-API-Key": "k-inst-a"}).json()
    cloud = next(s for s in graph["systems"] if s["key"] == "whatsapp_cloud")
    assert cloud["verified"] == "ok" and cloud["connected"] is True


def test_catalogo_wacli_honesto_y_cloud_oficial(client, db_session):
    _tenant(db_session, "Negocio", "inst-a")
    graph = client.get("/v1/integrations").json()
    wacli = next(s for s in graph["systems"] if s["key"] == "whatsapp")
    cloud = next(s for s in graph["systems"] if s["key"] == "whatsapp_cloud")
    # wacli: tu número en tu máquina, con la nota honesta (sin alarmismo).
    assert "tu número" in wacli["rol"].lower() and wacli.get("warning")
    assert "riesgo es bajo" in wacli["warning"]
    assert "oficial" in cloud["name"].lower()
    # La vía oficial dice claro que necesita URL pública y que falta el estreno.
    assert "URL pública" in cloud["does"]
    assert "PENDIENTE de verificar" in cloud["does"]


def test_aprobar_por_whatsapp_a_cliente_dado_de_baja_no_pierde_la_respuesta(db_session, monkeypatch):
    """El dueño aprueba+envía desde WhatsApp un recordatorio de un cliente que YA se dio
    de baja: el recordatorio queda 'failed' con motivo y la respuesta al dueño NO se
    pierde (antes, la excepción habría hecho rollback de todo el turno)."""
    from datetime import date
    from types import SimpleNamespace

    from aiuda_core.models import Invoice, Reminder
    from aiuda_core.optout import mark_opt_out

    t = _tenant(db_session, "Negocio", "inst-a")
    t.owner_phone = "5215512345678"
    c = Customer(tenant_id=t.id, name="Cliente", phone="5215587654321")
    db_session.add(c)
    db_session.flush()
    inv = Invoice(tenant_id=t.id, customer_id=c.id, folio="F-1", amount=100,
                  issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open")
    db_session.add(inv)
    db_session.flush()
    r = Reminder(tenant_id=t.id, invoice_id=inv.id, bucket="vencida", tone="firme",
                 message="Recordatorio", status="approved")
    db_session.add(r)
    db_session.flush()
    mark_opt_out(db_session, t, c.phone)

    conv = Conversation(tenant_id=t.id, remote_phone="5215512345678")  # el dueño
    db_session.add(conv)
    db_session.flush()
    msg = Message(tenant_id=t.id, conversation_id=conv.id, direction="in", body="enviar 1")
    db_session.add(msg)
    db_session.flush()

    monkeypatch.setattr(worker_main, "session_scope", _scope_of(db_session))

    respuestas: list = []

    def fake_engine(session, tenant):
        from aiuda_core.engine.engine import CleoEngine

        engine = CleoEngine(session, tenant, runner=SimpleNamespace(_usage_callback=object()),
                            send_whatsapp=lambda p, txt: respuestas.append((p, txt)))
        return engine

    monkeypatch.setattr(worker_main, "_build_engine", fake_engine)
    monkeypatch.setattr(
        "aiuda_core.engine.owner.handle_owner_command",
        lambda s, tenant, body: SimpleNamespace(
            text="Enviado", send_reminders=[(r, c.phone)]
        ),
    )

    worker_main.process_incoming_message_blocking(t.id, msg.id)

    assert respuestas == [("5215512345678", "Enviado")]  # la respuesta al dueño salió
    assert r.status == "failed" and r.meta.get("motivo_fallo") == "opt-out"
