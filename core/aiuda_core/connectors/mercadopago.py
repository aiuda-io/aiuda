"""Conector Mercado Pago — cobro por link y confirmación de pago.

Dos usos para aiuda, ambos de cobranza:
  1. link_de_pago  — genera un link de pago (Checkout Pro) que el ayudante manda por
     WhatsApp junto con el recordatorio: el cliente paga con un clic.
  2. confirmacion_pago — detecta pagos aprobados como fuente que CONFIRMA facturas,
     igual que Belvo/Stripe ("un dicho no es un pago").

Auth: Bearer con el access token de la cuenta (APP_USR-… en producción). Es la pasarela
#1 de México y su link de pago por WhatsApp es el fit natural de un cobrador.
Contra el contrato documentado (api.mercadopago.com); PENDIENTE de verificar en vivo.
Docs: https://www.mercadopago.com.mx/developers/es/reference
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://api.mercadopago.com"


@dataclass
class PagoMP:
    id: str
    amount: float
    currency: str
    description: str
    payer_email: str
    approved: bool
    created: str  # ISO8601


class MercadoPagoClient:
    def __init__(
        self,
        access_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        token = access_token or settings.mercadopago_access_token
        if not token:
            raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
            transport=transport,
        )

    def crear_link_pago(self, monto: float, concepto: str, referencia: str = "") -> str:
        """Crea una preferencia de Checkout Pro y devuelve el link (init_point) para
        mandarle al cliente. `referencia` (external_reference) permite luego casar el
        pago con la factura."""
        body = {
            "items": [{"title": concepto or "Pago", "quantity": 1, "unit_price": round(float(monto), 2)}],
        }
        if referencia:
            body["external_reference"] = referencia
        resp = self._http.post("/checkout/preferences", json=body)
        resp.raise_for_status()
        data = resp.json()
        link = data.get("init_point") or data.get("sandbox_init_point") or ""
        if not link:
            raise RuntimeError("Mercado Pago no devolvió un link de pago.")
        return link

    def list_recent_payments(self, limit: int = 50) -> list[PagoMP]:
        """Pagos recientes de la cuenta — la confirmación de que el dinero llegó."""
        resp = self._http.get(
            "/v1/payments/search",
            params={"sort": "date_created", "criteria": "desc", "limit": limit},
        )
        resp.raise_for_status()
        pagos = []
        for p in resp.json().get("results", []):
            payer = p.get("payer") or {}
            pagos.append(
                PagoMP(
                    id=str(p.get("id") or ""),
                    amount=float(p.get("transaction_amount") or 0),
                    currency=p.get("currency_id", ""),
                    description=p.get("description") or "",
                    payer_email=payer.get("email") or "",
                    approved=(p.get("status") == "approved"),
                    created=p.get("date_created") or "",
                )
            )
        return pagos

    def match_payment(self, pagos: list[PagoMP], amount: float) -> PagoMP | None:
        """Primer pago aprobado que coincide con el monto (tolerancia 1 peso)."""
        for p in pagos:
            if p.approved and abs(p.amount - amount) <= 1.0:
                return p
        return None

    def test_connection(self) -> dict:
        """Valida el access token contra /users/me (canónico) y cuenta pagos recientes.
        No cobra ni mueve dinero."""
        me = self._http.get("/users/me")
        me.raise_for_status()
        info = me.json()
        pagos = self._http.get("/v1/payments/search", params={"limit": 3})
        pagos.raise_for_status()
        return {
            "cuenta": info.get("nickname") or info.get("email") or "",
            "pagos_recientes": len(pagos.json().get("results", [])),
        }
