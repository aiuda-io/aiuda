"""Normalización de teléfonos compartida (envío WhatsApp + import)."""

from aiuda_core.phones import digits_from_jid, match_key, normalize_mx


def test_local_10_digits_gets_mx_mobile_prefix():
    assert normalize_mx("3314872210") == "5213314872210"


def test_strips_plus_and_spaces():
    assert normalize_mx("+521 33 1487 2210") == "5213314872210"


def test_already_normalized_passthrough():
    assert normalize_mx("5213314872210") == "5213314872210"


def test_52_mas_10_sin_uno_movil_recibe_el_uno():
    # El bug real: un número de la base como 52+10 (sin el '1' móvil, típico de Odoo) debe
    # volverse 521+10, o WhatsApp responde "no LID found" y el envío falla.
    assert normalize_mx("525512345678") == "5215512345678"
    assert normalize_mx("+52 55 1234 5678") == "5215512345678"


def test_no_mexicano_se_deja_igual():
    # Un número que no es mexicano (no empieza en 52, no son 10 dígitos) no se toca.
    assert normalize_mx("12125551234") == "12125551234"


def test_empty_and_none():
    assert normalize_mx("") == ""
    assert normalize_mx(None) == ""


def test_digits_from_jid_usuario_y_dispositivo():
    assert digits_from_jid("5212295423903@s.whatsapp.net") == "5212295423903"
    # Ignora el sufijo de dispositivo (:31).
    assert digits_from_jid("5212292641726:31@s.whatsapp.net") == "5212292641726"
    assert digits_from_jid("") == ""


def test_match_key_es_los_ultimos_10():
    # Cruza pese al '1' móvil mexicano: 521+10 y 52+10 dan la misma clave.
    assert match_key("5212295423903") == "2295423903"
    assert match_key("522295423903") == "2295423903"
    assert match_key("2295423903") == "2295423903"


def test_match_key_basura_corta_no_cruza():
    # Menos de 10 dígitos → clave vacía (no arriesga un match falso).
    assert match_key("12345") == ""
    assert match_key(None) == ""
