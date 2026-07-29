"""Write-back: lo confirmado en aiuda se inyecta al sistema de origen.

Aquí se prueba el MOTOR de la cola (estados, backoff, evidencia, reintento
manual) con dobles del conector. El contrato XML-RPC fino de Odoo vive en
test_odoo_writeback.py.
"""

from datetime import timedelta

from sqlalchemy import select

from aiuda_core.engine.writeback import (
    BACKOFF_MINUTES,
    MAX_ATTEMPTS,
    process_outbox,
    queue_customer_writeback,
    queue_payment_writeback,
    reset_for_retry,
)
from aiuda_core.models import Customer, OutboxEntry, utcnow


class FakeOdoo:
    """Doble del conector con la firma de escritura real. El contrato XML-RPC
    (requests grabados) se prueba aparte, en test_odoo_writeback.py."""

    url = "https://odoo.ejemplo.mx"

    def __init__(self, fail=False):
        self.payments = []
        self.partners = []
        self.fail = fail

    def register_invoice_payment(self, folio, amount=None, memo="", payment_date=None):
        if self.fail:
            raise ConnectionError("Odoo no responde")
        self.payments.append((folio, amount, memo, payment_date))
        return {"modo": "pago", "move_id": 7, "payment_state": "paid", "saldo_odoo": 0.0}

    def upsert_partner(self, ref, changes):
        if self.fail:
            raise ConnectionError("Odoo no responde")
        self.partners.append((ref, changes))
        creado = ref in (None, "")
        return {"partner_id": int(ref) if not creado else 55, "creado": creado, "en_odoo": changes}

    def crear_producto(self, name, sku=None, price=None, unit=None):
        if self.fail:
            raise ConnectionError("Odoo no responde")
        self.productos = getattr(self, "productos", [])
        self.productos.append((name, sku, price))
        return {"template_id": 71, "creado": True}

    def crear_factura_borrador(self, folio, cliente, amount, issued_date, due_date, concepto=""):
        if self.fail:
            raise ConnectionError("Odoo no responde")
        self.facturas = getattr(self, "facturas", [])
        self.facturas.append((folio, cliente, amount, issued_date, due_date, concepto))
        return {"move_id": 88, "creado": True, "borrador": True, "partner_id": 55, "partner_creado": not cliente.get("ref")}


class FakeShopify:
    """Shopify solo sabe dejar nota en el pedido (mark_note)."""

    def __init__(self):
        self.notes = []

    def mark_note(self, order_id, note):
        self.notes.append((order_id, note))
        return {"order": {"id": order_id, "note": note}}


def test_solo_fuentes_escribibles_encolan(session, tenant, customer, invoice):
    invoice.source = "excel"  # el Excel no es un sistema: no hay a dónde inyectar
    assert queue_payment_writeback(session, tenant, invoice) is None

    invoice.source = "odoo"
    entry = queue_payment_writeback(session, tenant, invoice)
    assert entry is not None
    assert entry.target == "odoo"
    assert entry.payload["folio"] == "F-001"
    assert entry.payload["invoice_id"] == invoice.id  # la ficha filtra por esto


def test_process_asienta_pago_y_persiste_evidencia(session, tenant, customer, invoice):
    invoice.source = "odoo"
    invoice.paid_source = "banco"
    queue_payment_writeback(session, tenant, invoice)

    odoo = FakeOdoo()
    result = process_outbox(session, tenant, odoo_client=odoo)
    assert result.processed == 1
    folio, amount, memo, _ = odoo.payments[0]
    assert folio == "F-001" and amount == 12500.5
    assert "confirmado" in memo and "banco" in memo

    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "done"
    assert entry.done_at is not None
    # Evidencia: qué se escribió, qué respondió la fuente y cuándo
    evidencia = entry.payload["evidencia"]
    assert evidencia["escrito"]["folio"] == "F-001"
    assert evidencia["respuesta"]["modo"] == "pago"
    assert evidencia["respuesta"]["saldo_odoo"] == 0.0
    assert evidencia["en"]
    # El request original sigue intacto en el payload
    assert entry.payload["invoice_id"] == invoice.id


def test_sin_conector_la_entrada_espera(session, tenant, customer, invoice):
    invoice.source = "odoo"
    queue_payment_writeback(session, tenant, invoice)
    result = process_outbox(session, tenant)  # sin clientes configurados
    assert result.processed == 0
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "pending"
    assert entry.attempts == 0  # esperar no cuenta como intento


def test_accion_sin_ejecutor_espera(session, tenant, customer):
    """Shopify aún no sabe escribir el cliente: la entrada espera su ejecutor,
    honesta en pending, sin quemar intentos ni marcar fallo."""
    customer.presence = {"shopify": {"ref": "9001"}}
    queue_customer_writeback(session, tenant, customer, {"name": "Nuevo Nombre"})
    result = process_outbox(session, tenant, shopify_client=FakeShopify())
    assert result.processed == 0 and result.failed == 0
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "pending"
    assert entry.attempts == 0


def test_actualizar_cliente_escribe_en_odoo(session, tenant, customer):
    customer.presence = {"odoo": {"ref": "12"}}
    queue_customer_writeback(session, tenant, customer, {"name": "Ferretería SA", "email": "f@x.mx"})
    odoo = FakeOdoo()
    result = process_outbox(session, tenant, odoo_client=odoo)
    assert result.processed == 1
    assert odoo.partners[0] == ("12", {"name": "Ferretería SA", "email": "f@x.mx"})
    entry = session.scalar(select(OutboxEntry))
    assert entry.payload["evidencia"]["respuesta"]["partner_id"] == 12


def test_alta_en_odoo_repara_la_liga(session, tenant, customer):
    """Si la presencia no traía referencia, el ejecutor da de alta el partner y
    la presencia del cliente queda ligada al registro nuevo."""
    customer.presence = {"odoo": {}}  # vive en odoo pero sin ref (liga rota)
    session.flush()
    queue_customer_writeback(session, tenant, customer, {"name": "Cliente Demo"})
    process_outbox(session, tenant, odoo_client=FakeOdoo())
    refreshed = session.get(Customer, customer.id)
    assert refreshed.presence["odoo"]["ref"] == "55"
    assert "res.partner/55" in (refreshed.presence["odoo"].get("url") or "")


def test_fallo_agenda_backoff_y_no_reintenta_de_inmediato(session, tenant, customer, invoice):
    invoice.source = "odoo"
    queue_payment_writeback(session, tenant, invoice)
    odoo = FakeOdoo(fail=True)
    t0 = utcnow()

    result = process_outbox(session, tenant, odoo_client=odoo, now=t0)
    assert result.failed == 1
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "pending" and entry.attempts == 1
    assert "Odoo no responde" in entry.last_error
    assert entry.payload["reintento_en"]  # backoff agendado

    # Corrida inmediata: el backoff aún no vence, no quema otro intento
    result2 = process_outbox(session, tenant, odoo_client=odoo, now=t0 + timedelta(seconds=10))
    assert result2.failed == 0
    assert entry.attempts == 1

    # Pasado el backoff, sí reintenta
    result3 = process_outbox(
        session, tenant, odoo_client=odoo, now=t0 + timedelta(minutes=BACKOFF_MINUTES[0] + 1)
    )
    assert result3.failed == 1
    assert entry.attempts == 2


def test_errores_reintentan_hasta_failed(session, tenant, customer, invoice):
    invoice.source = "odoo"
    queue_payment_writeback(session, tenant, invoice)
    odoo = FakeOdoo(fail=True)
    momento = utcnow()
    for _ in range(MAX_ATTEMPTS):
        process_outbox(session, tenant, odoo_client=odoo, now=momento)
        momento += timedelta(hours=2)  # cada corrida ya venció su backoff
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "failed"
    assert entry.attempts == MAX_ATTEMPTS
    assert "Odoo no responde" in entry.last_error
    assert "reintento_en" not in entry.payload  # falló definitivo: ya no agenda


def test_reintento_manual_resetea_y_procesa(session, tenant, customer, invoice):
    """Una fallida se reintenta a mano: vuelve a pending con presupuesto completo
    y el siguiente procesado la inyecta (cuando la fuente ya responde)."""
    invoice.source = "odoo"
    queue_payment_writeback(session, tenant, invoice)
    momento = utcnow()
    for _ in range(MAX_ATTEMPTS):
        process_outbox(session, tenant, odoo_client=FakeOdoo(fail=True), now=momento)
        momento += timedelta(hours=2)
    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "failed"

    reset_for_retry(entry)
    assert entry.status == "pending" and entry.attempts == 0
    assert entry.last_error  # el rastro del fallo anterior se conserva

    result = process_outbox(session, tenant, odoo_client=FakeOdoo(), now=momento)
    assert result.processed == 1
    assert entry.status == "done"
    assert entry.last_error is None
    assert entry.payload["evidencia"]["respuesta"]["modo"] == "pago"


def test_shopify_registra_nota_de_pago(session, tenant, customer, invoice):
    invoice.source = "shopify"
    invoice.folio = "#1042"
    shopify = FakeShopify()
    queue_payment_writeback(session, tenant, invoice)
    result = process_outbox(session, tenant, shopify_client=shopify)
    assert result.processed == 1
    assert shopify.notes[0][0] == "1042"
    entry = session.scalar(select(OutboxEntry))
    assert entry.payload["evidencia"]["respuesta"] == {"modo": "nota", "pedido": "1042"}


# --------------------------------------------------------------------------- #
# Candado de dinero: un intento del outbox solo lo ejecuta UNA corrida          #
# --------------------------------------------------------------------------- #
def test_claim_pierde_si_otra_corrida_ya_tomo_el_intento(session, tenant, customer, invoice):
    """La carrera real (TOCTOU): dos corridas leyeron la MISMA entrada pending con
    attempts=0. La que llega tarde al claim atómico no ejecuta nada — el asiento
    del pago jamás sale dos veces. (En Postgres además la fila viaja con
    FOR UPDATE SKIP LOCKED; este CAS es el cinturón que también corre en SQLite.)"""
    from sqlalchemy import update

    from aiuda_core.engine.writeback import _claim

    invoice.source = "odoo"
    entry = queue_payment_writeback(session, tenant, invoice)

    # Otra corrida ganó el intento entre nuestro SELECT y nuestro claim.
    session.execute(
        update(OutboxEntry)
        .where(OutboxEntry.id == entry.id)
        .values(attempts=1)
        .execution_options(synchronize_session=False)
    )

    assert _claim(session, entry) is False


def test_el_asiento_sobrevive_al_rollback_de_la_corrida(session, tenant, customer, invoice):
    """El peor bug del repo: process_outbox marcaba 'done' solo con flush y el
    commit lo daba la transacción del caller (la corrida del tenant, que envuelve
    también el sync y las llamadas al LLM). Un error de red posterior hacía
    rollback: el pago YA estaba asentado en Odoo pero la entrada volvía a
    'pending', y la siguiente corrida lo asentaba OTRA VEZ en la contabilidad
    del cliente. El asiento debe quedar durable en el momento en que la fuente
    lo recibió, pase lo que pase después en la misma transacción."""
    invoice.source = "odoo"
    queue_payment_writeback(session, tenant, invoice)
    session.commit()  # la entrada pending ya está durable (patrón outbox)

    odoo = FakeOdoo()
    process_outbox(session, tenant, odoo_client=odoo)
    assert len(odoo.payments) == 1

    # El caller truena DESPUÉS del write-back (p.ej. la IA sin red) y su
    # session_scope hace rollback de toda la transacción del tenant.
    session.rollback()

    entry = session.scalar(select(OutboxEntry))
    assert entry.status == "done"  # durable: Odoo ya recibió el pago

    # Y la siguiente corrida NO vuelve a asentar el mismo pago.
    process_outbox(session, tenant, odoo_client=odoo)
    assert len(odoo.payments) == 1


def test_claim_no_toma_entradas_que_dejaron_de_estar_pending(session, tenant, customer, invoice):
    from aiuda_core.engine.writeback import _claim

    invoice.source = "odoo"
    entry = queue_payment_writeback(session, tenant, invoice)
    entry.status = "done"
    session.flush()

    assert _claim(session, entry) is False


def test_memo_del_pago_lleva_el_id_del_outbox(session, tenant, customer, invoice):
    """Detectabilidad: si un doble asiento se colara por cualquier vía, el memo en
    Odoo dice qué entrada del outbox lo escribió."""
    invoice.source = "odoo"
    invoice.paid_source = "banco"
    entry = queue_payment_writeback(session, tenant, invoice)

    odoo = FakeOdoo()
    process_outbox(session, tenant, odoo_client=odoo)

    memo = odoo.payments[0][2]
    assert f"[outbox {entry.id}]" in memo
    # Y el payload persistido NO se contaminó con la llave inyectada al ejecutor.
    session.refresh(entry)
    assert "outbox_id" not in {k for k in entry.payload if k != "evidencia"}


# --------------------------------------------------------------------------- #
# Altas aiuda-born: el destino es ELEGIDO y la liga regresa como presencia      #
# --------------------------------------------------------------------------- #
class FakeGCal:
    def __init__(self):
        self.eventos = []

    def create_event(self, summary, start, end, description=""):
        from aiuda_core.connectors.gcal import CalendarEvent

        self.eventos.append((summary, start, end, description))
        return CalendarEvent(
            id="ev-9", summary=summary, start=start.isoformat(), end=end.isoformat(),
            html_link="https://calendar.google.com/event?eid=ev-9",
        )


def test_alta_de_cliente_va_al_destino_elegido_y_liga_presencia(session, tenant, customer):
    from aiuda_core.engine.writeback import queue_creation_writeback

    entry = queue_creation_writeback(session, tenant, registro=customer, target="odoo")
    assert entry.action == "crear_cliente" and entry.target == "odoo"

    odoo = FakeOdoo()
    result = process_outbox(session, tenant, odoo_client=odoo)
    assert result.processed == 1
    session.refresh(customer)
    assert customer.presence["odoo"]["ref"] == "55"
    assert "res.partner" in customer.presence["odoo"]["url"]


def test_alta_a_destino_que_no_recibe_esa_entidad_truena_legible(session, tenant, customer):
    from aiuda_core.engine.writeback import queue_creation_writeback

    import pytest

    with pytest.raises(ValueError, match="no recibe altas"):
        queue_creation_writeback(session, tenant, registro=customer, target="googlecalendar")


def test_alta_no_se_reencola_si_ya_vive_en_el_destino(session, tenant, customer):
    from aiuda_core.engine.writeback import queue_creation_writeback

    import pytest

    customer.presence = {"odoo": {"ref": "12"}}
    session.flush()
    with pytest.raises(ValueError, match="ya vive en odoo"):
        queue_creation_writeback(session, tenant, registro=customer, target="odoo")


def test_factura_aiuda_born_llega_como_borrador_con_su_cliente(session, tenant, customer, invoice):
    from aiuda_core.engine.writeback import queue_creation_writeback

    invoice.source = "aiuda"
    customer.presence = {"odoo": {"ref": "31"}}
    session.flush()
    queue_creation_writeback(session, tenant, registro=invoice, target="odoo")

    odoo = FakeOdoo()
    result = process_outbox(session, tenant, odoo_client=odoo)
    assert result.processed == 1
    folio, cliente, amount, _issued, _due, _c = odoo.facturas[0]
    assert folio == invoice.folio and float(amount) == float(invoice.amount)
    assert cliente["ref"] == "31"  # la factura se cuelga del partner ya ligado
    session.refresh(invoice)
    assert invoice.presence["odoo"]["ref"] == "88"
    assert "account.move" in invoice.presence["odoo"]["url"]
    entry = session.scalar(select(OutboxEntry).where(OutboxEntry.action == "crear_factura"))
    assert entry.payload["evidencia"]["respuesta"]["borrador"] is True


def test_cita_sin_hora_no_se_encola(session, tenant):
    from aiuda_core.engine.writeback import queue_creation_writeback
    from aiuda_core.models import Appointment

    import pytest

    cita = Appointment(tenant_id=tenant.id, title="Revisión", source="aiuda")
    session.add(cita)
    session.flush()
    with pytest.raises(ValueError, match="fecha y hora"):
        queue_creation_writeback(session, tenant, registro=cita, target="googlecalendar")


def test_cita_aiuda_born_viaja_a_google_calendar_y_liga_en_meta(session, tenant):
    from datetime import datetime

    from aiuda_core.engine.writeback import queue_creation_writeback
    from aiuda_core.models import Appointment

    cita = Appointment(
        tenant_id=tenant.id, title="Revisión anual", source="aiuda",
        starts_at=datetime(2026, 7, 15, 10, 0),
    )
    session.add(cita)
    session.flush()
    queue_creation_writeback(session, tenant, registro=cita, target="googlecalendar")

    gcal = FakeGCal()
    result = process_outbox(session, tenant, gcal_client=gcal)
    assert result.processed == 1
    summary, start, end, _d = gcal.eventos[0]
    assert summary == "Revisión anual" and (end - start).seconds == 3600
    session.refresh(cita)
    liga = cita.meta["inyectada_en"]["googlecalendar"]
    assert liga["ref"] == "ev-9" and "calendar.google" in liga["url"]


def test_alta_fallida_NO_se_reintenta_sola(session, tenant, customer):
    """Un timeout ambiguo pudo haber creado el registro allá: reintentar solo
    duplicaría. El alta fallida queda failed al primer golpe; el reintento es
    el botón (decisión consciente del dueño)."""
    from aiuda_core.engine.writeback import queue_creation_writeback

    entry = queue_creation_writeback(session, tenant, registro=customer, target="odoo")
    result = process_outbox(session, tenant, odoo_client=FakeOdoo(fail=True))
    assert result.failed == 1
    session.refresh(entry)
    assert entry.status == "failed"  # sin backoff, sin reintento automático
    assert entry.attempts == 1
    assert "reintento_en" not in entry.payload


def test_alta_por_conexion_a_la_medida_postea_y_liga_con_su_nombre(session, tenant, customer, monkeypatch):
    """La receta con write_path inyecta a LA API del dueño; la presencia queda
    con el nombre que él le puso a su conexión."""
    import base64
    import io
    import json as _json
    from contextlib import contextmanager

    from aiuda_core.connectors import custom_api
    from aiuda_core.engine.writeback import queue_creation_writeback
    from aiuda_core.security import crypto

    ct, ver = crypto.encrypt("secreto-x")
    tenant.config = {
        **(tenant.config or {}),
        "custom_sources": [{
            "id": "cx1", "name": "Mi ERP", "cap": "directorio_clientes",
            "base_url": "https://erp.mia.mx/api", "write_path": "clientes",
            "write_id_path": "data.id", "auth_type": "header", "auth_header": "X-Key",
            "secret_ct": base64.b64encode(ct).decode(), "secret_ver": ver,
            "mapping": {"name": "razon_social", "phone": "contacto.cel", "email": "contacto.mail"},
        }],
    }
    session.flush()

    llamadas = []

    @contextmanager
    def opener(req, timeout=15):
        llamadas.append((req.full_url, dict(req.headers), req.data))
        yield io.BytesIO(_json.dumps({"data": {"id": 909}}).encode())

    monkeypatch.setattr(custom_api.urllib.request, "urlopen", opener)

    queue_creation_writeback(
        session, tenant, registro=customer, target="custom",
        conexion={"id": "cx1", "pkey": "Mi ERP"},
    )
    result = process_outbox(session, tenant)
    assert result.processed == 1

    url, headers, body = llamadas[0]
    assert url.endswith("/clientes")
    assert headers.get("X-key") == "secreto-x" or headers.get("X-Key") == "secreto-x"
    enviado = _json.loads(body)
    assert enviado["razon_social"] == customer.name  # mapping invertido
    session.refresh(customer)
    assert customer.presence["Mi ERP"]["ref"] == "909"
