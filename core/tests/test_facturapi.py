import httpx
import pytest

from aiuda_core.connectors.facturapi import FacturapiClient


def test_facturapi_lista_invoices():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/invoices"
        assert request.headers.get("authorization", "").startswith("Basic ")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "inv1",
                        "folio_number": 102,
                        "total": 18750.5,
                        "customer": {"tax_id": "FEM880101XX1", "legal_name": "Ferretería El Martillo"},
                        "created_at": "2026-05-01T10:00:00Z",
                        "status": "valid",
                    }
                ]
            },
        )

    client = FacturapiClient(api_key="sk_test_x", transport=httpx.MockTransport(handler))
    cfdis = client.list_invoices()
    assert cfdis[0].folio == "102"
    assert cfdis[0].razon_receptor == "Ferretería El Martillo"


def test_facturapi_sin_key_truena(monkeypatch):
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "facturapi_api_key", "")
    with pytest.raises(RuntimeError):
        FacturapiClient(api_key="")
