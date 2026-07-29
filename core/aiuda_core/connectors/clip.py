"""Conector Clip — cobro por link de pago y confirmación de pago.

Clip es la terminal y los links de pago más difundidos entre PyMEs y changarros de
México: baja fricción de adopción. Dos usos para aiuda:
  1. link_de_pago  — genera un link de pago que el ayudante manda por WhatsApp con el
     recordatorio.
  2. confirmacion_pago — detecta pagos ya cobrados para confirmar facturas.

Auth: Bearer con la API key de la cuenta (portal de Clip). Contra el contrato documentado
(api.payclip.com); PENDIENTE de verificar en vivo.
Docs: https://developer.clip.mx/reference
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://api.payclip.com"


@dataclass
class PagoClip:
    id: str
    amount: float
    currency: str
    description: str
    paid: bool
    created: str


class ClipClient:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or settings.clip_api_key
        if not key:
            raise RuntimeError("CLIP_API_KEY no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=30,
            transport=transport,
        )

    def crear_link_pago(self, monto: float, concepto: str, referencia: str = "") -> str:
        """Crea un link de pago (payment request) y devuelve la URL para el cliente."""
        body: dict = {
            "amount": round(float(monto), 2),
            "currency": "MXN",
            "purchase_description": concepto or "Pago",
        }
        if referencia:
            body["metadata"] = {"reference": referencia}
        resp = self._http.post("/v2/checkout/payment-links", json=body)
        resp.raise_for_status()
        data = resp.json()
        link = data.get("payment_request_url") or data.get("url") or ""
        if not link:
            raise RuntimeError("Clip no devolvió un link de pago.")
        return link

    def list_recent_payments(self, limit: int = 50) -> list[PagoClip]:
        """Pagos recientes de la cuenta — la confirmación de que el dinero llegó."""
        resp = self._http.get("/v2/payments", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        pagos = []
        for p in rows or []:
            pagos.append(
                PagoClip(
                    id=str(p.get("id") or ""),
                    amount=float(p.get("amount") or 0),
                    currency=p.get("currency", "MXN"),
                    description=p.get("purchase_description") or p.get("description") or "",
                    paid=(p.get("status") in ("approved", "paid", "completed")),
                    created=p.get("created_at") or "",
                )
            )
        return pagos

    def match_payment(self, pagos: list[PagoClip], amount: float) -> PagoClip | None:
        """Primer pago liquidado que coincide con el monto (tolerancia 1 peso)."""
        for p in pagos:
            if p.paid and abs(p.amount - amount) <= 1.0:
                return p
        return None

    def test_connection(self) -> dict:
        """Valida la API key pidiendo una página mínima de pagos. No cobra nada."""
        resp = self._http.get("/v2/payments", params={"limit": 1})
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        return {"pagos_visibles": len(rows or [])}
