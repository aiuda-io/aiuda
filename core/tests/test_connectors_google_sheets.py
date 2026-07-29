"""Conector Google Sheets: lectura por API key (Sheets API v4) + mapeo por
encabezado + ingesta reusando los lectores custom. Ninguna prueba toca la red:
httpx.MockTransport intercepta todo.
"""

import httpx
import pytest
from sqlalchemy import select

from aiuda_core.connectors.google_sheets import GoogleSheetsClient, inferir_mapeo
from aiuda_core.engine.sync import sync_google_sheets
from aiuda_core.models import Customer, Invoice, Product


def transport(handler):
    return httpx.MockTransport(handler)


# ─────────────────────────── inferir_mapeo (sin red) ───────────────────────────


def test_inferir_mapeo_exacto_gana_sobre_contencion():
    # "Teléfono" exacto debe ganar sobre "Teléfono del cliente" para el campo phone.
    headers = ["Folio", "Cliente", "Teléfono del cliente", "Teléfono", "Monto", "Vencimiento"]
    mapeo = inferir_mapeo(headers, "facturas")
    assert headers[mapeo["folio"]] == "Folio"
    assert headers[mapeo["customer"]] == "Cliente"
    assert headers[mapeo["phone"]] == "Teléfono"  # exacto, no el compuesto
    assert headers[mapeo["amount"]] == "Monto"
    assert headers[mapeo["due_date"]] == "Vencimiento"


def test_inferir_mapeo_acentos_y_mayusculas():
    headers = ["CORREO ELECTRÓNICO", "Nombre", "WhatsApp"]
    mapeo = inferir_mapeo(headers, "clientes")
    assert headers[mapeo["name"]] == "Nombre"
    assert headers[mapeo["email"]] == "CORREO ELECTRÓNICO"
    assert headers[mapeo["phone"]] == "WhatsApp"


def test_inferir_mapeo_tipo_desconocido_vacio():
    assert inferir_mapeo(["A", "B"], "loquesea") == {}


# ─────────────────────────── fetch_rows (mock transport) ───────────────────────────


def test_fetch_rows_facturas_mapea_y_omite_vacias():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["key"] = request.url.params.get("key")
        return httpx.Response(
            200,
            json={
                "range": "Facturas!A:E",
                "values": [
                    ["Folio", "Cliente", "Teléfono", "Monto", "Vencimiento"],
                    ["F-001", "Juan Pérez", "8112345678", "1,250.50", "2026-07-20"],
                    ["", "", "", "", ""],  # fila vacía: se omite
                    ["F-002", "Ana", "", "900", "2026-08-01"],
                ],
            },
        )

    client = GoogleSheetsClient(api_key="AIzaTEST", transport=transport(handler))
    rows, err = client.fetch_rows("SHEET123", "Facturas!A:E", "facturas")

    assert err is None
    assert captured["key"] == "AIzaTEST"
    assert "SHEET123" in captured["path"] and "values" in captured["path"]
    assert len(rows) == 2
    assert rows[0] == {
        "folio": "F-001",
        "customer": "Juan Pérez",
        "phone": "8112345678",
        "amount": "1,250.50",
        "due_date": "2026-07-20",
    }
    # Celda vacía intermedia queda como "" (la fila no está vacía del todo, se conserva).
    assert rows[1]["folio"] == "F-002" and rows[1]["phone"] == ""


def test_fetch_rows_productos():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "values": [
                    ["Nombre", "SKU", "Precio", "Existencia"],
                    ["Café molido", "CAF-1", "180", "42"],
                ]
            },
        )

    client = GoogleSheetsClient(api_key="k", transport=transport(handler))
    rows, err = client.fetch_rows("S", "Productos!A:D", "productos")
    assert err is None
    assert rows == [{"name": "Café molido", "sku": "CAF-1", "price": "180", "stock": "42"}]


def test_fetch_rows_sin_columnas_conocidas_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [["Columna X", "Columna Y"], ["1", "2"]]})

    client = GoogleSheetsClient(api_key="k", transport=transport(handler))
    rows, err = client.fetch_rows("S", "H!A:B", "clientes")
    assert rows == [] and err is not None and "reconocí" in err


def test_fetch_rows_403_no_compartida_error_legible():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "forbidden"}})

    client = GoogleSheetsClient(api_key="k", transport=transport(handler))
    rows, err = client.fetch_rows("S", "H!A:B", "facturas")
    assert rows == [] and err is not None and "403" in err


def test_fetch_rows_rango_vacio_noop():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})  # sin 'values'

    client = GoogleSheetsClient(api_key="k", transport=transport(handler))
    rows, err = client.fetch_rows("S", "H!A:B", "facturas")
    assert rows == [] and err is None


def test_test_connection_titulo_y_conteo():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/values/" + "Facturas%21A%3AF") or "values" in request.url.path:
            return httpx.Response(
                200, json={"values": [["Folio"], ["1"], ["2"], ["3"]]}
            )
        return httpx.Response(
            200,
            json={
                "properties": {"title": "Cartera Hanova"},
                "sheets": [{"properties": {"title": "Facturas"}}, {"properties": {"title": "Clientes"}}],
            },
        )

    client = GoogleSheetsClient(api_key="k", transport=transport(handler))
    info = client.test_connection("SHEET123", "Facturas!A:F")
    assert info["title"] == "Cartera Hanova"
    assert info["sheets"] == 2
    assert info["rows"] == 3  # 4 filas menos el encabezado


def test_sin_api_key_truena():
    with pytest.raises(RuntimeError):
        GoogleSheetsClient(api_key="")


# ─────────────────────────── sync_google_sheets (con fake) ───────────────────────────


class FakeSheets:
    def __init__(self, rows, err=None):
        self._rows = rows
        self._err = err

    def fetch_rows(self, spreadsheet_id, sheet_range, tipo):
        return self._rows, self._err


def test_sync_google_sheets_ingesta_cartera(session, tenant):
    fake = FakeSheets(
        [
            {"folio": "F-100", "customer": "Cliente Hoja", "phone": "8110000000",
             "amount": "500", "due_date": "2026-07-30"},
        ]
    )
    # El tipo/rango se resuelven del credential (config legada), no del cliente inyectado.
    tenant.config = {"integrations": {"google_sheets": {
        "api_key": "k", "spreadsheet_id": "S", "sheet_range": "F!A:E", "tipo": "facturas"}}}
    session.add(tenant)
    session.flush()
    report = sync_google_sheets(session, tenant, google_sheets_client=fake)
    assert "google_sheets" in report.fuentes
    assert report.pedidos_importados == 1
    inv = session.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == "F-100")
    )
    assert inv is not None
    assert "google_sheets" in (inv.presence or {})


def test_sync_google_sheets_directorio_y_catalogo(session, tenant):
    # Clientes
    tenant.config = {"integrations": {"google_sheets": {
        "api_key": "k", "spreadsheet_id": "S", "sheet_range": "C!A:C", "tipo": "clientes"}}}
    session.add(tenant)
    session.flush()
    fake_dir = FakeSheets([{"name": "Laura", "phone": "8122223333", "email": "laura@x.mx"}])
    r1 = sync_google_sheets(session, tenant, google_sheets_client=fake_dir)
    assert r1.clientes_importados == 1
    c = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Laura"))
    assert c is not None and "google_sheets" in (c.presence or {})

    # Productos
    tenant.config = {"integrations": {"google_sheets": {
        "api_key": "k", "spreadsheet_id": "S", "sheet_range": "P!A:D", "tipo": "productos"}}}
    session.add(tenant)
    session.flush()
    fake_cat = FakeSheets([{"name": "Playera", "sku": "PL-1", "price": "199", "stock": "10"}])
    r2 = sync_google_sheets(session, tenant, google_sheets_client=fake_cat)
    assert r2.productos_importados == 1
    p = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.sku == "PL-1"))
    assert p is not None and "google_sheets" in (p.presence or {})


def test_sync_google_sheets_tipo_desconocido_noop(session, tenant):
    tenant.config = {"integrations": {"google_sheets": {
        "api_key": "k", "spreadsheet_id": "S", "sheet_range": "X!A:Z", "tipo": "loquesea"}}}
    session.add(tenant)
    session.flush()
    report = sync_google_sheets(session, tenant, google_sheets_client=FakeSheets([{"x": 1}]))
    assert report.fuentes == [] and report.pedidos_importados == 0


def test_sync_google_sheets_error_va_a_avisos(session, tenant):
    tenant.config = {"integrations": {"google_sheets": {
        "api_key": "k", "spreadsheet_id": "S", "sheet_range": "F!A:E", "tipo": "facturas"}}}
    session.add(tenant)
    session.flush()
    fake = FakeSheets([], err="Google respondió 403: revisa que la hoja esté compartida.")
    report = sync_google_sheets(session, tenant, google_sheets_client=fake)
    assert report.pedidos_importados == 0
    assert any("Google Sheets" in a for a in report.avisos)
