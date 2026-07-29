import pytest

from aiuda_core.agents.cleo.tools import send_approved_reminder
from aiuda_core.engine import approval
from aiuda_core.models import Reminder


def make_reminder(tenant, invoice, status="draft") -> Reminder:
    return Reminder(
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        bucket="vencida",
        tone="firme",
        message="Hola, le recordamos su pago pendiente.",
        status=status,
    )


def test_flujo_feliz(tenant, invoice):
    r = make_reminder(tenant, invoice)
    approval.advance(r, "pending_approval")
    approval.advance(r, "approved")
    approval.advance(r, "sent")
    assert r.status == "sent"
    assert r.sent_at is not None


def test_no_se_puede_enviar_sin_aprobar(tenant, invoice):
    r = make_reminder(tenant, invoice, status="pending_approval")
    with pytest.raises(approval.InvalidTransition):
        approval.advance(r, "sent")


def test_rechazado_es_recuperable(tenant, invoice):
    # Rechazar NO es terminal: el dueño corrige y envía (rejected -> approved) o lo
    # devuelve a la bandeja (rejected -> pending_approval). Nada se pierde.
    r = make_reminder(tenant, invoice, status="rejected")
    approval.advance(r, "approved")
    assert r.status == "approved"
    r2 = make_reminder(tenant, invoice, status="rejected")
    approval.advance(r2, "pending_approval")
    assert r2.status == "pending_approval"


def test_rechazado_no_salta_a_enviado(tenant, invoice):
    r = make_reminder(tenant, invoice, status="rejected")
    with pytest.raises(approval.InvalidTransition):
        approval.advance(r, "sent")


def test_envio_real_valida_estado(tenant, invoice):
    r = make_reminder(tenant, invoice, status="pending_approval")
    sent = []
    with pytest.raises(approval.InvalidTransition):
        send_approved_reminder(r, sent.append)
    assert sent == []  # nada salió por WhatsApp


def test_envio_real_marca_sent(tenant, invoice):
    r = make_reminder(tenant, invoice, status="approved")
    sent = []
    send_approved_reminder(r, sent.append)
    assert sent == [r.message]
    assert r.status == "sent"


def test_fallo_de_envio_marca_failed_y_permite_reintento(tenant, invoice):
    r = make_reminder(tenant, invoice, status="approved")

    def boom(_):
        raise ConnectionError("WhatsApp caído")

    with pytest.raises(ConnectionError):
        send_approved_reminder(r, boom)
    assert r.status == "failed"
    approval.advance(r, "approved")  # reintento permitido


def test_auto_send_nunca_para_critica():
    assert approval.can_auto_send({"auto_send_buckets": ["critica"]}, "critica") is False
    assert approval.can_auto_send({"auto_send_buckets": ["vence_pronto"]}, "vence_pronto") is True
    assert approval.can_auto_send({}, "vencida") is False
