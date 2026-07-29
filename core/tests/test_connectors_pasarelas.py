"""Pasarelas de cobro (Mercado Pago, Clip, Conekta): link de pago, confirmación y prueba,
con transporte mockeado. Ninguna toca la red: httpx.MockTransport intercepta todo."""

import httpx

from aiuda_core.connectors.clip import ClipClient
from aiuda_core.connectors.conekta import ConektaClient
from aiuda_core.connectors.mercadopago import MercadoPagoClient


def _t(handler):
    return httpx.MockTransport(handler)


# ---------- Mercado Pago ----------
def test_mercadopago_link_auth_y_referencia():
    cap = {}

    def handler(req: httpx.Request) -> httpx.Response:
        cap["url"] = str(req.url)
        cap["auth"] = req.headers.get("authorization", "")
        import json
        cap["body"] = json.loads(req.content)
        return httpx.Response(200, json={"init_point": "https://mpago.la/abc"})

    c = MercadoPagoClient(access_token="APP_USR-x", transport=_t(handler))
    link = c.crear_link_pago(1850.0, "Factura F-1042", referencia="F-1042")
    assert link == "https://mpago.la/abc"
    assert cap["auth"] == "Bearer APP_USR-x"
    assert cap["url"].endswith("/checkout/preferences")
    assert cap["body"]["items"][0]["unit_price"] == 1850.0
    assert cap["body"]["external_reference"] == "F-1042"


def test_mercadopago_confirma_por_monto():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"id": 1, "transaction_amount": 500.0, "status": "approved", "currency_id": "MXN", "payer": {"email": "a@b.mx"}},
            {"id": 2, "transaction_amount": 999.0, "status": "rejected"},
        ]})

    c = MercadoPagoClient(access_token="t", transport=_t(handler))
    pagos = c.list_recent_payments()
    assert c.match_payment(pagos, 500.0).id == "1"
    assert c.match_payment(pagos, 999.0) is None  # rechazado no cuenta


def test_mercadopago_test_connection():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/users/me":
            return httpx.Response(200, json={"nickname": "TIENDA_MX"})
        return httpx.Response(200, json={"results": [{"id": 1}]})

    info = MercadoPagoClient(access_token="t", transport=_t(handler)).test_connection()
    assert info["cuenta"] == "TIENDA_MX" and info["pagos_recientes"] == 1


# ---------- Clip ----------
def test_clip_link_y_confirmacion():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            assert req.headers.get("authorization") == "Bearer clip-k"
            return httpx.Response(200, json={"payment_request_url": "https://clip.mx/p/xyz"})
        return httpx.Response(200, json={"data": [{"id": "p1", "amount": 320.0, "status": "paid"}]})

    c = ClipClient(api_key="clip-k", transport=_t(handler))
    assert c.crear_link_pago(320.0, "Pago") == "https://clip.mx/p/xyz"
    pagos = c.list_recent_payments()
    assert c.match_payment(pagos, 320.0).id == "p1"


def test_clip_test_connection():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "p1"}]})

    assert ClipClient(api_key="k", transport=_t(handler)).test_connection()["pagos_visibles"] == 1


# ---------- Conekta ----------
def test_conekta_link_centavos_y_basic_auth():
    cap = {}

    def handler(req: httpx.Request) -> httpx.Response:
        cap["auth"] = req.headers.get("authorization", "")
        cap["accept"] = req.headers.get("accept", "")
        import json
        cap["body"] = json.loads(req.content)
        return httpx.Response(200, json={"url": "https://pay.conekta.com/link/abc"})

    c = ConektaClient(api_key="key_priv", transport=_t(handler))
    link = c.crear_link_pago(100.0, "Factura")
    assert link == "https://pay.conekta.com/link/abc"
    assert cap["auth"].startswith("Basic ")  # private key como usuario
    assert "conekta" in cap["accept"]
    assert cap["body"]["line_items"][0]["unit_price"] == 10000  # 100 pesos -> centavos


def test_conekta_confirma_convierte_centavos():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"id": "ord_1", "amount": 45000, "payment_status": "paid", "currency": "MXN"},
        ]})

    c = ConektaClient(api_key="k", transport=_t(handler))
    pagos = c.list_recent_payments()
    assert pagos[0].amount == 450.0  # 45000 centavos
    assert c.match_payment(pagos, 450.0).id == "ord_1"


def test_conekta_test_connection():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "ord_1"}]})

    assert ConektaClient(api_key="k", transport=_t(handler)).test_connection()["ordenes_visibles"] == 1
