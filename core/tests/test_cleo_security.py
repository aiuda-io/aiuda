"""Seguridad del loop conversacional con el deudor (input NO confiable).

El ejecutor de cobranza, cuando atiende a un deudor por WhatsApp, debe atar TODA
operación al teléfono que escribe: no puede leer la cartera completa ni tocar
facturas de otros clientes del mismo negocio aunque cite el folio. En el chat del
dueño (caller_phone=None) el acceso sigue siendo total.
"""

from datetime import date

import pytest
from sqlalchemy import select

from aiuda_core.agents.cleo.tools import CleoToolExecutor
from aiuda_core.models import PaymentPromise

TODAY = date(2026, 6, 9)
OTRO_TELEFONO = "5215599999999"  # un deudor distinto al dueño de la factura F-001


def test_deudor_no_toca_folio_ajeno(session, tenant, customer, invoice):
    """Un deudor que cita un folio que NO es suyo es rechazado (no escribe nada)."""
    ex = CleoToolExecutor(session, tenant, today=TODAY, caller_phone=OTRO_TELEFONO)
    with pytest.raises(ValueError, match="asociada a este número"):
        ex._registrar_pago(invoice.folio)
    with pytest.raises(ValueError, match="asociada a este número"):
        ex._registrar_promesa_pago(invoice.folio, "2026-06-20")
    # no se registró ninguna promesa
    promesas = session.scalars(
        select(PaymentPromise).where(PaymentPromise.tenant_id == tenant.id)
    ).all()
    assert promesas == []


def test_deudor_no_ve_cartera_ajena(session, tenant, customer, invoice):
    """consultar_cartera con un deudor solo ve SUS facturas, nunca la cartera completa."""
    ex = CleoToolExecutor(session, tenant, today=TODAY, caller_phone=OTRO_TELEFONO)
    # aunque el modelo proponga el teléfono de otro cliente, se ignora
    salida = ex._consultar_cartera(telefono_cliente=customer.phone)
    assert "F-001" not in salida
    assert "Sin facturas" in salida


def test_dueno_de_la_factura_si_puede(session, tenant, customer, invoice):
    """El cliente dueño del folio sí registra sobre su propia factura."""
    ex = CleoToolExecutor(session, tenant, today=TODAY, caller_phone=customer.phone)
    msg = ex._registrar_pago(invoice.folio)
    assert invoice.folio in msg
    session.refresh(invoice)
    assert invoice.payment_reported is True


def test_chat_dueno_ve_todo(session, tenant, customer, invoice):
    """Sin caller_phone (chat autenticado del dueño) el acceso a la cartera es total."""
    ex = CleoToolExecutor(session, tenant, today=TODAY)  # caller_phone=None
    salida = ex._consultar_cartera()
    assert "F-001" in salida
