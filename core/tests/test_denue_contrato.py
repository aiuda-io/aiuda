"""Contrato del conector DENUE contra la estructura de la API pública del INEGI.

El fixture (``data/denue_buscar_contrato.json``) trae la estructura DOCUMENTADA
de ``Buscar`` — todos los campos que INEGI publica — servida por MockTransport:
si INEGI renombra un campo que usamos, o alguien recorta el fixture, esto truena.
Honesto: NO es una respuesta grabada en vivo (no hay token configurado); cuando
haya token, se graba la respuesta real y reemplaza la sección ``respuesta``.
"""

import json
from pathlib import Path

import httpx
import pytest

from aiuda_core.connectors.denue import DenueClient

FIXTURE = Path(__file__).parent / "data" / "denue_buscar_contrato.json"

# Los campos que INEGI documenta para cada unidad económica de Buscar.
CAMPOS_DOCUMENTADOS = {
    "CLEE", "Id", "Nombre", "Razon_social", "Clase_actividad", "Estrato",
    "Tipo_vialidad", "Calle", "Num_Exterior", "Num_Interior", "Colonia", "CP",
    "Ubicacion", "Telefono", "Correo_e", "Sitio_internet", "Tipo",
    "Longitud", "Latitud", "CentroComercial", "TipoCentroComercial", "NumLocal",
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_trae_todos_los_campos_documentados():
    """Guardia del contrato: cada unidad del fixture trae los 22 campos que
    documenta INEGI. Si alguien lo recorta, el fixture deja de ser contrato."""
    respuesta = _fixture()["respuesta"]
    assert len(respuesta) >= 2  # una contactable y una sin teléfono/correo
    for unidad in respuesta:
        assert set(unidad.keys()) == CAMPOS_DOCUMENTADOS


def test_buscar_parsea_el_contrato_documentado():
    """El conector entiende la respuesta con la forma documentada: request bien
    armado (condición citada, punto, radio, token) y campos mapeados a Negocio."""
    capturado = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # raw_path = lo que va en el cable: la condición debe ir %-citada.
        capturado["raw"] = request.url.raw_path.decode()
        return httpx.Response(200, json=_fixture()["respuesta"])

    client = DenueClient(token="tok-contrato", transport=httpx.MockTransport(handler))
    negocios = client.buscar("ferreteria y tlapaleria", 19.4326, -99.1332, 1000)

    assert capturado["raw"] == (
        "/app/api/denue/v1/consulta/Buscar/ferreteria%20y%20tlapaleria/"
        "19.4326,-99.1332/1000/tok-contrato"
    )
    assert len(negocios) == 2
    central = negocios[0]
    assert central.id == "2825563"
    assert central.nombre == "FERRETERIA LA CENTRAL"
    assert central.razon_social == "FERRETERA LA CENTRAL SA DE CV"
    assert central.actividad == "Comercio al por menor en ferreterías y tlapalerías"
    assert central.telefono == "5555550110"
    assert central.correo == "CONTACTO@FERRECENTRAL.MX"
    assert central.direccion == "AV JUAREZ 10, CENTRO, 06000"
    assert central.contactable is True

    tornillo = negocios[1]
    assert tornillo.telefono == "" and tornillo.correo == ""
    assert tornillo.contactable is False  # sin teléfono ni correo no hay a quién marcar


def test_token_invalido_propaga_remote_protocol_error():
    """Verificado en vivo (2026-07-07): con token inválido INEGI responde la
    línea de estado 'HTTP/1.1 000', que httpx reporta como RemoteProtocolError.
    El conector la deja subir tal cual (el API la traduce a un error legible),
    y sigue siendo RequestError, la familia que el API cacha al final."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            "InformationalResponse status_code should be in range [100, 200), not 0",
            request=request,
        )

    client = DenueClient(token="token-invalido", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.RemoteProtocolError):
        client.buscar("todos", 19.4326, -99.1332, 500)
    assert issubclass(httpx.RemoteProtocolError, httpx.RequestError)
