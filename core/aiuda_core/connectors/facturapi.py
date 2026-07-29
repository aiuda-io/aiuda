"""Conector Facturapi — PAC developer-friendly para CFDI 4.0.

Para qué lo usa aiuda: misma categoría que Facturama (lectura de CFDI como
respaldo fiscal de la cartera); el negocio elige su PAC y aiuda habla con el
que ya tenga. Sandbox con key sk_test_…

Auth: HTTP Basic con (api_key, ""). Docs: https://docs.facturapi.io
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://www.facturapi.io"


@dataclass
class FacturapiCfdi:
    id: str
    folio: str
    total: float
    rfc_receptor: str
    razon_receptor: str
    fecha: str
    status: str


class FacturapiClient:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        key = api_key or settings.facturapi_api_key
        if not key:
            raise RuntimeError("FACTURAPI_API_KEY no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=BASE_URL, auth=(key, ""), timeout=30, transport=transport
        )

    def list_invoices(self, page: int = 1, limit: int = 50) -> list[FacturapiCfdi]:
        response = self._http.get("/v2/invoices", params={"page": page, "limit": limit})
        response.raise_for_status()
        return [
            FacturapiCfdi(
                id=item["id"],
                folio=str(item.get("folio_number") or ""),
                total=float(item.get("total") or 0),
                rfc_receptor=(item.get("customer") or {}).get("tax_id", ""),
                razon_receptor=(item.get("customer") or {}).get("legal_name", ""),
                fecha=item.get("created_at", ""),
                status=item.get("status", ""),
            )
            for item in response.json().get("data", [])
        ]

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida la API key pidiendo una
        factura (limit=1) y lee el total de la paginación. No descarga los CFDI."""
        response = self._http.get("/v2/invoices", params={"page": 1, "limit": 1})
        response.raise_for_status()
        body = response.json()
        total = body.get("total_results")
        if total is None:
            total = len(body.get("data", []))
        return {"facturas": int(total)}

    def download_xml(self, invoice_id: str) -> bytes:
        """XML del CFDI — la evidencia fiscal que respalda una factura."""
        response = self._http.get(f"/v2/invoices/{invoice_id}/xml")
        response.raise_for_status()
        return response.content
