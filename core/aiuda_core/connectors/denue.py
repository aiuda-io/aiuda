"""Conector DENUE — INEGI (directorio público de 5.5M unidades económicas).

Para qué lo usa aiuda: Sofía (prospección) encuentra negocios reales por giro y
zona, con teléfono y dirección, desde una fuente pública y gratuita del Estado
mexicano. Token gratuito en https://www.inegi.org.mx/app/api/denue/

API: GET /app/api/denue/v1/consulta/Buscar/{condicion}/{lat,lng}/{radio_m}/{token}
"""

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from aiuda_core.config import settings

BASE_URL = "https://www.inegi.org.mx"


@dataclass
class Negocio:
    id: str
    nombre: str
    razon_social: str
    actividad: str
    telefono: str
    correo: str
    direccion: str

    @property
    def contactable(self) -> bool:
        return bool(self.telefono or self.correo)


class DenueClient:
    def __init__(self, token: str | None = None, transport: httpx.BaseTransport | None = None):
        self.token = token or settings.denue_token
        if not self.token:
            raise RuntimeError("DENUE_TOKEN no configurado — gratis en inegi.org.mx")
        self._http = httpx.Client(base_url=BASE_URL, timeout=30, transport=transport)

    def buscar(
        self, condicion: str, lat: float, lng: float, radio_m: int = 5000
    ) -> list[Negocio]:
        """Negocios por palabra clave alrededor de un punto (ej. 'ferreteria', CDMX, 5km)."""
        path = (
            f"/app/api/denue/v1/consulta/Buscar/{quote(condicion)}/"
            f"{lat},{lng}/{radio_m}/{self.token}"
        )
        response = self._http.get(path)
        response.raise_for_status()
        return [
            Negocio(
                id=item.get("Id", ""),
                nombre=item.get("Nombre", ""),
                razon_social=item.get("Razon_social", ""),
                actividad=item.get("Clase_actividad", ""),
                telefono=item.get("Telefono", ""),
                correo=item.get("Correo_e", ""),
                direccion=", ".join(
                    p
                    for p in (
                        item.get("Calle", ""),
                        item.get("Colonia", ""),
                        item.get("CP", ""),
                    )
                    if p
                ),
            )
            for item in response.json()
        ]
