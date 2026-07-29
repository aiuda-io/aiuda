"""Normalización de teléfonos al formato que espera WhatsApp (whatsmeow/wacli y
Evolution): solo dígitos país+número, sin '+', sin sufijo '@s.whatsapp.net'.

Los teléfonos en la base son inconsistentes (de Excel crudo, de Shopify con '+52…',
del webhook como '521…'), así que se normalizan en el borde de envío, no al guardar.
Para México un número local de 10 dígitos se prefija con 521 (52 país + 1 móvil que
WhatsApp exige).
"""

import re


def normalize_mx(value) -> str:
    """Dígitos país+número para WhatsApp. México usa 521 + los 10 dígitos locales (52 país
    + 1 móvil que WhatsApp EXIGE: sin el '1', el servidor responde 'no LID found' y el envío
    falla). Acepta las tres formas que llegan de la base: 10 dígitos sueltos, 52+10 (sin el
    '1', típico de Odoo/Excel) y 521+10 ya formado; las tres salen como 521+10 (idempotente).
    Un número no mexicano (que no empieza en 52 ni trae 10 dígitos) se deja como viene."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return f"521{digits}"
    if len(digits) in (12, 13) and digits.startswith("52"):
        return f"521{digits[-10:]}"
    return digits


def digits_from_jid(jid) -> str:
    """Dígitos del teléfono en un JID de WhatsApp.

    '5212295423903@s.whatsapp.net' → '5212295423903'. Ignora el sufijo de dispositivo
    (':31') y el dominio. Para grupos ('...@g.us') devuelve los dígitos del id (no es
    un teléfono; el caller decide por el dominio si aplica).
    """
    head = str(jid or "").split("@", 1)[0].split(":", 1)[0]
    return re.sub(r"\D", "", head)


def match_key(value) -> str:
    """Clave estable para cruzar teléfonos pese al '1' móvil mexicano (52 vs 521) y a
    los formatos sueltos: los últimos 10 dígitos (el número local). Cadena vacía si no
    hay al menos 10 dígitos (no se arriesga un match con basura corta)."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""
