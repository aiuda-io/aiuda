"""Folios de documentos.

Un folio *provisional* es un marcador interno para un documento que todavía no tiene número
propio (p.ej. una factura en borrador de Odoo). Sirve para deduplicar de forma estable, pero
NO debe citarse al cliente como si fuera el número de su factura: el cliente no reconoce
"borrador-1", y mostrárselo se ve poco serio. La convención vive aquí, en un solo lugar, para
que quien genera el folio (los conectores) y quien redacta al cliente (el motor) coincidan.
"""

FOLIO_PROVISIONAL_PREFIX = "borrador-"


def folio_provisional(ref: str | int) -> str:
    """Folio interno estable para un documento sin número propio todavía."""
    return f"{FOLIO_PROVISIONAL_PREFIX}{ref}"


def es_provisional(folio: str | None) -> bool:
    """True si el folio es un marcador interno, no un número real de documento."""
    return bool(folio) and folio.startswith(FOLIO_PROVISIONAL_PREFIX)


def folio_para_cliente(folio: str | None) -> str:
    """El folio tal como puede citarse al cliente, o '' si es provisional (no hay número
    real que mostrar)."""
    return "" if es_provisional(folio) else (folio or "")
