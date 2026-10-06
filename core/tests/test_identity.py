"""Resolución de identidad por teléfono: cruzar cliente y conversación pese a los
formatos distintos (Excel crudo, '+52…', '521…' del webhook). Es el bug raíz que
destejía el producto: la igualdad exacta nunca cruzaba."""

from aiuda_core.identity import (
    find_conversation_by_phone,
    resolve_customer_by_email,
    resolve_customer_by_phone,
    telefonos_atendidos,
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


def test_telefonos_atendidos_son_los_clientes_y_el_dueno_en_cualquier_formato(session, tenant):
    from aiuda_core.phones import match_key, phone_from_jid

    tenant.owner_phone = "+52 1 55 0000 0000"
    session.add_all([
        Customer(tenant_id=tenant.id, name="Local", phone="55 1234 5678"),
        Customer(tenant_id=tenant.id, name="Con 52", phone="+52 33 1487 2210"),
        Customer(tenant_id=tenant.id, name="Sin teléfono", phone=None),
        Customer(tenant_id=tenant.id, name="Basura", phone="123"),
    ])
    session.flush()
    atendidos = telefonos_atendidos(session, tenant)
    assert atendidos == {"5512345678", "3314872210", "5500000000"}

    def llega(jid):
        return match_key(phone_from_jid(jid)) in atendidos

    # WhatsApp entrega el mismo número con 521 o con 52: los dos cruzan.
    assert llega("5215512345678@s.whatsapp.net") and llega("525512345678@s.whatsapp.net")
    assert llega("5213314872210:31@s.whatsapp.net")  # con sufijo de dispositivo
    assert not llega("5215599990000@s.whatsapp.net")
    # Un '@lid' no trae teléfono, y el id de un grupo no es un teléfono aunque
    # termine en los mismos dígitos que el de un cliente.
    assert not llega("190000000000001@lid")
    assert not llega("5215512345678@lid")
    assert not llega("5215512345678-1475339136@g.us")
