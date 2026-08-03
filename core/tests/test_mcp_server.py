"""El servidor MCP: protocolo mínimo y, sobre todo, las rejas.

Lo que se fija aquí no es "responde bien", es que un modelo corriendo en el arnés del
dueño NO pueda salirse de su alcance: ni llamar una aiudita que no tiene, ni cambiar de
negocio pasando tenant_id, ni encontrar una herramienta que envíe algo.
"""

from __future__ import annotations

import io
import json

import pytest

from aiuda_core.mcp.server import Sesion, bucle, herramientas_de
from aiuda_core.models import Ayudante


@pytest.fixture()
def ayudante(session, tenant):
    a = Ayudante(
        tenant_id=tenant.id,
        name="Male",
        appearance={},
        aiuditas={"cobranza.consultar_cartera": {}},
    )
    session.add(a)
    session.flush()
    return a


def _hablar(sesion: Sesion, mensajes: list[dict]) -> list[dict]:
    entrada = io.StringIO("\n".join(json.dumps(m) for m in mensajes) + "\n")
    salida = io.StringIO()
    bucle(entrada, salida, sesion)
    return [json.loads(x) for x in salida.getvalue().splitlines() if x.strip()]


def _rpc(mid, method, **params):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}


# ---------- protocolo ----------

def test_initialize_devuelve_la_version_que_pidio_el_cliente(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(s, [_rpc(0, "initialize", protocolVersion="2025-11-25")])
    assert r["result"]["protocolVersion"] == "2025-11-25"
    assert r["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert r["result"]["serverInfo"]["name"] == "aiuda"


def test_las_notificaciones_no_llevan_respuesta(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    assert _hablar(s, [{"jsonrpc": "2.0", "method": "notifications/initialized"}]) == []


def test_json_invalido_no_tumba_la_sesion(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    entrada = io.StringIO('{no soy json\n' + json.dumps(_rpc(1, "ping")) + "\n")
    salida = io.StringIO()
    bucle(entrada, salida, s)
    rs = [json.loads(x) for x in salida.getvalue().splitlines() if x.strip()]
    assert rs[0]["error"]["code"] == -32700
    assert rs[1]["result"] == {}  # la sesión siguió viva


def test_metodo_desconocido_es_error_de_protocolo(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(s, [_rpc(1, "resources/list")])
    assert r["error"]["code"] == -32601


# ---------- alcance: qué herramientas existen ----------

def test_solo_lista_las_aiuditas_que_el_dueno_le_activo(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(s, [_rpc(1, "tools/list")])
    nombres = [t["name"] for t in r["result"]["tools"]]
    assert nombres == ["consultar_cartera"]


def test_un_ayudante_sin_aiuditas_no_expone_ninguna(session, tenant):
    a = Ayudante(tenant_id=tenant.id, name="Nuevo", appearance={}, aiuditas={})
    session.add(a)
    session.flush()
    s = Sesion(session, tenant, a)
    [r] = _hablar(s, [_rpc(1, "tools/list")])
    assert r["result"]["tools"] == []


def test_no_existe_ninguna_herramienta_que_envie_o_escriba():
    """La garantía central: la soberanía humana no depende del prompt.

    Se listan TODAS las aiuditas de chat que existen, no las de un ayudante. Si algún
    día alguien agrega una que envíe o escriba a CHAT_AIUDITAS, este test truena."""
    from aiuda_core.aiuditas.chat import CHAT_AIUDITAS

    todas = herramientas_de(list(CHAT_AIUDITAS))
    assert todas, "sin herramientas el test no probaría nada"
    prohibidos = ("enviar", "mandar", "registrar", "redactar", "crear", "borrar", "aprobar")
    for t in todas:
        assert not any(p in t["name"] for p in prohibidos), t["name"]
        assert t["annotations"]["readOnlyHint"] is True


# ---------- alcance: qué se puede llamar ----------

def test_llamar_una_aiudita_que_no_tiene_es_isError_no_una_excepcion(session, tenant, ayudante):
    """isError y no un error de JSON-RPC: el modelo tiene que poder leerlo y corregir.
    Un error de protocolo mataría la sesión entera."""
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(s, [_rpc(1, "tools/call", name="consultar_agenda", arguments={})])
    assert r["result"]["isError"] is True
    assert "error" not in r
    assert "no es una herramienta de este ayudante" in r["result"]["content"][0]["text"]


def test_no_se_puede_cambiar_de_negocio_pasando_tenant_id(session, tenant, ayudante):
    """El tenant se impone desde el proceso, no se acepta del modelo."""
    otro = "tenant-de-alguien-mas"
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(
        s,
        [_rpc(1, "tools/call", name="consultar_cartera", arguments={"tenant_id": otro})],
    )
    # No revienta por argumento inesperado: lo descarta y contesta con lo del tenant real.
    assert r["result"]["isError"] is False
    assert otro not in r["result"]["content"][0]["text"]


def test_una_llamada_valida_devuelve_texto(session, tenant, ayudante):
    s = Sesion(session, tenant, ayudante)
    [r] = _hablar(s, [_rpc(1, "tools/call", name="consultar_cartera", arguments={})])
    assert r["result"]["isError"] is False
    assert isinstance(r["result"]["content"][0]["text"], str)
