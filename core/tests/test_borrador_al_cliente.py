"""Lo que se guarda como recordatorio tiene que poder mandársele a un cliente.

`llm.complete` devuelve "" cuando la respuesta del modelo no trae bloque de
texto (se cortó, contestó solo con razonamiento, tropezó). `draft_reminder` lo
guardaba tal cual, y con auto-envío el cliente recibía un WhatsApp en blanco con
la firma del negocio abajo. La reja está en el motor —no en el prompt— porque el
prompt es una petición y esto es una garantía.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from aiuda_core.engine.engine import BorradorInvalido, CleoEngine
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Ayudante, Invoice, Reminder
from conftest import FakeResponse

TODAY = date(2026, 6, 9)
# La factura de conftest: folio F-001, $12,500.50.
BUENO = "Buen día, le recuerdo su factura F-001 por $12,500.50, vencida el 31/05."


def make_engine(session, tenant, fake_client):
    return CleoEngine(session, tenant, runner=ClaudeRunner(client=fake_client))


def _borrar(session, tenant, fake, invoice, customer):
    return make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)


def _guardados(session, tenant) -> list[Reminder]:
    return list(session.scalars(select(Reminder).where(Reminder.tenant_id == tenant.id)).all())


def test_un_borrador_bueno_si_pasa(session, tenant, customer, invoice, fake_client_factory):
    r = _borrar(session, tenant, fake_client_factory(FakeResponse(BUENO)), invoice, customer)
    assert r.status == "pending_approval" and r.message == BUENO


def test_el_mensaje_vacio_no_se_guarda(session, tenant, customer, invoice, fake_client_factory):
    with pytest.raises(BorradorInvalido):
        _borrar(session, tenant, fake_client_factory(FakeResponse("")), invoice, customer)
    assert _guardados(session, tenant) == []


def test_la_firma_no_disfraza_un_mensaje_vacio(
    session, tenant, customer, invoice, fake_client_factory
):
    """El bug reportado: el modelo no dijo nada y al cliente le llegaba solo la
    firma del negocio, como si alguien le hubiera escrito."""
    session.add(
        Ayudante(
            tenant_id=tenant.id,
            name="abi",
            aiuditas={"cobranza.redactar_recordatorio": {"firma": "Equipo Hanova"}},
        )
    )
    session.flush()
    with pytest.raises(BorradorInvalido):
        _borrar(session, tenant, fake_client_factory(FakeResponse("   \n  ")), invoice, customer)
    assert _guardados(session, tenant) == []


def test_sin_el_folio_no_sale(session, tenant, customer, invoice, fake_client_factory):
    """Un cobro que no dice de qué factura habla obliga al cliente a adivinar."""
    fake = fake_client_factory(FakeResponse("Le recuerdo su adeudo de $12,500.50."))
    with pytest.raises(BorradorInvalido) as exc:
        _borrar(session, tenant, fake, invoice, customer)
    assert "F-001" in str(exc.value)


def test_sin_el_monto_no_sale(session, tenant, customer, invoice, fake_client_factory):
    fake = fake_client_factory(FakeResponse("Le recuerdo su factura F-001, ya vencida."))
    with pytest.raises(BorradorInvalido) as exc:
        _borrar(session, tenant, fake, invoice, customer)
    assert "monto" in str(exc.value)


@pytest.mark.parametrize(
    "cantidad", ["$12,500.50", "$12500.50", "$12,500", "12500.50 pesos"]
)
def test_el_monto_cuenta_con_o_sin_comas(
    session, tenant, customer, invoice, fake_client_factory, cantidad
):
    """El modelo escribe la cantidad como se le da la gana; la reja no puede
    rechazar un mensaje bueno por una coma."""
    fake = fake_client_factory(FakeResponse(f"Su factura F-001 por {cantidad} sigue pendiente."))
    assert _borrar(session, tenant, fake, invoice, customer).status == "pending_approval"


def test_la_factura_sin_folio_real_no_exige_folio(
    session, tenant, customer, invoice, fake_client_factory
):
    """Un folio provisional (borrador-N de Odoo) no se le cita al cliente, así que
    tampoco se le exige al mensaje."""
    invoice.folio = "borrador-7"
    session.flush()
    fake = fake_client_factory(FakeResponse("Le recuerdo su adeudo de $12,500.50."))
    assert _borrar(session, tenant, fake, invoice, customer).status == "pending_approval"


def test_la_corrida_salta_la_mala_y_sigue_con_las_demas(
    session, tenant, customer, invoice, fake_client_factory
):
    """Una factura que el modelo no supo redactar no puede llevarse a las demás:
    queda sin recordatorio activo y la corrida siguiente la vuelve a intentar."""
    otra = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio="F-002", amount=800,
        issued_date=date(2026, 5, 1), due_date=TODAY - timedelta(days=3),
    )
    session.add(otra)
    session.flush()
    # invoice vence antes, así que va primera: esa es la que sale vacía.
    fake = fake_client_factory(
        FakeResponse(""),
        FakeResponse("Le recuerdo su factura F-002 por $800.00, vencida hace 3 días."),
    )
    drafted = make_engine(session, tenant, fake).run_reminders(TODAY)
    assert len(drafted) == 1
    assert session.get(Invoice, drafted[0].invoice_id).folio == "F-002"
    assert _guardados(session, tenant) == drafted


def test_el_prompt_le_pide_al_modelo_lo_que_se_le_va_a_exigir(
    session, tenant, customer, invoice, fake_client_factory
):
    """La reja no puede ser una trampa: si se exige monto y folio, el prompt los
    pide explícitamente."""
    fake = fake_client_factory(FakeResponse(BUENO))
    _borrar(session, tenant, fake, invoice, customer)
    prompt = fake.messages.requests[0]["messages"][0]["content"]
    assert "monto" in prompt and "folio" in prompt
