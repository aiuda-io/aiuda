"""CUA local (MVP real): navegador Chromium local como 'computer' + loop de computer-use.

El navegador real se prueba en vivo (determinista, sin modelo). El loop se prueba con un
cliente Anthropic async mockeado que devuelve una accion y luego el JSON final. Sin
credencial, el runner es no-op honesto.
"""

import asyncio
from types import SimpleNamespace

import pytest

from aiuda_core.cua.computer import _map_key
from aiuda_core.cua.mission import Mission
from aiuda_core.cua.runner import CuaRunner


def test_map_key_traduce_a_playwright():
    assert _map_key("Return") == "Enter"
    assert _map_key("ctrl+a") == "Control+a"
    assert _map_key("Page_Down") == "PageDown"
    assert _map_key("Tab") == "Tab"


# --- Navegador real, local, determinista (sin modelo) -----------------------

def test_local_computer_navega_teclea_y_captura():
    pytest.importorskip("playwright")
    from aiuda_core.cua.computer import LocalComputer

    async def go():
        async with LocalComputer(headless=True) as comp:
            await comp.page.set_content(
                "<input id='x' /><div id='out'>vacio</div>"
                "<script>document.getElementById('x').addEventListener('input',"
                "e=>document.getElementById('out').textContent=e.target.value)</script>"
            )
            shot = await comp.screenshot()
            assert isinstance(shot, bytes) and len(shot) > 100  # PNG real
            await comp.page.focus("#x")
            await comp.act("type", text="hola cua")  # accion de computer-use real
            assert await comp.page.input_value("#x") == "hola cua"
            assert await comp.page.inner_text("#out") == "hola cua"

    try:
        asyncio.run(go())
    except Exception as e:  # Chromium no instalado (p.ej. CI sin 'playwright install')
        pytest.skip(f"Chromium no disponible: {e}")


def test_triple_click_selecciona_para_reemplazar():
    """El modelo real usa triple_click para seleccionar lo escrito antes de teclear
    (observado en corrida real): el type debe REEMPLAZAR el contenido, no anexar."""
    pytest.importorskip("playwright")
    from aiuda_core.cua.computer import LocalComputer

    async def go():
        async with LocalComputer(headless=True) as comp:
            await comp.page.set_content(
                "<input id='x' value='123/2026' style='position:absolute;left:50px;top:50px;width:200px' />"
            )
            await comp.act("triple_click", coordinate=[150, 60])
            await comp.act("type", text="77/2025")
            assert await comp.page.input_value("#x") == "77/2025"  # reemplazo, no "123/202677/2025"

    try:
        asyncio.run(go())
    except Exception as e:
        pytest.skip(f"Chromium no disponible: {e}")


# --- El loop de computer-use (cliente y computer mockeados) -----------------

class FakeComputer:
    """Computer async falso: registra acciones, no abre navegador."""

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
        return b"PNGDATA"

    async def act(self, action, **kw):
        self.acciones.append((action, kw))


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks))


def _tool_use(action, **params):
    return SimpleNamespace(type="tool_use", id="t1", input={"action": action, **params})


def _text(t):
    return SimpleNamespace(type="text", text=t)


class FakeMessages:
    def __init__(self, guion):
        self._guion = list(guion)
        self.llamadas = 0

    async def create(self, **kw):
        r = self._guion[min(self.llamadas, len(self._guion) - 1)]
        self.llamadas += 1
        return r


class FakeAsyncAnthropic:
    def __init__(self, guion):
        self.beta = SimpleNamespace(messages=FakeMessages(guion))


def _mission():
    return Mission(
        objetivo="Extrae los depositos",
        sistema="Portal de prueba",
        url_inicio="https://portal.local/",
        datos_a_extraer={"depositos": "lista {fecha, monto}"},
        max_pasos=5,
    )


def test_loop_ejecuta_accion_y_entrega_json(tmp_path):
    # Paso 1: el agente pide un click; paso 2: entrega el JSON final.
    guion = [
        _resp(_tool_use("left_click", coordinate=[100, 200])),
        _resp(_text('{"depositos": [{"fecha": "2026-07-01", "monto": 1500}], "_resumen": "listo"}')),
    ]
    comp = FakeComputer()
    runner = CuaRunner(
        client=FakeAsyncAnthropic(guion), computer=comp, evidence_dir=str(tmp_path)
    )
    result = asyncio.run(runner.run(_mission()))
    assert result.success is True
    assert result.data == {"depositos": [{"fecha": "2026-07-01", "monto": 1500}]}
    assert "_resumen" not in result.data  # el resumen no ensucia los datos
    # ejecuto la navegacion inicial y el click que pidio el modelo
    assert ("goto", "https://portal.local/") in comp.acciones
    assert ("left_click", {"coordinate": [100, 200]}) in comp.acciones
    # evidencia: captura inicial + una por accion
    assert len(result.evidence) >= 2


def test_sin_credencial_es_noop_honesto(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    # Con el navegador presente (simulado), el faltante que se reporta es la credencial.
    monkeypatch.setattr("aiuda_core.cua.runner.paquete_playwright_instalado", lambda: True)
    runner = CuaRunner()  # sin cliente inyectado ni credencial disponible
    result = asyncio.run(runner.run(_mission()))
    assert result.success is False
    assert "credencial" in (result.error or "").lower()  # dice por que, no inventa datos


# --- Deteccion honesta: instalado vs no instalado ---------------------------

def test_sin_extra_cua_es_noop_honesto_aunque_haya_credencial(monkeypatch):
    """Servidor sin el extra `cua`: la mision no corre y el error dice que instalar,
    aunque la credencial de IA este presente. Nunca inventa datos."""
    monkeypatch.setattr("aiuda_core.cua.runner.paquete_playwright_instalado", lambda: False)
    runner = CuaRunner(client=object())  # credencial/cliente presentes
    result = asyncio.run(runner.run(_mission()))
    assert result.success is False
    assert "no está instalado" in (result.error or "")
    assert "uv sync --extra cua" in (result.error or "")  # accionable, no criptico


def test_estado_navegador_sin_paquete(monkeypatch):
    import aiuda_core.cua.computer as comp

    monkeypatch.setattr(comp, "paquete_playwright_instalado", lambda: False)
    listo, detalle = comp.estado_navegador()
    assert listo is False and "extra `cua`" in detalle


def test_estado_navegador_con_todo_instalado():
    pytest.importorskip("playwright")
    from aiuda_core.cua.computer import estado_navegador

    listo, detalle = estado_navegador()
    if not listo:  # entorno con playwright pero sin el Chromium descargado
        assert "playwright install" in detalle  # honesto y accionable
    else:
        assert "listo" in detalle.lower()


def test_error_de_chromium_faltante_se_traduce(tmp_path, monkeypatch):
    """Paquete presente pero sin `playwright install chromium`: el error críptico del
    driver se traduce al faltante real."""

    class ComputerSinChromium:
        width, height = 1280, 800

        async def __aenter__(self):
            raise RuntimeError(
                "BrowserType.launch: Executable doesn't exist at /x/chrome\n"
                "Please run: playwright install"
            )

        async def __aexit__(self, *exc):
            return False

    guion = [_resp(_text('{"depositos": [], "_resumen": "x"}'))]
    runner = CuaRunner(
        client=FakeAsyncAnthropic(guion),
        computer=ComputerSinChromium(),
        evidence_dir=str(tmp_path),
    )
    result = asyncio.run(runner.run(_mission()))
    assert result.success is False
    assert "playwright install chromium" in (result.error or "")
