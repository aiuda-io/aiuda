"""Handoff de login: la máquina de estados y la reutilización de la sesión.

Sin abrir un Chromium de verdad (el opener es inyectable) probamos el ciclo completo:
abrir → esperar → confirmar/cancelar/timeout → guardar cifrado. Y que la sesión guardada
se descifra y llega al runner para que el asistente arranque logueado.
"""

import asyncio

import pytest

from aiuda_core.cua import fallback, handoff
from aiuda_core.cua.mission import MissionResult


class FakeComputer:
    """Navegador falso: recuerda a dónde fue y entrega una sesión canned al capturar."""

    def __init__(self, state):
        self._state = state
        self.goto_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def goto(self, url):
        self.goto_url = url

    async def capturar_storage_state(self):
        return self._state


def _opener(state):
    def abrir():
        return FakeComputer(state)

    return abrir


@pytest.fixture(autouse=True)
def _limpiar_sesiones():
    handoff._SESIONES.clear()
    yield
    handoff._SESIONES.clear()


async def _hasta(cond, intentos=200):
    for _ in range(intentos):
        if cond():
            return True
        await asyncio.sleep(0.005)
    return False


def test_handoff_confirma_captura_y_guarda(monkeypatch):
    """El dueño entra y confirma: se captura su sesión y se persiste (cifrada)."""
    guardadas = []
    monkeypatch.setattr(
        handoff, "_persistir_sesion", lambda tid, cap, st: guardadas.append((tid, cap, st))
    )
    state = {"cookies": [{"name": "sid", "value": "abc"}]}

    async def run():
        s = handoff.iniciar_handoff(
            "t1", "portal:x", "Portal X", "https://x.example", abrir=_opener(state)
        )
        assert await _hasta(lambda: s.estado == "esperando")
        handoff.confirmar_handoff(s)
        await s._task
        return s

    s = asyncio.run(run())
    assert s.estado == "guardado"
    assert guardadas == [("t1", "portal:x", state)]


def test_handoff_cancela_no_guarda(monkeypatch):
    llamado = []
    monkeypatch.setattr(handoff, "_persistir_sesion", lambda *a: llamado.append(a))

    async def run():
        s = handoff.iniciar_handoff(
            "t1", "cfdi", "SAT", "https://sat.example", abrir=_opener({})
        )
        assert await _hasta(lambda: s.estado == "esperando")
        handoff.cancelar_handoff(s)
        await s._task
        return s

    s = asyncio.run(run())
    assert s.estado == "cancelado" and not llamado


def test_handoff_timeout_cierra(monkeypatch):
    monkeypatch.setattr(handoff, "_persistir_sesion", lambda *a: None)
    monkeypatch.setattr(handoff, "TIMEOUT_LOGIN_S", 0.02)

    async def run():
        s = handoff.iniciar_handoff(
            "t1", "cfdi", "SAT", "https://sat.example", abrir=_opener({})
        )
        await s._task
        return s

    s = asyncio.run(run())
    assert s.estado == "expirado"


def test_handoff_reusa_sesion_activa(monkeypatch):
    """Pedir el handoff dos veces del mismo portal no abre dos ventanas: reusa la viva."""
    monkeypatch.setattr(handoff, "_persistir_sesion", lambda *a: None)

    async def run():
        a = handoff.iniciar_handoff("t1", "cfdi", "SAT", "https://sat", abrir=_opener({}))
        assert await _hasta(lambda: a.estado == "esperando")
        b = handoff.iniciar_handoff("t1", "cfdi", "SAT", "https://sat", abrir=_opener({}))
        assert a.id == b.id
        handoff.cancelar_handoff(a)
        await a._task

    asyncio.run(run())


def test_obtener_aisla_por_tenant(monkeypatch):
    monkeypatch.setattr(handoff, "_persistir_sesion", lambda *a: None)

    async def run():
        s = handoff.iniciar_handoff("t1", "cfdi", "SAT", "https://sat", abrir=_opener({}))
        assert await _hasta(lambda: s.estado == "esperando")
        assert handoff.obtener(s.id, "t1") is s
        assert handoff.obtener(s.id, "OTRO") is None  # otro tenant no la ve
        handoff.cancelar_handoff(s)
        await s._task

    asyncio.run(run())


# ---------- La sesión guardada se reusa en el recado ----------


def test_sesion_cifrada_round_trip(session, tenant):
    state = {"cookies": [{"name": "sid", "value": "xyz"}], "origins": []}
    fallback.guardar_sesion(session, tenant, "portal:x", state)
    session.flush()
    assert fallback.tiene_sesion(tenant, "portal:x")
    assert fallback.sesion_guardada_en(tenant, "portal:x")
    assert fallback.sesion_de_capacidad(tenant, "portal:x") == state
    # borrarla la olvida
    assert fallback.borrar_sesion(session, tenant, "portal:x") is True
    assert fallback.sesion_de_capacidad(tenant, "portal:x") is None


def test_recado_reusa_la_sesion_guardada(session, tenant, monkeypatch):
    """ejecutar_recado carga la sesión guardada del portal y se la pasa al runner, para
    que el asistente arranque ya logueado."""
    tenant.config = {
        **(tenant.config or {}),
        fallback.CUA_PORTALES_URL_KEY: [
            {"id": "x", "nombre": "Proveedor", "url": "https://prov.example/"}
        ],
    }
    session.flush()
    state = {"cookies": [{"name": "sid", "value": "abc"}]}
    fallback.guardar_sesion(session, tenant, "portal:x", state)
    session.flush()

    recibido = {}

    class FakeRunner:
        async def run(self, mission):
            return MissionResult(success=True, data={"resultado": "ok"}, evidence=[])

    def fake_runner_para_tenant(sess, ten, storage_state=None):
        recibido["storage_state"] = storage_state
        return FakeRunner()

    monkeypatch.setattr(fallback, "_runner_para_tenant", fake_runner_para_tenant)
    recado = fallback.enqueue_cua_mission(session, tenant, "portal:x")
    fallback.ejecutar_recado(session, recado)
    assert recado.status == "done"
    assert recibido["storage_state"] == state


def test_runner_pasa_storage_state_al_computer():
    from aiuda_core.cua.runner import CuaRunner

    r = CuaRunner(storage_state={"cookies": []})
    comp = r._computer_cm()
    assert comp.storage_state == {"cookies": []}
