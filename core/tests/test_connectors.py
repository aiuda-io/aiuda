"""Conectores externos: request correcto + parsing, con transporte mockeado.

Ninguno toca la red real: httpx.MockTransport intercepta todo.
"""

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from aiuda_core.connectors.belvo import BelvoClient
from aiuda_core.connectors.denue import DenueClient
from aiuda_core.connectors.facturama import FacturamaClient
from aiuda_core.connectors.gcal import GoogleCalendarClient


def transport(handler):
    return httpx.MockTransport(handler)


# ---------- Belvo ----------


def test_belvo_inflows_y_match():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "tx1",
                        "amount": 18750.50,
                        "description": "SPEI FERRETERIA MARTILLO",
                        "value_date": "2026-06-08",
                        "type": "INFLOW",
                        "account": {"id": "acc1"},
                    }
                ]
            },
        )

    client = BelvoClient(secret_id="sid", secret_password="spw", transport=transport(handler))
    inflows = client.list_inflows("link-1", date(2026, 6, 1), date(2026, 6, 9))

    assert "type=INFLOW" in captured["url"]
    assert "value_date__gte=2026-06-01" in captured["url"]
    assert captured["auth"].startswith("Basic ")
    assert inflows[0].amount == 18750.50

    # tolerancia de 1 peso al cruzar contra la factura
    assert client.match_payment(inflows, 18750.00) is not None
    assert client.match_payment(inflows, 99999.0) is None


def test_belvo_sin_credenciales_truena():
    with pytest.raises(RuntimeError):
        BelvoClient(secret_id="", secret_password="")


# ---------- Facturama ----------


def test_facturama_lista_cfdis():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cfdi"
        assert request.url.params["type"] == "issuedLite"
        return httpx.Response(
            200,
            json=[
                {
                    "Id": "abc",
                    "Folio": "F-102",
                    "Total": 18750.5,
                    "RfcReceiver": "FEM880101XX1",
                    "TaxEntityName": "Ferretería El Martillo",
                    "Date": "2026-05-01",
                    "Status": "active",
                }
            ],
        )

    client = FacturamaClient(user="u", password="p", transport=transport(handler))
    cfdis = client.list_cfdis()
    assert cfdis[0].folio == "F-102"
    assert cfdis[0].rfc_receptor == "FEM880101XX1"


# ---------- DENUE ----------


def test_denue_buscar():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/app/api/denue/v1/consulta/Buscar/ferreteria/" in request.url.path
        assert request.url.path.endswith("/tok-123")
        return httpx.Response(
            200,
            json=[
                {
                    "Id": "1",
                    "Nombre": "FERRETERIA LA CENTRAL",
                    "Razon_social": "",
                    "Clase_actividad": "Comercio al por menor",
                    "Telefono": "5555555555",
                    "Correo_e": "",
                    "Calle": "AV JUAREZ 10",
                    "Colonia": "CENTRO",
                    "CP": "06000",
                }
            ],
        )

    client = DenueClient(token="tok-123", transport=transport(handler))
    negocios = client.buscar("ferreteria", 19.4326, -99.1332)
    assert negocios[0].nombre == "FERRETERIA LA CENTRAL"
    assert negocios[0].contactable is True
    assert "CENTRO" in negocios[0].direccion


# ---------- Google Calendar ----------


def test_gcal_freebusy_y_evento():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path.endswith("/freeBusy"):
            body = json.loads(request.content)
            assert body["items"] == [{"id": "primary"}]
            return httpx.Response(
                200,
                json={"calendars": {"primary": {"busy": [{"start": "a", "end": "b"}]}}},
            )
        return httpx.Response(
            200,
            json={
                "id": "ev1",
                "summary": "Llamada de cobranza",
                "start": {"dateTime": "2026-06-10T10:00:00"},
                "end": {"dateTime": "2026-06-10T10:30:00"},
                "htmlLink": "https://cal",
            },
        )

    client = GoogleCalendarClient(token="tok", transport=transport(handler))
    start = datetime(2026, 6, 10, 9, tzinfo=timezone.utc)
    end = datetime(2026, 6, 10, 18, tzinfo=timezone.utc)
    assert client.busy_slots(start, end) == [{"start": "a", "end": "b"}]
    event = client.create_event("Llamada de cobranza", start, end)
    assert event.id == "ev1"
