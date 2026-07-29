"""Cadencia anti-spam, tope de borradores por corrida y seguimiento de promesas
incumplidas (core del engine)."""

import re
from datetime import date, datetime, time, timedelta, timezone

from aiuda_core.engine.engine import MAX_BORRADORES_POR_CORRIDA, CleoEngine
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Invoice, PaymentPromise, Reminder
from conftest import FakeResponse

TODAY = date(2026, 6, 9)


def make_engine(session, tenant, fake_client):
    return CleoEngine(session, tenant, runner=ClaudeRunner(client=fake_client))


class _EcoMessages:
    """Fake que redacta A PARTIR del prompt: cita el folio y el monto que le dieron,
    como haría el modelo real. Con una cartera de muchas facturas no sirve una
    respuesta fija: cada borrador tiene que hablar de SU factura."""

    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        datos = re.search(r"folio (\S+) por \$([\d,.]+)", kwargs["messages"][0]["content"])
        folio, monto = datos.group(1), datos.group(2)
        return FakeResponse(f"Buen día, su factura {folio} por ${monto} sigue pendiente.")


class _EcoClient:
    def __init__(self):
        self.messages = _EcoMessages()


def cartera(session, tenant, customer, cuantas: int) -> None:
    """`cuantas` facturas vencidas hace 9 días: todas accionables la misma corrida."""
    for n in range(cuantas):
        session.add(
            Invoice(
                tenant_id=tenant.id,
                customer_id=customer.id,
                folio=f"F-{n:03d}",
                amount=1000 + n,
                issued_date=TODAY - timedelta(days=40),
                due_date=TODAY - timedelta(days=9),
            )
        )
    session.flush()


def sent_reminder(session, tenant, invoice, days_ago: int) -> Reminder:
    r = Reminder(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        bucket="vencida_reciente",
        tone="amable_directo",
        message="Recordatorio previo",
        status="sent",
        sent_at=datetime.combine(
            TODAY - timedelta(days=days_ago), time(9, 0), tzinfo=timezone.utc
        ),
    )
    session.add(r)
    session.flush()
    return r


def test_cooldown_evita_spam_diario(session, tenant, customer, invoice, fake_client_factory):
    sent_reminder(session, tenant, invoice, days_ago=1)
    engine = make_engine(session, tenant, fake_client_factory())
    assert engine.run_reminders(TODAY) == []  # ayer se envio uno: hoy no insiste


def test_cooldown_vencido_permite_seguimiento(
    session, tenant, customer, invoice, fake_client_factory
):
    sent_reminder(session, tenant, invoice, days_ago=5)
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("Seguimiento")))
    drafted = engine.run_reminders(TODAY)
    assert len(drafted) == 1  # default 4 dias: a los 5 ya toca


def test_cooldown_configurable_por_tenant(
    session, tenant, customer, invoice, fake_client_factory
):
    tenant.config = {**(tenant.config or {}), "reminder_cooldown_days": 10}
    sent_reminder(session, tenant, invoice, days_ago=5)
    engine = make_engine(session, tenant, fake_client_factory())
    assert engine.run_reminders(TODAY) == []


def test_promesa_incumplida_dispara_seguimiento_inmediato(
    session, tenant, customer, invoice, fake_client_factory
):
    # Se envio recordatorio hace 2 dias (dentro del cooldown)...
    sent_reminder(session, tenant, invoice, days_ago=2)
    # ...pero el cliente prometio pagar AYER y no se reflejo
    session.add(
        PaymentPromise(
            tenant_id=tenant.id,
            invoice_id=invoice.id,
            promised_date=TODAY - timedelta(days=1),
        )
    )
    session.flush()
    fake = fake_client_factory(FakeResponse("Seguimiento de promesa"))
    engine = make_engine(session, tenant, fake)
    drafted = engine.run_reminders(TODAY)
    assert len(drafted) == 1
    prompt = fake.messages.requests[0]["messages"][0]["content"]
    assert "prometió pagar" in prompt  # el mensaje referencia la promesa


def test_promesa_ya_seguida_no_repite(session, tenant, customer, invoice, fake_client_factory):
    # Promesa rota hace 3 dias, y YA hubo recordatorio despues (hace 1 dia)
    session.add(
        PaymentPromise(
            tenant_id=tenant.id,
            invoice_id=invoice.id,
            promised_date=TODAY - timedelta(days=3),
        )
    )
    sent_reminder(session, tenant, invoice, days_ago=1)
    engine = make_engine(session, tenant, fake_client_factory())
    assert engine.run_reminders(TODAY) == []  # aplica cooldown normal


# --- Tope de borradores por corrida ------------------------------------------
# Sin tope, una cartera importada de golpe (o un negocio con 300 facturas
# vencidas) dispara 300 llamadas al LLM en la primera corrida: el dueño paga eso
# de un jalón y además recibe una bandeja de aprobaciones que nadie revisa.


def test_tope_de_borradores_por_corrida(session, tenant, customer, fake_client_factory):
    cartera(session, tenant, customer, 25)
    engine = make_engine(session, tenant, _EcoClient())
    assert len(engine.run_reminders(TODAY)) == MAX_BORRADORES_POR_CORRIDA == 20


def test_lo_que_no_cupo_sale_en_la_corrida_siguiente(session, tenant, customer):
    cartera(session, tenant, customer, 25)
    engine = make_engine(session, tenant, _EcoClient())
    assert len(engine.run_reminders(TODAY)) == 20
    # Las 20 de la primera ya tienen recordatorio activo: la siguiente corrida
    # levanta las 5 que quedaron, no las repite.
    segunda = engine.run_reminders(TODAY)
    assert len(segunda) == 5
    folios = {
        session.get(Invoice, r.invoice_id).folio for r in segunda
    }
    assert folios == {f"F-{n:03d}" for n in range(20, 25)}


def test_el_dueno_puede_mover_el_tope(session, tenant, customer):
    tenant.config = {**(tenant.config or {}), "max_borradores_corrida": 3}
    cartera(session, tenant, customer, 10)
    engine = make_engine(session, tenant, _EcoClient())
    assert len(engine.run_reminders(TODAY)) == 3


def test_las_mas_atrasadas_van_primero(session, tenant, customer):
    """El tope solo es justo si corta por el final: primero cobra lo más viejo."""
    tenant.config = {**(tenant.config or {}), "max_borradores_corrida": 2}
    for n, dias in enumerate((5, 30, 12)):
        session.add(
            Invoice(
                tenant_id=tenant.id, customer_id=customer.id, folio=f"F-{n}",
                amount=1000 + n, issued_date=TODAY - timedelta(days=60),
                due_date=TODAY - timedelta(days=dias),
            )
        )
    session.flush()
    drafted = make_engine(session, tenant, _EcoClient()).run_reminders(TODAY)
    assert [session.get(Invoice, r.invoice_id).folio for r in drafted] == ["F-1", "F-2"]


def test_handle_incoming_incluye_historial(
    session, tenant, customer, invoice, fake_client_factory
):
    fake = fake_client_factory(FakeResponse("Claro, le ayudo con eso."))
    engine = make_engine(session, tenant, fake)
    engine.handle_incoming(
        customer.phone,
        "entonces que onda con mi factura?",
        TODAY,
        history="[Tú (agente)]: Le recordé su factura F-001\n[Cliente]: dejame ver",
    )
    prompt = fake.messages.requests[0]["messages"][0]["content"]
    assert "Historial reciente del chat" in prompt
    assert "dejame ver" in prompt
