"""Conector Stripe — plataforma de pagos en línea.

Para qué lo usa aiuda: detectar cobros ya realizados como fuente que
CONFIRMA pagos, igual que Belvo con el banco ("un dicho no es un pago").
Carlos puede ver qué ventas de su tienda en línea ya liquidaron en Stripe
y cuáles siguen pendientes, sin abrir el dashboard de Stripe.

Auth: Bearer con la API key de la cuenta (sk_live_… en producción).
Docs: https://stripe.com/docs/api/charges/list
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings


@dataclass
class Cobro:
    id: str
    amount: float      # convertido de centavos a pesos/unidad
    currency: str
    description: str
    customer_email: str
    paid: bool
    created: int       # epoch Unix


class StripeClient:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or settings.stripe_api_key
        if not key:
            raise RuntimeError(
                "STRIPE_API_KEY no configurado — ver .env.example"
            )
        self._http = httpx.Client(
            base_url="https://api.stripe.com",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
            transport=transport,
        )

    def list_recent_charges(self, limit: int = 50) -> list[Cobro]:
        """Últimos cobros de la cuenta — la confirmación de que el dinero llegó."""
        response = self._http.get("/v1/charges", params={"limit": limit})
        response.raise_for_status()
        cobros = []
        for c in response.json().get("data", []):
            billing = c.get("billing_details") or {}
            cobros.append(
                Cobro(
                    id=c["id"],
                    # Stripe devuelve centavos; dividimos entre 100 para pesos/dólares
                    amount=float(c.get("amount") or 0) / 100,
                    currency=c.get("currency", ""),
                    description=c.get("description") or "",
                    customer_email=billing.get("email") or "",
                    paid=bool(c.get("paid")),
                    created=int(c.get("created") or 0),
                )
            )
        return cobros

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida la API key contra
        /v1/balance (la verificación canónica de Stripe) y confirma lectura de
        cargos. Devuelve el saldo disponible en la moneda principal (convertido de
        centavos) y cuántos cargos recientes hay."""
        balance = self._http.get("/v1/balance")
        balance.raise_for_status()
        disponibles = balance.json().get("available") or []
        principal = disponibles[0] if disponibles else {}
        charges = self._http.get("/v1/charges", params={"limit": 3})
        charges.raise_for_status()
        recientes = charges.json().get("data", [])
        return {
            "disponible": float(principal.get("amount") or 0) / 100,
            "moneda": (principal.get("currency") or "").upper(),
            "cargos_recientes": len(recientes),
        }

    def match_payment(
        self, cobros: list[Cobro], amount: float
    ) -> Cobro | None:
        """Primer cobro pagado que coincide con el monto (tolerancia 1 peso/dólar).

        Mismo espíritu que BelvoClient.match_payment: cruzar el monto de una
        factura contra los cobros reales para confirmar que sí se cobró.
        """
        for c in cobros:
            if c.paid and abs(c.amount - amount) <= 1.0:
                return c
        return None
