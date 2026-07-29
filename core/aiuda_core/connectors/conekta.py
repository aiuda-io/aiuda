"""Conector Conekta — cobro por link (OXXO Pay / SPEI / tarjeta) y confirmación de pago.

Conekta es clave para el mercado PyME mexicano porque cobra a quien NO usa tarjeta: OXXO
Pay (efectivo con referencia) y SPEI (transferencia). Dos usos para aiuda:
  1. link_de_pago  — crea un checkout y devuelve el link que el ayudante manda por
     WhatsApp con el recordatorio; el cliente paga con tarjeta, en OXXO o por SPEI.
  2. confirmacion_pago — detecta órdenes pagadas para confirmar facturas.

Auth: Basic con la private key (key_… / sk_…) como usuario y contraseña vacía; header de
versión de API. Contra el contrato documentado (api.conekta.io); PENDIENTE de verificar en
vivo. Docs: https://developers.conekta.com/reference
"""

import base64
from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://api.conekta.io"
API_VERSION = "application/vnd.conekta-v2.1.0+json"


@dataclass
class PagoConekta:
    id: str
    amount: float
    currency: str
    description: str
    paid: bool
    created: int


class ConektaClient:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or settings.conekta_api_key
        if not key:
            raise RuntimeError("CONEKTA_API_KEY no configurado — ver .env.example")
        basic = base64.b64encode(f"{key}:".encode()).decode()
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Accept": API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30,
            transport=transport,
        )

    def crear_link_pago(self, monto: float, concepto: str, referencia: str = "") -> str:
        """Crea un checkout (link de pago) que acepta tarjeta, OXXO Pay y SPEI, y devuelve
        la URL para el cliente. Conekta cobra en CENTAVOS."""
        centavos = int(round(float(monto) * 100))
        body: dict = {
            "name": concepto or "Pago",
            "type": "PaymentLink",
            "recurrent": False,
            "expires_at": None,
            "allowed_payment_methods": ["cash", "card", "bank_transfer"],
            "line_items": [{"name": concepto or "Pago", "unit_price": centavos, "quantity": 1}],
        }
        if referencia:
            body["metadata"] = {"reference": referencia}
        resp = self._http.post("/checkouts", json=body)
        resp.raise_for_status()
        data = resp.json()
        link = data.get("url") or (data.get("data") or {}).get("url") or ""
        if not link:
            raise RuntimeError("Conekta no devolvió un link de pago.")
        return link

    def list_recent_payments(self, limit: int = 50) -> list[PagoConekta]:
        """Órdenes recientes — la confirmación de que el dinero llegó."""
        resp = self._http.get("/orders", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        pagos = []
        for o in rows or []:
            pagos.append(
                PagoConekta(
                    id=str(o.get("id") or ""),
                    amount=float(o.get("amount") or 0) / 100,  # centavos -> pesos
                    currency=o.get("currency", "MXN"),
                    description=(o.get("line_items") or {}).get("data", [{}])[0].get("name", "")
                    if isinstance(o.get("line_items"), dict)
                    else "",
                    paid=(o.get("payment_status") == "paid"),
                    created=int(o.get("created_at") or 0),
                )
            )
        return pagos

    def match_payment(self, pagos: list[PagoConekta], amount: float) -> PagoConekta | None:
        """Primera orden pagada que coincide con el monto (tolerancia 1 peso)."""
        for p in pagos:
            if p.paid and abs(p.amount - amount) <= 1.0:
                return p
        return None

    def test_connection(self) -> dict:
        """Valida la private key pidiendo una orden (limit=1). No cobra nada."""
        resp = self._http.get("/orders", params={"limit": 1})
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        return {"ordenes_visibles": len(rows or [])}
