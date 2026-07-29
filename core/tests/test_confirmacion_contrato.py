"""Contrato de las fuentes de confirmación de pago (Belvo / Stripe).

HONESTIDAD: los fixtures en data/ siguen la FORMA DOCUMENTADA de cada proveedor,
NO son respuestas grabadas de cuentas reales — Belvo y Stripe nunca han corrido en
vivo en este producto. Estos tests fijan el contrato (qué campos esperamos y cómo
se parsean) para que la primera corrida real solo tenga que sustituir el fixture
por la respuesta grabada. Mientras tanto, la UI dice 'pendiente de verificar en
vivo' y `verificada_en_vivo` es False en /v1/reconciliation.
"""

import json
from datetime import date
from pathlib import Path

import httpx

from aiuda_core.connectors.belvo import BelvoClient
from aiuda_core.connectors.stripe_pagos import StripeClient

DATA = Path(__file__).parent / "data"


def _transport(payload: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


def test_belvo_contrato_transacciones():
    payload = json.loads((DATA / "belvo_transacciones.json").read_text())
    client = BelvoClient(secret_id="sid", secret_password="spw", transport=_transport(payload))
    inflows = client.list_inflows("link-1", date(2026, 6, 1), date(2026, 6, 9))

    assert len(inflows) == 2
    t = inflows[0]
    # Los campos que la conciliación necesita: monto, descripción (contraparte),
    # fecha valor y tipo. Si Belvo cambia la forma, este test truena primero.
    assert t.id and t.type == "INFLOW"
    assert t.amount == 17073.60
    assert "PAPELERIA BIC" in t.description
    assert t.value_date == "2026-06-08"
    assert t.account_id == "d4617561-1c01-4b2f-83b6-b0f1f2f3a401"

    # El cruce por monto respeta la tolerancia de 1 peso del conector.
    assert client.match_payment(inflows, 17073.60) is not None
    assert client.match_payment(inflows, 17073.00) is not None
    assert client.match_payment(inflows, 99999.0) is None


def test_stripe_contrato_charges():
    payload = json.loads((DATA / "stripe_charges.json").read_text())
    client = StripeClient(api_key="sk_test_x", transport=_transport(payload))
    cobros = client.list_recent_charges()

    assert len(cobros) == 2
    c = cobros[0]
    # Stripe reporta centavos: el conector convierte a pesos.
    assert c.amount == 17073.60
    assert c.currency == "mxn" and c.paid is True
    assert c.customer_email == "compras@papeleriabic.mx"
    assert c.description == "Factura M-104"

    # Un cargo NO pagado (failed) jamás confirma una factura.
    fallido = cobros[1]
    assert fallido.paid is False
    assert client.match_payment(cobros, 5000.0) is None
    assert client.match_payment(cobros, 17073.60) is not None
