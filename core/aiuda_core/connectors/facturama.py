"""Conector Facturama — PAC certificado por el SAT (CFDI 4.0).

Para qué lo usa aiuda: listar y descargar los CFDI del negocio para que la
cartera tenga respaldo fiscal (procedencia) y Diego concilie contra el banco.
La emisión/timbrado queda para después; primero lectura.

Auth: HTTP Basic (usuario, contraseña de Facturama). Sandbox por default.
Docs: https://apisandbox.facturama.mx/guias
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings


@dataclass
class Cfdi:
    id: str
    folio: str
    total: float
    rfc_receptor: str
    razon_receptor: str
    fecha: str
    status: str


class FacturamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or settings.facturama_base_url).rstrip("/")
        auth = (user or settings.facturama_user, password or settings.facturama_password)
        if not auth[0]:
            raise RuntimeError("FACTURAMA_USER no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=self.base_url, auth=auth, timeout=30, transport=transport
        )

    def list_cfdis(self, status: str = "active", page: int = 0) -> list[Cfdi]:
        response = self._http.get(
            "/cfdi", params={"type": "issuedLite", "status": status, "page": page}
        )
        response.raise_for_status()
        return [
            Cfdi(
                id=c["Id"],
                folio=c.get("Folio") or "",
                total=float(c.get("Total") or 0),
                rfc_receptor=c.get("RfcReceiver") or "",
                razon_receptor=c.get("TaxEntityName") or c.get("Receiver") or "",
                fecha=c.get("Date") or "",
                status=c.get("Status") or status,
            )
            for c in response.json()
        ]

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida usuario y contraseña (Basic)
        pidiendo la primera página de CFDI emitidos. Devuelve cuántos trae la
        muestra (no descarga XML ni pagina completo)."""
        response = self._http.get(
            "/cfdi", params={"type": "issuedLite", "status": "active", "page": 0}
        )
        response.raise_for_status()
        data = response.json()
        return {"cfdi_muestra": len(data) if isinstance(data, list) else 0}

    def download_xml(self, cfdi_id: str) -> bytes:
        """XML del CFDI — la evidencia fiscal que respalda una factura."""
        response = self._http.get(f"/cfdi/xml/issuedLite/{cfdi_id}")
        response.raise_for_status()
        return response.content
