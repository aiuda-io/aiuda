"""Conectores comerciales: Shopify, WooCommerce y Stripe.

Ninguno toca la red real: httpx.MockTransport intercepta todo.
Casos cubiertos: request correcto (path, headers, params) + parsing de
respuesta + RuntimeError cuando faltan credenciales.
"""

import base64

import httpx
import pytest

from aiuda_core.connectors.shopify import ShopifyClient
from aiuda_core.connectors.woocommerce import WooCommerceClient
from aiuda_core.connectors.stripe_pagos import StripeClient


def transport(handler):
    return httpx.MockTransport(handler)


# ────────────────────────────── Shopify ──────────────────────────────


def test_shopify_list_unpaid_orders():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["token"] = request.headers.get("x-shopify-access-token", "")
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "id": 1001,
                        "name": "#1001",
                        "total_price": "1250.00",
                        "currency": "MXN",
                        "created_at": "2026-06-01T10:00:00-06:00",
                        "customer": {
                            "first_name": "Mariana",
                            "last_name": "López",
                            "phone": "+5215551234567",
                            "default_address": {"phone": "+5215559999999"},
                        },
                    }
                ]
            },
        )

    client = ShopifyClient(
        store_domain="mitienda.myshopify.com",
        access_token="shpat_test",
        transport=transport(handler),
    )
    pedidos = client.list_unpaid_orders()

    assert captured["path"] == "/admin/api/2024-01/orders.json"
    assert captured["token"] == "shpat_test"
    assert captured["params"]["financial_status"] == "pending"
    assert captured["params"]["status"] == "open"

    assert len(pedidos) == 1
    p = pedidos[0]
    assert p.id == 1001
    assert p.name == "#1001"
    assert p.total == 1250.0
    assert p.currency == "MXN"
    assert p.customer_name == "Mariana López"
    assert p.customer_phone == "+5215551234567"


def test_shopify_mark_note():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["body"] = request.read()
        return httpx.Response(200, json={"order": {"id": 1001, "note": "Llamó, promete pagar viernes"}})

    client = ShopifyClient(
        store_domain="mitienda.myshopify.com",
        access_token="shpat_test",
        transport=transport(handler),
    )
    result = client.mark_note(1001, "Llamó, promete pagar viernes")

    assert captured["path"] == "/admin/api/2024-01/orders/1001.json"
    assert captured["method"] == "PUT"
    assert b"promete pagar viernes" in captured["body"]
    assert "order" in result


def test_shopify_sin_credenciales_truena():
    with pytest.raises(RuntimeError):
        ShopifyClient(store_domain="", access_token="")


def test_shopify_sin_token_truena():
    with pytest.raises(RuntimeError):
        ShopifyClient(store_domain="mitienda.myshopify.com", access_token="")


# ────────────────────────────── WooCommerce ──────────────────────────────


def test_woocommerce_list_unpaid_orders():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "id": 55,
                    "number": "55",
                    "total": "3200.00",
                    "currency": "MXN",
                    "date_created": "2026-06-05T09:30:00",
                    "billing": {
                        "first_name": "Carlos",
                        "last_name": "Mendoza",
                        "phone": "+5215558887766",
                    },
                }
            ],
        )

    client = WooCommerceClient(
        base_url="https://mitienda.mx",
        consumer_key="ck_abc",
        consumer_secret="cs_xyz",
        transport=transport(handler),
    )
    pedidos = client.list_unpaid_orders()

    assert captured["path"] == "/wp-json/wc/v3/orders"
    # Authorization debe ser HTTP Basic
    assert captured["auth"].startswith("Basic ")
    # Decodificamos para verificar las credenciales
    encoded = captured["auth"].split(" ", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    assert decoded == "ck_abc:cs_xyz"
    assert captured["params"]["status"] == "pending,on-hold"
    assert captured["params"]["per_page"] == "50"

    assert len(pedidos) == 1
    p = pedidos[0]
    assert p.id == 55
    assert p.name == "#55"
    assert p.total == 3200.0
    assert p.currency == "MXN"
    assert p.customer_name == "Carlos Mendoza"
    assert p.customer_phone == "+5215558887766"


def test_woocommerce_sin_credenciales_truena():
    with pytest.raises(RuntimeError):
        WooCommerceClient(base_url="", consumer_key="", consumer_secret="")


def test_woocommerce_sin_key_truena():
    with pytest.raises(RuntimeError):
        WooCommerceClient(
            base_url="https://mitienda.mx", consumer_key="", consumer_secret=""
        )


# ────────────────────────────── Stripe ──────────────────────────────


def test_stripe_list_recent_charges():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization", "")
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "ch_test_001",
                        # 1 875 050 centavos → 18 750.50 pesos
                        "amount": 1875050,
                        "currency": "mxn",
                        "description": "Pago pedido #1001",
                        "paid": True,
                        "created": 1749340800,
                        "billing_details": {"email": "carlos@ejemplo.mx"},
                    },
                    {
                        "id": "ch_test_002",
                        "amount": 50000,
                        "currency": "mxn",
                        "description": "Intento fallido",
                        "paid": False,
                        "created": 1749340900,
                        "billing_details": {"email": ""},
                    },
                ]
            },
        )

    client = StripeClient(api_key="sk_test_abc", transport=transport(handler))
    cobros = client.list_recent_charges()

    assert captured["path"] == "/v1/charges"
    assert captured["auth"] == "Bearer sk_test_abc"
    assert captured["params"]["limit"] == "50"

    assert len(cobros) == 2
    c = cobros[0]
    assert c.id == "ch_test_001"
    # Verificamos conversión de centavos a pesos
    assert c.amount == 18750.50
    assert c.currency == "mxn"
    assert c.paid is True
    assert c.customer_email == "carlos@ejemplo.mx"

    c2 = cobros[1]
    assert c2.amount == 500.0
    assert c2.paid is False


def test_stripe_match_payment_encuentra():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "ch_paid",
                        "amount": 1875050,
                        "currency": "mxn",
                        "description": "",
                        "paid": True,
                        "created": 1749340800,
                        "billing_details": {"email": ""},
                    }
                ]
            },
        )

    client = StripeClient(api_key="sk_test_abc", transport=transport(handler))
    cobros = client.list_recent_charges()

    # Tolerancia de 1 peso: la factura dice 18 750 pero Stripe registró 18 750.50
    encontrado = client.match_payment(cobros, 18750.00)
    assert encontrado is not None
    assert encontrado.id == "ch_paid"

    no_encontrado = client.match_payment(cobros, 99999.0)
    assert no_encontrado is None


def test_stripe_match_payment_no_paga_no_cuenta():
    """Un cobro con paid=False no debe matchear aunque el monto coincida."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "ch_unpaid",
                        "amount": 1875000,
                        "currency": "mxn",
                        "description": "",
                        "paid": False,
                        "created": 1749340800,
                        "billing_details": {"email": ""},
                    }
                ]
            },
        )

    client = StripeClient(api_key="sk_test_abc", transport=transport(handler))
    cobros = client.list_recent_charges()
    assert client.match_payment(cobros, 18750.0) is None


def test_stripe_sin_credenciales_truena():
    with pytest.raises(RuntimeError):
        StripeClient(api_key="")
