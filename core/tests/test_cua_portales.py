"""Misiones plantilla corriendo DE VERDAD contra los portales de prueba locales.

Aquí no hay mocks del navegador: un Chromium headless real (extra `cua`) opera los
portales de `cua/portales/` (login + tabla, buscador + lista) con el agente de GUION
determinista (`cua/scripted.py`) en el rol del modelo. Se prueba el ciclo completo:
instrucción del dueño → prompt → acciones en el navegador → portal operado → datos +
evidencia (capturas PNG reales) persistidos en el recado.

Los tests que abren navegador se saltan si el extra `cua` o el Chromium no están
instalados. Los deterministas puros (sin navegador) corren siempre.
"""

import asyncio
from dataclasses import replace

import pytest

from aiuda_core.cua.mission import build_mission_prompt
from aiuda_core.cua.portales import notas_portal_demo, servir_portales, url_portal_demo
from aiuda_core.cua.runner import PLANTILLAS, CuaRunner
from aiuda_core.cua.scripted import (
    DATOS_PORTAL,
    EXPEDIENTE_DEFAULT,
    AgenteGuion,
    expediente_en,
)

PNG_MAGIA = b"\x89PNG\r\n\x1a\n"


def _computer_con_memoria():
    """LocalComputer que recuerda el DOM final antes de cerrar: permite verificar qué
    mostró el portal DE VERDAD (un guion siempre entrega sus datos; el DOM no miente)."""
    from aiuda_core.cua.computer import LocalComputer

    class ComputerConMemoria(LocalComputer):
        def __init__(self):
            super().__init__(headless=True)
            self.texto_final = ""

        async def __aexit__(self, *exc):
            try:
                if self.page is not None:
                    self.texto_final = await self.page.inner_text("body")
            finally:
                await super().__aexit__(*exc)

    return ComputerConMemoria()


@pytest.fixture(scope="module")
def chromium():
    """Salta si el navegador real no está disponible (extra `cua` + Chromium)."""
    from aiuda_core.cua.computer import estado_navegador

    listo, detalle = estado_navegador()
    if not listo:
        pytest.skip(detalle)


@pytest.fixture(scope="module")
def portales():
    with servir_portales() as base:
        yield base


# --- Deterministas puros (sin navegador): la instrucción gobierna el guion ---------


def test_guion_extrae_el_expediente_de_la_instruccion():
    assert expediente_en("Revisa el expediente 77/2025 por favor") == "77/2025"
    assert expediente_en("EXPEDIENTE 9/2024, urgente") == "9/2024"
    assert expediente_en("sin numero explicito") == EXPEDIENTE_DEFAULT


def test_guion_obedece_la_instruccion_del_prompt_sin_navegador():
    """Ciclo instrucción → prompt → acciones, sin Chromium: el guion lee el prompt REAL
    que arma el runner y teclea el expediente que la instrucción indica."""

    class FakeComputer:
        width, height = 1280, 800

        def __init__(self):
            self.acciones = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def goto(self, url):
            self.acciones.append(("goto", url))

        async def screenshot(self):
            return PNG_MAGIA + b"fake"

        async def act(self, action, **kw):
            self.acciones.append((action, kw))

    mission = replace(
        PLANTILLAS["tribunal_acuerdos"],
        url_inicio="https://tribunal.example/",
        notas="Instrucción específica del dueño: revisa el expediente 77/2025",
    )
    assert "77/2025" in build_mission_prompt(mission)  # la instrucción viaja en el prompt
    comp = FakeComputer()
    runner = CuaRunner(client=AgenteGuion("tribunal_acuerdos"), computer=comp)
    result = asyncio.run(runner.run(mission))
    assert result.success is True
    assert ("type", {"text": "77/2025"}) in comp.acciones  # tecleó LO QUE PIDIÓ el dueño
    assert result.data["acuerdos"] and "sentencia" in result.data["acuerdos"][-1]["sintesis"]


# --- Con Chromium real contra los portales locales ---------------------------------


def test_acciones_de_computer_use_operan_el_login_del_portal(chromium, portales):
    """Las acciones crudas (type/key) pasan el login del portal banca de verdad: la
    tabla de movimientos queda visible en el DOM y la captura es un PNG real."""
    from aiuda_core.cua.computer import LocalComputer

    async def go():
        async with LocalComputer(headless=True) as comp:
            await comp.goto(f"{portales}/banca.html")
            await comp.act("type", text="demo")  # autofocus en usuario
            await comp.act("key", text="Tab")
            await comp.act("type", text="aiuda123")
            await comp.act("key", text="Return")  # submit del formulario
            texto = await comp.page.inner_text("body")
            return texto, await comp.screenshot()

    texto, shot = asyncio.run(go())
    # el h2 se pinta en mayúsculas (text-transform): comparar sin distinguirlas
    assert "movimientos" in texto.lower() and "12,500.00" in texto  # la tabla quedó visible
    assert "contrasena" not in texto.lower()  # el login ya no está en pantalla
    assert shot[:8] == PNG_MAGIA


def test_plantilla_banca_corre_con_guion_y_deja_evidencia(chromium, portales, tmp_path):
    """La misión plantilla banca corre completa: login + tabla en Chromium headless,
    capturas por paso y datos coherentes con lo que el portal muestra."""
    mission = replace(
        PLANTILLAS["banca_movimientos"],
        url_inicio=url_portal_demo(portales, "banca_movimientos"),
        notas=notas_portal_demo("banca_movimientos"),
    )
    comp = _computer_con_memoria()
    runner = CuaRunner(
        client=AgenteGuion("banca_movimientos"), computer=comp, evidence_dir=str(tmp_path)
    )
    result = asyncio.run(runner.run(mission))
    assert result.success is True
    assert result.data == DATOS_PORTAL["banca_movimientos"]
    # el portal quedó operado DE VERDAD: pasó el login y la tabla es lo visible
    assert "movimientos" in comp.texto_final.lower() and "12,500.00" in comp.texto_final
    assert "contrasena" not in comp.texto_final.lower()
    assert len(result.evidence) >= 6  # captura inicial + una por acción del guion
    for ruta in result.evidence:
        with open(ruta, "rb") as f:
            assert f.read(8) == PNG_MAGIA  # evidencia real, no placeholders
    assert result.steps_log and "guion determinista" in result.steps_log[-1]  # honesto


def test_plantilla_sat_corre_con_guion(chromium, portales, tmp_path):
    mission = replace(
        PLANTILLAS["sat_cfdi_recibidos"],
        url_inicio=url_portal_demo(portales, "sat_cfdi_recibidos"),
        notas=notas_portal_demo("sat_cfdi_recibidos"),
    )
    comp = _computer_con_memoria()
    runner = CuaRunner(
        client=AgenteGuion("sat_cfdi_recibidos"), computer=comp, evidence_dir=str(tmp_path)
    )
    result = asyncio.run(runner.run(mission))
    assert result.success is True
    assert [c["folio"] for c in result.data["cfdis"]] == [
        "A1B2-4411", "C3D4-8032", "E5F6-1290", "G7H8-5567",
    ]
    # el login del portal de facturas pasó de verdad: la tabla de CFDI quedó visible
    assert "facturas recibidas" in comp.texto_final.lower() and "A1B2-4411" in comp.texto_final
    assert len(result.evidence) >= 6


def test_instruccion_del_dueno_cambia_lo_que_pasa_en_el_portal(
    chromium, portales, session, tenant, tmp_path
):
    """Ciclo COMPLETO del producto con navegador real: la instrucción del dueño
    (data._instruccion) viaja al prompt, el agente busca ESE expediente en el portal
    del tribunal, y el recado persiste datos + evidencia distintos según la instrucción."""
    from aiuda_core.cua.fallback import (
        CUA_PORTALES_KEY,
        ejecutar_recado,
        enqueue_cua_mission,
    )

    tenant.config = {
        **(tenant.config or {}),
        CUA_PORTALES_KEY: {"expedientes": f"{portales}/tribunal.html"},
    }
    session.flush()

    def correr(instruccion):
        comp = _computer_con_memoria()
        runner = CuaRunner(
            client=AgenteGuion("tribunal_acuerdos"), computer=comp,
            evidence_dir=str(tmp_path),
        )
        recado = enqueue_cua_mission(session, tenant, "expedientes", instruccion=instruccion)
        return ejecutar_recado(session, recado, runner=runner), comp.texto_final

    pedido, texto_77 = correr("Revisa el expediente 77/2025 y tráeme los acuerdos")
    default, texto_123 = correr(None)

    assert pedido.status == "done" and default.status == "done"
    # el portal REAL mostró el expediente que la instrucción pidió, no el default
    assert "77/2025" in texto_77 and "sentencia interlocutoria" in texto_77
    assert "123/2026" in texto_123 and "emplazar" in texto_123
    assert "sentencia interlocutoria" not in texto_123
    # lo extraído difiere según la instrucción y coincide con lo que el portal enseña
    assert pedido.data["acuerdos"] != default.data["acuerdos"]
    assert pedido.data["_instruccion"].startswith("Revisa el expediente 77/2025")
    # evidencia persistida en el recado (capturas base64 de PNG reales)
    import base64

    assert pedido.evidence
    assert base64.b64decode(pedido.evidence[-1])[:8] == PNG_MAGIA
    assert pedido.resumen and "guion determinista" in pedido.resumen  # honesto: sin IA
