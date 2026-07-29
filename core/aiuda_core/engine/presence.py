"""Presencia multi-sistema: el mismo registro puede vivir en varios lugares.

Un cliente puede estar en Odoo y en tu Excel; una factura puede ser también un
pedido de Shopify. En vez de duplicar o ignorar, aiuda hace upsert: registra en
qué sistemas vive cada registro (con liga directa cuando existe) y deja saltar
de uno a otro desde el detalle.
"""

# Sistemas de registro: su presencia eleva la verificación del dato. Incluye los PAC
# (Facturama/Facturapi): un CFDI timbrado es respaldo fiscal del SAT, la verificación
# más fuerte que puede tener una factura.
REGISTRY_SYSTEMS = {"odoo", "shopify", "woocommerce", "facturama", "facturapi"}


def add_presence(record, system: str, ref: str, url: str | None = None) -> None:
    """Marca que `record` también vive en `system`. Idempotente.

    Las columnas JSON no trackean mutación in-place: siempre se reasigna.
    """
    entry: dict = {"ref": ref}
    if url:
        entry["url"] = url
    record.presence = {**(record.presence or {}), system: entry}
    if system in REGISTRY_SYSTEMS and getattr(record, "verified", None) == "sin_verificar":
        record.verified = "verificada"


def odoo_record_url(base_url: str, record_id: int, model: str = "account.move") -> str | None:
    """Liga directa a un registro en Odoo (v17+: /odoo/<modelo>/<id>). Por defecto la
    factura (account.move); se pasa `model="res.partner"` para ligar al cliente."""
    if not base_url or not record_id:
        return None
    return f"{base_url.rstrip('/')}/odoo/{model}/{record_id}"


def shopify_order_url(store_domain: str, order_id: str) -> str | None:
    if not store_domain or not order_id:
        return None
    return f"https://{store_domain}/admin/orders/{order_id}"
