"""E2E de los flujos críticos (§13), de la API al efecto final, sin red.

App completa con SQLite en memoria + TestClient. La diferencia con los tests de
endpoint existentes: aquí NO se mockea el worker — el BackgroundTask corre de
verdad contra la MISMA base (session_scope parcheado) y solo se fakea el borde
externo (wacli como sender, Belvo como transporte HTTP grabado).

Flujos:
1. aprobar -> enviar WhatsApp: approve por API dispara send_reminder_blocking
   real; el fake de wacli registra el envío y el recordatorio queda 'sent'.
2. importar hoja -> cartera: analyze (IA fake propone tipo+mapeo) -> commit ->
   la cartera y el directorio existen por API.
3. detectar pago -> conciliar -> cerrar factura: detectar_pagos con la respuesta
   de Belvo (fixture de contrato) crea el pago pendiente; Diego propone por API;
   el humano confirma; la factura se cierra verificada con write-back encolado.
4. crear conexión a la medida -> ingesta: SKIP honesto (la rebanada §0 no está
   en esta base; ver el skip para el detalle).
"""

import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_server.api.main import app, get_db
from aiuda_core.models import (
    AuditLog,
    Base,
    Customer,
    Invoice,
    OutboxEntry,
    Payment,
    Reminder,
    Tenant,
)

HEADERS = {"X-API-Key": "k-demo"}
BELVO_FIXTURE = Path(__file__).parent.parent.parent / "core/tests/data/belvo_transacciones.json"


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
    app.dependency_overrides[get_db] = lambda: db_session
    app.state.queue = None  # modo inline: BackgroundTasks, sin cola

    # El worker corre DE VERDAD sobre la misma base del test (no un mock que
    # solo registra argumentos): así el E2E cubre approve -> background -> envío.
    # Como el session_scope real: commit al salir (si no, lo que el worker marcó
    # se pierde en el siguiente refresh) y rollback si truena.
    @contextmanager
    def _scope():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr(worker_main, "session_scope", _scope)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant(db_session):
    t = Tenant(
        name="Demo SA",
        owner_phone="5215512345678",
        evolution_instance="demo",
        # WhatsApp conectado vía wacli: el flujo de envío exige canal del tenant.
        config={"api_key": "k-demo", "integrations": {"whatsapp": {"via": "wacli"}}},
    )
    db_session.add(t)
    db_session.flush()
    return t


def _factura(db, tenant, *, nombre, telefono, folio, monto, vence) -> tuple[Customer, Invoice]:
    c = Customer(tenant_id=tenant.id, name=nombre, phone=telefono)
    db.add(c)
    db.flush()
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=c.id,
        folio=folio,
        amount=monto,
        issued_date=date(2026, 5, 20),
        due_date=vence,
    )
    db.add(inv)
    db.flush()
    return c, inv


# --------------------------------------------------------------------------- #
# Flujo 1: aprobar -> enviar WhatsApp                                          #
# --------------------------------------------------------------------------- #


def test_aprobar_dispara_envio_real_por_wacli(client, db_session, tenant, monkeypatch):
    customer, invoice = _factura(
        db_session, tenant,
        nombre="Ferretería El Martillo", telefono="5215587654321",
        folio="F-810", monto=12500.50, vence=date(2026, 6, 1),
    )
    reminder = Reminder(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        bucket="vencida",
        tone="firme",
        message="Su factura F-810 por $12,500.50 MXN presenta atraso; ¿acordamos fecha de pago?",
        status="pending_approval",
    )
    db_session.add(reminder)
    db_session.flush()

    # Borde externo: el sender de wacli. resolve_whatsapp y el gating por canal
    # del tenant corren de verdad; solo el binario wacli se sustituye.
    envios: list[tuple] = []
    def _fake_sender(channel, wa, window=None):
        assert channel == "whatsapp" and wa is not None and wa.provider == "wacli"
        return lambda phone, text: envios.append((phone, text))

    monkeypatch.setattr(worker_main, "get_channel_sender", _fake_sender)

    res = client.post(f"/v1/reminders/{reminder.id}/approve", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["status"] == "approved"  # lo que vio la consola al instante
    assert res.json()["delivery"] == "encolado"  # canal listo: el envío va en camino
    assert res.json()["aviso"] is None

    # El BackgroundTask ya corrió (TestClient lo ejecuta tras responder): el
    # envío salió por el canal del tenant y el estado avanzó a 'sent'.
    db_session.refresh(reminder)
    assert reminder.status == "sent"
    assert reminder.sent_at is not None
    assert envios == [("5215587654321", reminder.message)]
    # Auditoría del approve (con el canal resuelto), trazable.
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant.id, AuditLog.action == "reminder.approve"
        )
    )
    assert audit is not None and audit.entity_id == reminder.id


def test_aprobar_sin_canal_queda_aprobado_con_aviso_no_failed(client, db_session, monkeypatch):
    """Sin canal conectado, aprobar NO es un fallo: no se intentó nada. Queda
    'approved' con el aviso honesto ("se enviará cuando conectes WhatsApp"), sin
    sent_at, y la respuesta del API refleja el estado FINAL (nada de decir approved
    y amanecer failed). El barrido horario lo despacha cuando haya canal. 'failed'
    se reserva para un intento REAL de envío que tronó."""
    t = Tenant(
        name="Sin Canal SA", owner_phone="5215500000001",
        evolution_instance="x", config={"api_key": "k-demo"},  # SIN integrations
    )
    db_session.add(t)
    db_session.flush()
    customer, invoice = _factura(
        db_session, t, nombre="Cliente", telefono="5215599990000",
        folio="F-1", monto=100.0, vence=date(2026, 6, 1),
    )
    reminder = Reminder(
        tenant_id=t.id, invoice_id=invoice.id, bucket="vencida", tone="firme",
        message="m", status="pending_approval",
    )
    db_session.add(reminder)
    db_session.flush()

    res = client.post(f"/v1/reminders/{reminder.id}/approve", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "approved"
    assert body["delivery"] == "pendiente_canal"
    assert "conectes WhatsApp" in body["aviso"]

    # El BackgroundTask ya corrió: sin sender no hay intento, queda aprobado y honesto.
    db_session.refresh(reminder)
    assert reminder.status == "approved"
    assert reminder.sent_at is None
    assert "conectes WhatsApp" in reminder.meta["pendiente_canal"]

    # La lista expone el aviso para la UI (pestaña "Sin enviar", nunca "Enviados").
    listado = client.get("/v1/reminders?status=approved", headers=HEADERS).json()
    assert listado[0]["id"] == reminder.id
    assert listado[0]["sent_at"] is None
    assert "conectes WhatsApp" in listado[0]["pendiente"]


# --------------------------------------------------------------------------- #
# Flujo 2: importar hoja -> cartera                                            #
# --------------------------------------------------------------------------- #

CSV_FACTURAS = (
    "Folio,Cliente,Celular,Total,Emision,Vence\n"
    "M-201,Papelería Bic,55 1111 0001,17073.60,2026-06-01,2026-06-20\n"
    "M-202,Tornillos MX,55 2222 0002,4000.00,2026-06-05,2026-07-15\n"
).encode()


class FakeImportRunner:
    """Hace lo que la IA de mapeo hace en vivo, determinista (sin red)."""

    _usage_callback = None

    def model_for(self, role):
        return f"fake-{role}"

    def complete(self, system, user, *, model=None, role="triage", task="", max_tokens=1024):
        if task == "clasificar_archivo":
            return '{"tipo": "facturas", "confianza": 0.93}'
        if task == "mapear_archivo":
            return json.dumps(
                {
                    "folio": "Folio",
                    "cliente": "Cliente",
                    "telefono": "Celular",
                    "monto": "Total",
                    "fecha_emision": "Emision",
                    "fecha_vencimiento": "Vence",
                }
            )
        raise AssertionError(f"tarea inesperada en import: {task}")


def test_importar_hoja_llega_a_cartera(client, db_session, tenant, monkeypatch):
    import aiuda_server.metering as metering

    monkeypatch.setattr(metering, "tenant_runner", lambda db, t: FakeImportRunner())

    # Paso 1: analyze propone tipo y mapeo a partir del archivo del usuario.
    res = client.post(
        "/v1/import/analyze",
        headers=HEADERS,
        files={"file": ("cartera.csv", CSV_FACTURAS, "text/csv")},
    )
    assert res.status_code == 200
    propuesta = res.json()
    assert propuesta["entity"] == "facturas"
    assert propuesta["row_count"] == 2
    assert propuesta["mapping"]["folio"] == "Folio"

    # Paso 2: commit con el mapeo que confirmó el usuario (el paso HITL).
    res = client.post(
        "/v1/import/commit",
        headers=HEADERS,
        data={"entity": "facturas", "mapping": json.dumps(propuesta["mapping"]), "extras": "[]"},
        files={"file": ("cartera.csv", CSV_FACTURAS, "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["created"] == 2
    assert res.json()["errors"] == []

    # Efecto final: la cartera existe por API, con clientes y teléfono normalizado.
    cartera = client.get("/v1/invoices", headers=HEADERS).json()
    assert {r["folio"] for r in cartera} == {"M-201", "M-202"}
    bic = next(r for r in cartera if r["folio"] == "M-201")
    assert bic["amount"] == 17073.60
    assert bic["customer"] == "Papelería Bic"
    assert bic["customer_phone"] == "5215511110001"  # 10 dígitos -> 521 canónico
    clientes = client.get("/v1/customers", headers=HEADERS).json()
    nombres = {c["name"] for c in (clientes if isinstance(clientes, list) else clientes.get("customers", []))}
    assert {"Papelería Bic", "Tornillos MX"} <= nombres


# --------------------------------------------------------------------------- #
# Flujo 3: detectar pago -> conciliar -> cerrar factura                        #
# --------------------------------------------------------------------------- #


def test_pago_detectado_se_concilia_y_cierra_factura(client, db_session, tenant):
    customer, invoice = _factura(
        db_session, tenant,
        nombre="Papelería Bic", telefono="5215511110001",
        folio="M-104", monto=17073.60, vence=date(2026, 6, 5),
    )
    # Procedencia: la factura vino de Odoo -> al cerrarla, el pago se escribe de
    # vuelta a la fuente (writeback). Sin fuente escribible no se encola nada.
    invoice.source = "odoo"
    db_session.flush()

    # Detección: Diego cruza la cartera contra el banco. Belvo contesta la
    # respuesta del fixture de contrato (forma documentada) vía MockTransport.
    from aiuda_core.connectors.belvo import BelvoClient
    from aiuda_core.engine.sync import detectar_pagos

    belvo_respuesta = json.loads(BELVO_FIXTURE.read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/transactions/"
        assert request.url.params["type"] == "INFLOW"
        return httpx.Response(200, json=belvo_respuesta)

    belvo = BelvoClient(
        secret_id="sid", secret_password="spw", transport=httpx.MockTransport(handler)
    )
    report = detectar_pagos(
        db_session, tenant, today=date(2026, 6, 9), belvo_client=belvo, belvo_link_id="link-1"
    )
    assert report.pagos_por_conciliar == 1  # el depósito de 17,073.60 cuadró

    pago = db_session.scalar(select(Payment).where(Payment.tenant_id == tenant.id))
    assert pago.status == "pendiente"  # Diego PROPONE; nada se cierra solo
    db_session.refresh(invoice)
    assert invoice.status == "open"

    # Bandeja de conciliación: la propuesta trae la factura con evidencia.
    bandeja = client.get("/v1/reconciliation", headers=HEADERS).json()
    assert bandeja["count"] == 1
    pendiente = bandeja["pending"][0]
    assert pendiente["id"] == pago.id
    assert pendiente["source"] == "banco"
    assert pendiente["proposal"]["folio"] == "M-104"
    assert pendiente["proposal"]["cuadra"] is True

    # El humano confirma: la factura se cierra pagada, verificada por el banco,
    # con write-back encolado y auditoría.
    res = client.post(
        f"/v1/reconciliation/{pago.id}/confirm",
        headers=HEADERS,
        json={"invoice_ids": [pendiente["proposal"]["invoice_id"]]},
    )
    assert res.status_code == 200
    assert res.json()["invoice"]["status"] == "paid"

    db_session.refresh(invoice)
    db_session.refresh(pago)
    assert invoice.status == "paid"
    assert invoice.verified == "verificada"
    assert invoice.paid_source == "banco"
    assert pago.status == "conciliado"
    # Write-back del pago hacia la fuente (Odoo) quedó encolado (outbox).
    outbox = db_session.scalars(
        select(OutboxEntry).where(OutboxEntry.tenant_id == tenant.id)
    ).all()
    assert any(o.target == "odoo" and o.action == "registrar_pago" for o in outbox)
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant.id, AuditLog.action == "payment.reconcile"
        )
    )
    assert audit is not None
    # Y ya no está en la bandeja.
    assert client.get("/v1/reconciliation", headers=HEADERS).json()["count"] == 0


# --------------------------------------------------------------------------- #
# Flujo 4: crear conexión a la medida -> ingesta                               #
# --------------------------------------------------------------------------- #


def test_conexion_a_la_medida_ingesta(client, db_session, tenant, monkeypatch):
    """El dueño declara SU conexión en el builder (secreto cifrado) -> /v1/sync la
    ingiere -> la factura y el cliente existen por API con la procedencia que él
    nombró. El borde externo (su API) se fakea a nivel urlopen, igual que los
    tests de contrato de sync_custom; todo lo demás corre de verdad."""
    import io
    from contextlib import contextmanager as _ctx

    import aiuda_core.connectors.custom_api as custom_api

    # La API del usuario: cuentas por cobrar, envueltas como las regresa su sistema.
    respuesta = {
        "data": {
            "facturas": [
                {
                    "id": "fac-9001",
                    "cliente": "Refacciones Norte",
                    "cel": "55 3333 0044",
                    "folio": "RN-77",
                    "total": "$9,850.00",
                    "vence": "2026-07-20",
                }
            ]
        }
    }
    llamadas: list[tuple[str, dict]] = []

    @_ctx
    def opener(req, timeout=15):
        llamadas.append((req.full_url, {k.lower(): v for k, v in req.headers.items()}))
        yield io.BytesIO(json.dumps(respuesta).encode("utf-8"))

    monkeypatch.setattr(custom_api.urllib.request, "urlopen", opener)

    # Paso 1: crear la conexión por API (la prueba en vivo del builder corre aquí).
    res = client.post(
        "/v1/custom-connectors",
        headers=HEADERS,
        json={
            "name": "Facturador propio",
            "cap": "cuentas_por_cobrar",
            "base_url": "https://erp.ejemplo.mx/api",
            "list_path": "facturas",
            "root": "data.facturas",
            "auth_type": "header",
            "auth_header": "X-API-Key",
            "auth_value": "secreto-123",
            "mapping": {
                "customer": "cliente",
                "phone": "cel",
                "folio": "folio",
                "amount": "total",
                "due_date": "vence",
                "external_id": "id",
            },
        },
    )
    assert res.status_code == 200, res.text
    conexion = res.json()
    assert "auth_value" not in json.dumps(conexion)  # el secreto jamás regresa

    # Paso 2: la corrida de sync ingiere la fuente del dueño.
    res = client.post("/v1/sync", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["avisos"] == []  # respondió: nada que confesar

    # El GET salió con el secreto DESCIFRADO en el header que el dueño declaró.
    assert any(h.get("x-api-key") == "secreto-123" for _, h in llamadas)

    # Efecto final: cartera y directorio por API, con teléfono normalizado.
    cartera = client.get("/v1/invoices", headers=HEADERS).json()
    rn = next(r for r in cartera if r["folio"] == "RN-77")
    assert rn["amount"] == 9850.0  # "$9,850.00" -> Decimal
    assert rn["customer"] == "Refacciones Norte"
    assert rn["customer_phone"] == "5215533330044"

    # Procedencia: la fuente es custom y el badge lleva EL NOMBRE de su conexión.
    factura = db_session.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == "RN-77")
    )
    assert factura.source == "custom"
    assert factura.presence.get("Facturador propio", {}).get("ref") == "fac-9001"

    # Idempotencia: otra corrida no duplica (dedupe por external_id).
    client.post("/v1/sync", headers=HEADERS)
    assert len(client.get("/v1/invoices", headers=HEADERS).json()) == 1

    # Y la lista de conexiones dice la verdad de la última corrida.
    lista = client.get("/v1/custom-connectors", headers=HEADERS).json()
    mia = next(c for c in lista if c["name"] == "Facturador propio")
    assert mia.get("last_error") in (None, "")
    assert mia.get("last_count") == 1
