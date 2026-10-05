from aiuda_core.engine.owner import handle_owner_command
from aiuda_core.models import Reminder


def make_pending(session, tenant, invoice, agent="mariana"):
    r = Reminder(
        tenant_id=tenant.id,
        agent=agent,
        invoice_id=invoice.id,
        bucket="vencida",
        tone="firme",
        message="Recordatorio pendiente",
        status="pending_approval",
    )
    session.add(r)
    session.flush()
    return r


def test_no_comando_devuelve_none(session, tenant):
    assert handle_owner_command(session, tenant, "cuánto me deben?") is None
    assert handle_owner_command(session, tenant, "hola") is None


def test_pendientes_lista_numerada(session, tenant, customer, invoice):
    make_pending(session, tenant, invoice)
    reply = handle_owner_command(session, tenant, "pendientes")
    assert "1. Cliente Demo · F-001" in reply.text
    assert "aprobar 2" in reply.text  # instrucciones de uso


def test_pendientes_bandeja_limpia(session, tenant):
    reply = handle_owner_command(session, tenant, "pendientes")
    assert "Bandeja limpia" in reply.text


def test_aprobar_numero(session, tenant, customer, invoice):
    r = make_pending(session, tenant, invoice)
    reply = handle_owner_command(session, tenant, "Aprobar 1")
    assert r.status == "approved"
    assert reply.send_reminders == [(r, customer.phone)]
    assert "Aprobado" in reply.text


def test_aprobar_todo(session, tenant, customer, invoice):
    r1 = make_pending(session, tenant, invoice)
    r2 = make_pending(session, tenant, invoice, agent="carlos")
    reply = handle_owner_command(session, tenant, "aprobar todo")
    assert r1.status == "approved" and r2.status == "approved"
    assert len(reply.send_reminders) == 2


def test_rechazar_numero_y_sin_rechazar_todo(session, tenant, customer, invoice):
    r = make_pending(session, tenant, invoice)
    reply = handle_owner_command(session, tenant, "rechazar 1")
    assert r.status == "rejected"
    assert reply.send_reminders == []

    r2 = make_pending(session, tenant, invoice)
    reply2 = handle_owner_command(session, tenant, "rechazar todo")
    assert r2.status == "pending_approval"  # no tocó nada
    assert "uno por uno" in reply2.text


def test_indice_invalido(session, tenant, customer, invoice):
    make_pending(session, tenant, invoice)
    reply = handle_owner_command(session, tenant, "aprobar 9")
    assert "No tengo el número 9" in reply.text


def test_no_se_aprueba_por_whatsapp_lo_de_una_factura_que_ya_no_se_cobra(
    session, tenant, customer, invoice
):
    """Aprobar por WhatsApp envía directo, sin pasar por la puerta de la consola
    ni por la del envío. Una factura cerrada (nota de crédito, cancelada en el
    SAT, entre tus empresas) no se ofrece ni se aprueba: se retira."""
    r = make_pending(session, tenant, invoice)
    invoice.status = "cancelled"
    invoice.meta = {"cerrada_por": "nota de crédito"}
    reply = handle_owner_command(session, tenant, "aprobar todo")
    assert reply.send_reminders == []
    assert "No hay nada pendiente" in reply.text
    assert r.status == "rejected"
    assert r.meta["retirado"] == "La factura ya no se cobra: nota de crédito."
