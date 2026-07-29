"""Conector Google Sheets — una hoja de cálculo compartida como fuente.

Para qué lo usa aiuda: el negocio que lleva su cartera, su directorio o su
catálogo en una hoja de Google la conecta como fuente de solo lectura. aiuda lee
los valores, mapea las columnas a sus campos y los ingesta por los MISMOS
lectores que las conexiones a la medida (engine/sync._CUSTOM_READERS), sin
duplicar lógica.

Auth SIMPLE y autoservible (esta tanda): una API key de Google Cloud + el ID de
la hoja. La hoja DEBE estar compartida como "Cualquier persona con el enlace ·
Lector"; con eso la Sheets API v4 (spreadsheets.values.get) la lee usando solo la
API key (?key=...), sin OAuth ni pantalla de consentimiento ni tokens que rotar.
MEJORA FUTURA (documentada, por cablear): OAuth server-side para leer hojas
privadas sin abrirlas al público.

Modo mapeo (estilo connectors/custom_api): el dueño declara un `range`
("Facturas!A:F") y el `tipo` de datos (facturas | clientes | productos). La
PRIMERA fila del rango son los encabezados; aiuda los mapea a sus campos por
NOMBRE convencional, reusando las convenciones del importador inteligente
(smart_import) — sin LLM: coincidencia por encabezado (exacta primero, luego por
contención). Cada fila se reduce a un dict con los campos que el lector espera.

Docs: https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets.values/get
"""

import unicodedata
import urllib.parse

import httpx

from aiuda_core.config import settings

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

# Tipos de hoja que aiuda sabe ingerir hoy (cada uno cae a un lector custom).
TIPOS = ("facturas", "clientes", "productos")

# Convenciones de encabezado -> campo de aiuda, por tipo. Las llaves de salida son
# EXACTAMENTE las que esperan los lectores custom (engine/sync._custom_cartera /
# _custom_directorio / _custom_catalogo). Los alias van normalizados (minúsculas,
# sin acentos, sin espacios ni signos); reusan los nombres del importador
# inteligente (smart_import.ENTITY_FIELDS) para no divergir.
_CONVENCIONES: dict[str, dict[str, list[str]]] = {
    "facturas": {
        "folio": ["folio", "factura", "numero", "documento", "referencia"],
        "customer": ["cliente", "nombre", "razonsocial", "customer"],
        "phone": ["telefono", "tel", "whatsapp", "celular", "movil", "phone"],
        "amount": ["monto", "importe", "total", "saldo", "amount"],
        "due_date": ["vencimiento", "fechavencimiento", "vence", "limite", "duedate"],
        "external_id": ["externalid", "idexterno", "uuid", "id"],
    },
    "clientes": {
        "name": ["nombre", "cliente", "razonsocial", "contacto", "name"],
        "phone": ["telefono", "tel", "whatsapp", "celular", "movil", "phone"],
        "email": ["correo", "email", "mail", "correoelectronico"],
        "external_id": ["externalid", "idexterno", "id"],
    },
    "productos": {
        "name": ["nombre", "producto", "descripcion", "articulo", "name"],
        "sku": ["sku", "clave", "codigo", "code"],
        "price": ["precio", "price", "costo", "importe"],
        "stock": ["existencia", "stock", "inventario", "cantidad", "disponible"],
        "external_id": ["externalid", "idexterno", "id"],
    },
}


def _norm(texto) -> str:
    """Normaliza un encabezado para comparar: minúsculas, sin acentos, solo
    alfanumérico ('Fecha de Vencimiento' -> 'fechadevencimiento')."""
    s = unicodedata.normalize("NFKD", str(texto if texto is not None else ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def inferir_mapeo(headers: list, tipo: str) -> dict[str, int]:
    """Mapea {campo_aiuda: índice de columna} leyendo la fila de encabezados por
    nombre convencional. Coincidencia EXACTA primero (una columna 'Teléfono' gana
    sobre 'Teléfono del cliente'); una segunda pasada acepta contención para
    encabezados compuestos. Cada columna se asigna a un solo campo; cada campo se
    queda con su primera coincidencia. Un `tipo` desconocido devuelve {}."""
    conv = _CONVENCIONES.get(tipo, {})
    norm = [_norm(h) for h in headers]
    mapeo: dict[str, int] = {}
    usados: set[int] = set()

    for exacta in (True, False):
        for campo, alias in conv.items():
            if campo in mapeo:
                continue
            for a in alias:
                idx = None
                for i, nh in enumerate(norm):
                    if i in usados or not nh:
                        continue
                    if (nh == a) if exacta else (a in nh):
                        idx = i
                        break
                if idx is not None:
                    mapeo[campo] = idx
                    usados.add(idx)
                    break
    return mapeo


def _mensaje_http(exc: httpx.HTTPStatusError) -> str:
    """Traduce el error de la Sheets API a algo accionable para el dueño."""
    code = exc.response.status_code
    if code == 403:
        return (
            "Google respondió 403: revisa que la hoja esté compartida como "
            "'Cualquier persona con el enlace · Lector' y que la API key sea válida."
        )
    if code == 404:
        return "Google respondió 404: no se encontró la hoja. Revisa el ID."
    if code == 400:
        return "Google respondió 400: revisa el rango (p.ej. 'Facturas!A:F')."
    return f"Google respondió {code}."


class GoogleSheetsClient:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key or settings.google_sheets_api_key
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_SHEETS_API_KEY no configurada — captura la API key de Google."
            )
        self._http = httpx.Client(base_url=SHEETS_API, timeout=30, transport=transport)

    def _values(self, spreadsheet_id: str, sheet_range: str) -> list[list]:
        """spreadsheets.values.get crudo: devuelve la matriz de valores (incluye la
        fila de encabezados). Lanza HTTPStatusError si Google rechaza."""
        quoted = urllib.parse.quote(sheet_range, safe="")
        resp = self._http.get(
            f"/{spreadsheet_id}/values/{quoted}", params={"key": self.api_key}
        )
        resp.raise_for_status()
        return resp.json().get("values", []) or []

    def fetch_rows(
        self, spreadsheet_id: str, sheet_range: str, tipo: str
    ) -> tuple[list[dict], str | None]:
        """Lee el rango y mapea cada fila a los campos que el lector de `tipo`
        espera. Devuelve (filas, error_legible): nunca truena, el error viaja como
        string (igual que custom_api.fetch_rows) para que la corrida no se caiga."""
        if not spreadsheet_id:
            return [], "Falta el ID de la hoja."
        if not sheet_range:
            return [], "Falta el rango (p.ej. 'Facturas!A:F')."
        if tipo not in _CONVENCIONES:
            return [], f"Tipo de datos no soportado: {tipo!r} (usa facturas, clientes o productos)."
        try:
            values = self._values(spreadsheet_id, sheet_range)
        except httpx.HTTPStatusError as exc:
            return [], _mensaje_http(exc)
        except Exception as exc:  # noqa: BLE001 — red caída, etc.: error legible, no crash
            return [], f"No se pudo leer la hoja: {exc}"
        if not values:
            return [], None  # rango vacío: no-op honesto
        headers = values[0]
        mapeo = inferir_mapeo(headers, tipo)
        if not mapeo:
            return [], (
                "No reconocí columnas conocidas en la primera fila del rango. "
                "Ponle encabezados como los que usa aiuda (p.ej. Folio, Cliente, Monto)."
            )
        rows: list[dict] = []
        for raw in values[1:]:
            row = {campo: (raw[i] if i < len(raw) else None) for campo, i in mapeo.items()}
            if any(v not in (None, "") for v in row.values()):
                rows.append(row)
        return rows, None

    def test_connection(self, spreadsheet_id: str, sheet_range: str = "") -> dict:
        """Verifica el acceso a la hoja: lee su metadata (título y pestañas) y, si
        hay rango, cuenta las filas de datos. Un error de permisos/ID llega como
        HTTPStatusError y lo traduce el tester."""
        meta = self._http.get(
            f"/{spreadsheet_id}",
            params={"key": self.api_key, "fields": "properties.title,sheets.properties.title"},
        )
        meta.raise_for_status()
        body = meta.json()
        title = (body.get("properties") or {}).get("title") or ""
        sheets = body.get("sheets") or []
        rows = 0
        if sheet_range:
            values = self._values(spreadsheet_id, sheet_range)
            rows = max(0, len(values) - 1)  # descuenta la fila de encabezados
        return {"title": title, "sheets": len(sheets), "rows": rows}
