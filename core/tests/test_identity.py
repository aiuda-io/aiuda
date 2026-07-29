"""Resolución de identidad por teléfono: cruzar cliente y conversación pese a los
formatos distintos (Excel crudo, '+52…', '521…' del webhook). Es el bug raíz que
destejía el producto: la igualdad exacta nunca cruzaba."""

from aiuda_core.identity import (
    find_conversation_by_phone,
    resolve_customer_by_email,
    resolve_customer_by_phone,
)
from aiuda_core.models.entities import Conversation, Customer


def test_resolve_customer_cruza_formatos(session, tenant):
    c = Customer(tenant_id=tenant.id, name="Juan", phone="+52 55 1234 5678")
    session.add(c)
    session.flush()
    # El webhook guarda '5215512345678'; el mismo cliente debe cruzar por match_key.
    assert resolve_customer_by_phone(session, tenant.id, "5215512345678").id == c.id
    assert resolve_customer_by_phone(session, tenant.id, "5512345678").id == c.id
    assert resolve_customer_by_phone(session, tenant.id, "5599999999") is None


def test_find_conversation_cruza_formatos(session, tenant):
    conv = Conversation(tenant_id=tenant.id, remote_phone="5215512345678")
    session.add(conv)
    session.flush()
    assert find_conversation_by_phone(session, tenant.id, "+52 55 1234 5678").id == conv.id
    assert find_conversation_by_phone(session, tenant.id, "5512345678").id == conv.id
    assert find_conversation_by_phone(session, tenant.id, None) is None


def test_no_cruza_con_telefono_corto(session, tenant):
    # Menos de 10 dígitos: no se arriesga un match con basura corta.
    c = Customer(tenant_id=tenant.id, name="X", phone="123")
    session.add(c)
    session.flush()
    assert resolve_customer_by_phone(session, tenant.id, "123") is None


def test_resolve_customer_por_email_normaliza(session, tenant):
    """El canal de correo cruza al remitente contra el directorio por email, sin
    distinguir mayúsculas ni espacios (como quedó capturado en el Excel/fuente)."""
    c = Customer(tenant_id=tenant.id, name="Ana", email=" Ana@Cliente.MX ")
    session.add(c)
    session.flush()
    assert resolve_customer_by_email(session, tenant.id, "ana@cliente.mx").id == c.id
    assert resolve_customer_by_email(session, tenant.id, "ANA@CLIENTE.MX ").id == c.id
    assert resolve_customer_by_email(session, tenant.id, "otro@cliente.mx") is None
    # Sin @ no hay correo: nunca cruza (ni con vacío ni con basura).
    assert resolve_customer_by_email(session, tenant.id, "") is None
    assert resolve_customer_by_email(session, tenant.id, "ana") is None
