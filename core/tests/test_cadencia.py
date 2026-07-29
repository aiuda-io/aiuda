"""Cadencia anti-spam y seguimiento de promesas incumplidas (core del engine)."""

from datetime import date, datetime, time, timedelta, timezone

from aiuda_core.engine.engine import CleoEngine
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import PaymentPromise, Reminder
from conftest import FakeResponse

TODAY = date(2026, 6, 9)


def make_engine(session, tenant, fake_client):
    return CleoEngine(session, tenant, runner=ClaudeRunner(client=fake_client))


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
