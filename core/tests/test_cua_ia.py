"""El CUA con la IA del dueño por la vía de todo lo demás (resolve_credential +
make_runner), y el corte honesto cuando esa IA no puede operar portales.

Aquí NO se parcha `_runner_para_tenant`: se ejercita tal cual. Lo único falso es lo
que sale de la máquina: el cliente de Anthropic (un guion) y el navegador.
"""

import asyncio
from types import SimpleNamespace

import pytest

from aiuda_core.connectors.credentials import set_credential
from aiuda_core.cua import fallback
from aiuda_core.cua.runner import _COMPUTER_BETA, ClienteDelMotor, CuaRunner
from aiuda_core.engine.llm import BudgetExceeded, ClaudeRunner


class NavegadorFalso:
    """LocalComputer falso: recuerda con qué sesión lo abrieron y qué le pidieron."""

    abiertos: list["NavegadorFalso"] = []
    width, height = 1280, 800

    def __init__(self, headless=True, storage_state=None):
        self.storage_state = storage_state
        self.acciones = []
        NavegadorFalso.abiertos.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def goto(self, url):
        self.acciones.append(("goto", url))

    async def screenshot(self):
        return b"PNG"

    async def act(self, action, **kw):
        self.acciones.append((action, kw))


class _Uso:
    input_tokens = 900
    output_tokens = 40


def _resp(*bloques):
    return SimpleNamespace(content=list(bloques), usage=_Uso())


class AnthropicFalso:
    """Cliente SÍNCRONO de Anthropic con solo lo que usa el CUA: beta.messages.create.
    Sigue un guion: un clic y luego el JSON final."""

    def __init__(self):
        self.pedidos = []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.pedidos.append(kw)
        if len(self.pedidos) == 1:
            return _resp(
                SimpleNamespace(
                    type="tool_use", id="t1",
                    input={"action": "left_click", "coordinate": [10, 20]},
                )
            )
        return _resp(
            SimpleNamespace(type="text", text='{"resultado": "3 pedidos", "_resumen": "listo"}')
        )


@pytest.fixture()
def navegador(monkeypatch):
    NavegadorFalso.abiertos = []
    monkeypatch.setattr("aiuda_core.cua.runner.LocalComputer", NavegadorFalso)
    monkeypatch.setattr("aiuda_core.cua.runner.paquete_playwright_instalado", lambda: True)
    return NavegadorFalso


@pytest.fixture()
def con_portal(session, tenant):
    tenant.config = {
        **(tenant.config or {}),
        fallback.CUA_PORTALES_URL_KEY: [
            {"id": "x", "nombre": "Proveedor", "url": "https://prov.example/"}
        ],
    }
    session.flush()
    return tenant


def _conectar(session, tenant, name, mode="api_key", secret="sk-ant-prueba"):
    """La IA como la guarda el panel: cifrada, en el almacén de credenciales."""
    valores = {"name": name, "mode": mode}
    if mode != "cli":
        valores["secret"] = secret
    set_credential(session, tenant.id, "ia", valores)
    session.flush()


def test_con_llave_de_anthropic_corre_por_el_runner_del_motor(
    session, con_portal, navegador, monkeypatch
):
    """El camino real: credencial guardada -> make_runner -> ClaudeRunner.computer_use,
    con el tope consultado antes de cada paso y cada paso registrado como uso."""
    tenant = con_portal
    _conectar(session, tenant, "claude")
    estado = {"cookies": [{"name": "sid", "value": "abc"}]}
    fallback.guardar_sesion(session, tenant, "portal:x", estado)
    session.flush()

    falso = AnthropicFalso()
    usos, topes = [], []
    llaves = []

    def construir(cred):
        llaves.append((cred.name, cred.mode, cred.secret))
        return falso

    monkeypatch.setattr("aiuda_core.engine.llm.build_anthropic_client", construir)

    def ia():
        from aiuda_core.engine.provider import resolve_credential
        from aiuda_core.engine.runner import make_runner

        motor = make_runner(
            resolve_credential(session=session, tenant_id=tenant.id),
            usage_callback=lambda *a: usos.append(a),
        )
        motor.budget_check = lambda: topes.append(1)
        return motor

    recado = fallback.enqueue_cua_mission(session, tenant, "portal:x")
    fallback.ejecutar_recado(session, recado, ia=ia)

    assert recado.status == "done", recado.error
    assert recado.data == {"resultado": "3 pedidos"}
    # la llave del dueño, tal cual, sin token de sesión ni identidad de otro cliente
    assert llaves == [("claude", "api_key", "sk-ant-prueba")]
    assert len(falso.pedidos) == 2
    for pedido in falso.pedidos:
        assert pedido["betas"] == [_COMPUTER_BETA]  # solo computer-use, ninguna beta de OAuth
        assert "system" not in pedido
        assert pedido["tools"][0]["name"] == "computer"
    # el tope se consultó antes de CADA paso y cada paso quedó registrado
    assert len(topes) == 2
    assert [(u[1], u[2], u[3]) for u in usos] == [("cua", 900, 40)] * 2
    # la sesión del handoff llegó al navegador y el clic del modelo se ejecutó
    nav = navegador.abiertos[0]
    assert nav.storage_state == estado
    assert ("left_click", {"coordinate": [10, 20]}) in nav.acciones


def test_sin_fabrica_de_ia_tambien_corre(session, con_portal, navegador, monkeypatch):
    """Sin capa de servidor (sin `ia`), se arma con make_runner a secas."""
    _conectar(session, con_portal, "claude")
    falso = AnthropicFalso()
    monkeypatch.setattr("aiuda_core.engine.llm.build_anthropic_client", lambda cred: falso)
    recado = fallback.enqueue_cua_mission(session, con_portal, "portal:x")
    fallback.ejecutar_recado(session, recado)
    assert recado.status == "done", recado.error
    assert len(falso.pedidos) == 2


@pytest.mark.parametrize(
    ("name", "mode", "dice"),
    [
        ("codex", "api_key", "llave de OpenAI"),
        ("claude_cli", "cli", "Claude Code instalado"),
        ("codex_cli", "cli", "Codex instalado"),
        ("local", "api_key", "modelo local"),
        ("chatgpt", "oauth", "plan de ChatGPT"),
    ],
)
def test_una_ia_que_no_ve_la_pantalla_corta_honesto(
    session, con_portal, navegador, name, mode, dice
):
    """OpenAI, los CLIs y el modelo local no reciben capturas: el recado lo dice en
    palabras del dueño, sin abrir navegador y sin llamar a ninguna IA."""
    tenant = con_portal
    _conectar(session, tenant, name, mode, secret='{"base_url": "http://x", "model": "m"}')
    llamadas = []

    def ia():
        llamadas.append(1)
        raise AssertionError("no debe armarse el runner de IA")

    recado = fallback.enqueue_cua_mission(session, tenant, "portal:x")
    fallback.ejecutar_recado(session, recado, ia=ia)

    assert recado.status == "failed"
    assert dice in recado.error
    assert "llave de Anthropic" in recado.error
    assert "Traceback" not in recado.error and "Error" not in recado.error
    assert llamadas == [] and navegador.abiertos == []
    assert fallback.ia_para_cua(session, tenant) == (False, recado.error)


def test_sin_ia_conectada_corta_honesto(session, con_portal, navegador, monkeypatch):
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    recado = fallback.enqueue_cua_mission(session, con_portal, "portal:x")
    fallback.ejecutar_recado(session, recado)
    assert recado.status == "failed"
    assert "llave de Anthropic" in recado.error
    assert navegador.abiertos == []


def test_tope_agotado_a_media_mision_termina_con_el_motivo(
    session, con_portal, navegador, monkeypatch
):
    """El tope corta ANTES del segundo paso: la misión termina con el mensaje del
    tope y el proveedor recibió una sola llamada."""
    _conectar(session, con_portal, "claude")
    falso = AnthropicFalso()
    monkeypatch.setattr("aiuda_core.engine.llm.build_anthropic_client", lambda cred: falso)

    def ia():
        motor = ClaudeRunner(client=falso)
        pasos = []

        def tope():
            pasos.append(1)
            if len(pasos) > 1:
                raise BudgetExceeded("Llegaste al tope de IA de este mes.")

        motor.budget_check = tope
        return motor

    recado = fallback.enqueue_cua_mission(session, con_portal, "portal:x")
    fallback.ejecutar_recado(session, recado, ia=ia)
    assert recado.status == "failed"
    assert recado.error == "Llegaste al tope de IA de este mes."
    assert len(falso.pedidos) == 1


def test_un_runner_sin_computer_use_no_llega_al_loop(session, con_portal, navegador):
    """Red de seguridad: si la fábrica entrega un runner que no trae computer-use
    (uno envuelto, uno nuevo), se corta con mensaje y no con AttributeError."""
    _conectar(session, con_portal, "claude")
    recado = fallback.enqueue_cua_mission(session, con_portal, "portal:x")
    fallback.ejecutar_recado(session, recado, ia=lambda: object())
    assert recado.status == "failed"
    assert "llave de Anthropic" in recado.error
    assert navegador.abiertos == []


def test_cliente_del_motor_tiene_la_forma_que_espera_el_loop():
    """`client.beta.messages.create(...)` asíncrono, que cae en `motor.computer_use`."""
    visto = {}

    class Motor:
        def computer_use(self, *, task, **kw):
            visto.update(task=task, **kw)
            return "respuesta"

    cliente = ClienteDelMotor(Motor())
    assert asyncio.run(cliente.beta.messages.create(model="m")) == "respuesta"
    assert visto == {"task": "cua", "model": "m"}


def test_el_runner_ya_no_acepta_identidad_de_otro_cliente():
    """Resto del modo suscripción: el parámetro `system` servía para declararse como
    el cliente oficial del proveedor. Ya no existe."""
    with pytest.raises(TypeError):
        CuaRunner(system="cualquier cosa")


def test_llave_rechazada_se_dice_en_espanol(session, con_portal, navegador, monkeypatch):
    """Visto en la verificación en vivo: con una llave inválida el recado mostraba el
    error crudo del SDK. Ahora dice qué pasó y dónde arreglarlo."""
    import anthropic
    import httpx

    _conectar(session, con_portal, "claude")

    class Rechaza:
        def __init__(self):
            self.beta = SimpleNamespace(messages=self)

        def create(self, **kw):
            pedido = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.AuthenticationError(
                "Error code: 401", response=httpx.Response(401, request=pedido), body=None
            )

    monkeypatch.setattr("aiuda_core.engine.llm.build_anthropic_client", lambda cred: Rechaza())
    recado = fallback.enqueue_cua_mission(session, con_portal, "portal:x")
    fallback.ejecutar_recado(session, recado)
    assert recado.status == "failed"
    assert "no aceptó tu llave" in recado.error and "Tu IA" in recado.error
    assert "Error code" not in recado.error
