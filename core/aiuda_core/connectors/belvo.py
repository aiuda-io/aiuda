"""Conector Belvo — open banking LATAM.

Para qué lo usa aiuda: detectar pagos recibidos en las cuentas del negocio y
confirmar facturas sin que el dueño teclee nada ("un dicho no es un pago": el
banco es la fuente que verifica). Diego (conciliación) cruza estos movimientos
contra CFDI.

Auth: HTTP Basic con (secret_id, secret_password). Sandbox por default.
Docs: https://developers.belvo.com
"""

from dataclasses import dataclass
from datetime import date

import httpx

from aiuda_core.config import settings


@dataclass
class BankTransaction:
    id: str
    amount: float
    description: str
    value_date: str
    type: str  # INFLOW | OUTFLOW
    account_id: str


class BelvoClient:
    def __init__(
        self,
        base_url: str | None = None,
        secret_id: str | None = None,
        secret_password: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or settings.belvo_base_url).rstrip("/")
        auth = (
            secret_id or settings.belvo_secret_id,
            secret_password or settings.belvo_secret_password,
        )
        if not auth[0]:
            raise RuntimeError("BELVO_SECRET_ID no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=self.base_url, auth=auth, timeout=30, transport=transport
        )

    def list_accounts(self, link_id: str) -> list[dict]:
        response = self._http.get("/api/accounts/", params={"link": link_id})
        response.raise_for_status()
        return response.json().get("results", [])

    def test_connection(self, link_id: str = "") -> dict:
        """Prueba ligera para 'Probar conexión': valida las llaves (Basic) listando
        los links del negocio. Si se pasa un link, cuenta además sus cuentas
        bancarias (el mismo dato que alimenta la conciliación de Diego)."""
        response = self._http.get("/api/links/")
        response.raise_for_status()
        links = response.json().get("results", [])
        cuentas = len(self.list_accounts(link_id)) if link_id else None
        return {"links": len(links), "cuentas": cuentas}

    def list_inflows(
        self, link_id: str, date_from: date, date_to: date
    ) -> list[BankTransaction]:
        """Depósitos recibidos en el periodo — lo que confirma pagos de clientes."""
        response = self._http.get(
            "/api/transactions/",
            params={
                "link": link_id,
                "value_date__gte": date_from.isoformat(),
                "value_date__lte": date_to.isoformat(),
                "type": "INFLOW",
            },
        )
        response.raise_for_status()
        return [
            BankTransaction(
                id=t["id"],
                amount=float(t["amount"]),
                description=t.get("description") or "",
                value_date=t["value_date"],
                type=t["type"],
                account_id=(t.get("account") or {}).get("id", ""),
            )
            for t in response.json().get("results", [])
        ]

    def match_payment(self, inflows: list[BankTransaction], amount: float) -> BankTransaction | None:
        """Primer depósito que coincide con el monto de una factura (tolerancia 1 peso)."""
        for t in inflows:
            if abs(t.amount - amount) <= 1.0:
                return t
        return None
