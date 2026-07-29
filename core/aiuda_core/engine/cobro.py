"""Cobro con link de pago: resuelve la pasarela conectada del tenant y genera el link.

Fuente única de verdad compartida por el endpoint HTTP (``/v1/cobro/link``) y la
redacción de recordatorios (``engine.draft_reminder``). El proveedor sale de la
credencial CIFRADA del tenant; el primero conectado gana (orden de ``PASARELAS``).
"""

import importlib

from aiuda_core.connectors.credentials import ctor_kwargs, get_credential

# Proveedor -> (módulo, clase, campo secreto que confirma la conexión). El orden es
# la preferencia cuando hay más de una conectada.
PASARELAS = [
    ("mercadopago", "aiuda_core.connectors.mercadopago", "MercadoPagoClient", "access_token"),
    ("clip", "aiuda_core.connectors.clip", "ClipClient", "api_key"),
    ("conekta", "aiuda_core.connectors.conekta", "ConektaClient", "api_key"),
]


def resolver_pasarela(session, tenant):
    """(proveedor, cliente) de la primera pasarela conectada del tenant, o (None, None)."""
    for prov, modpath, clsname, gate in PASARELAS:
        creds = get_credential(session, tenant.id, prov)
        if creds and creds.get(gate):
            cls = getattr(importlib.import_module(modpath), clsname)
            return prov, cls(**ctor_kwargs(prov, creds))
    return None, None
