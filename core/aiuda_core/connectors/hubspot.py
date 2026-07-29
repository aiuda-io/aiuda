"""Conector HubSpot CRM — contactos y pipeline de ventas.

Para qué lo usa aiuda: Carlos (agente de ventas) registra los prospectos que
llegan por WhatsApp o email sin que el vendedor tenga que capturar nada a mano,
y consulta el pipeline para saber qué oportunidades están abiertas y en qué
etapa van. Evita duplicados: si el contacto ya existe en HubSpot lo avisa.

Auth: private app token de la cuenta del usuario (no requiere OAuth).
Docs: https://developers.hubspot.com/docs/api/crm
"""

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings

BASE_URL = "https://api.hubapi.com"


@dataclass
class Oportunidad:
    id: str
    nombre: str
    monto: float
    etapa: str


@dataclass
class Contacto:
    id: str
    nombre: str
    telefono: str
    email: str


class HubSpotClient:
    def __init__(
        self,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.token = token or settings.hubspot_token
        if not self.token:
            raise RuntimeError("HUBSPOT_TOKEN no configurado — ver .env.example")
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
            transport=transport,
        )

    def list_open_deals(self, limit: int = 50) -> list[Oportunidad]:
        """Lista las oportunidades abiertas del pipeline con nombre, monto y etapa.

        Carlos la usa para el resumen diario de ventas y para priorizar a quién
        hacer seguimiento según el monto en juego o la etapa en que está el trato.
        """
        response = self._http.get(
            "/crm/v3/objects/deals",
            params={"limit": limit, "properties": "dealname,amount,dealstage"},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return [
            Oportunidad(
                id=deal["id"],
                nombre=deal.get("properties", {}).get("dealname", ""),
                monto=float(deal.get("properties", {}).get("amount") or 0),
                etapa=deal.get("properties", {}).get("dealstage", ""),
            )
            for deal in results
        ]

    def list_contacts(self, limit: int = 100) -> list[Contacto]:
        """Lista los contactos del CRM con nombre, teléfono y correo. Capacidad
        `directorio_clientes`: alimenta el directorio para que Carlos cotice y dé
        seguimiento sin recapturar. El nombre se arma de firstname + lastname."""
        response = self._http.get(
            "/crm/v3/objects/contacts",
            params={"limit": limit, "properties": "firstname,lastname,phone,email"},
        )
        response.raise_for_status()
        contactos = []
        for c in response.json().get("results", []):
            props = c.get("properties") or {}
            nombre = f"{props.get('firstname') or ''} {props.get('lastname') or ''}".strip()
            contactos.append(
                Contacto(
                    id=c["id"],
                    nombre=nombre,
                    telefono=(props.get("phone") or ""),
                    email=(props.get("email") or ""),
                )
            )
        return contactos

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': valida el private app token y
        devuelve los totales de contactos y oportunidades vía el endpoint de
        búsqueda (limit=1: solo el conteo, no baja los registros)."""

        def _total(objeto: str) -> int:
            response = self._http.post(
                f"/crm/v3/objects/{objeto}/search", json={"limit": 1}
            )
            response.raise_for_status()
            return int(response.json().get("total") or 0)

        return {"contactos": _total("contacts"), "oportunidades": _total("deals")}

    def create_contact(self, email: str, nombre: str, telefono: str = "") -> str:
        """Registra un prospecto nuevo en HubSpot a partir de los datos de WhatsApp.

        Si el contacto ya existe (HTTP 409) levanta RuntimeError para que el
        agente decida si actualizar el registro existente en vez de duplicarlo.
        Devuelve el id del contacto creado.
        """
        response = self._http.post(
            "/crm/v3/objects/contacts",
            json={
                "properties": {
                    "email": email,
                    "firstname": nombre,
                    "phone": telefono,
                }
            },
        )
        if response.status_code == 409:
            raise RuntimeError("El contacto ya existe en HubSpot")
        response.raise_for_status()
        return response.json()["id"]
