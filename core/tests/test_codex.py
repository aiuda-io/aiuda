"""CodexRunner: OpenAI por la Responses API estándar, con la API key del dueño. SSE mockeado.

El protocolo real (endpoint, gpt-5.x, stream obligatorio, formato de function_call) se
verificó en vivo; aquí se prueba la LÓGICA del runner: traducción de tools, acumulación de
texto por deltas, el loop de tools reenviando items, el registro de uso, el corte por tope
y los errores honestos.

Lo que YA NO se prueba porque ya no existe: el device flow, el refresh de tokens y el
backend de chatgpt.com. Esa vía mandaba `originator: codex_cli_rs` para hacerse pasar por
el CLI oficial y que el backend aceptara un token de suscripción personal.
"""

import json

import pytest

from aiuda_core.engine.codex import CodexError, CodexRunner, _to_openai_tool
from aiuda_core.engine.llm import BudgetExceeded

KEY = "sk-de-prueba"


def _sse(events: list[dict]) -> str:
    return "".join(f"data: {json.dumps(e)}\n" for e in events)


class _FakeResp:
    """Respuesta ya materializada (no-stream): el runner la consume por r.text."""

    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text
        self.content = text.encode()


def _post_seq(responses: list[_FakeResp], sink: list | None = None):
    it = iter(responses)

    def post(url, headers=None, json=None):  # noqa: A002
        if sink is not None:
            sink.append({"url": url, "headers": headers, "body": json})
        return next(it)

    return post


def _runner(responses, sink=None, **kw) -> CodexRunner:
    return CodexRunner(api_key=KEY, http_post=_post_seq(responses, sink), **kw)


# --- helpers puros ----------------------------------------------------------
def test_traduce_tool_anthropic_a_openai():
    tool = {
        "name": "cobrar",
        "description": "Cobra.",
        "input_schema": {"type": "object", "properties": {"x": {"type": "number"}}},
    }
    assert _to_openai_tool(tool) == {
        "type": "function",
        "name": "cobrar",
        "description": "Cobra.",
        "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
    }


# --- la vía: api.openai.com con Bearer --------------------------------------
def test_pega_a_la_api_estandar_con_la_llave_del_dueno():
    """Y NO al backend de chatgpt.com, ni mandando headers de un cliente ajeno."""
    visto: list = []
    r = _runner([_FakeResp(200, _sse([{"type": "response.output_text.delta", "delta": "ok"}]))], visto)
    r.complete(system="s", user="u", task="t")

    llamada = visto[0]
    assert llamada["url"] == "https://api.openai.com/v1/responses"
    assert llamada["headers"]["Authorization"] == f"Bearer {KEY}"
    assert "chatgpt-account-id" not in llamada["headers"]
    assert "originator" not in llamada["headers"]


def test_sin_llave_lo_dice_en_vez_de_intentar():
    r = CodexRunner(api_key="")
    assert r.mode == "api_key" and not r._has_session()
    with pytest.raises(CodexError, match="API key"):
        r.complete(system="s", user="u", task="t")


# --- protocolo --------------------------------------------------------------
def test_complete_acumula_texto_y_registra_uso():
    usos: list = []
    r = _runner(
        [
            _FakeResp(
                200,
                _sse(
                    [
                        {"type": "response.output_text.delta", "delta": "Hola "},
                        {"type": "response.output_text.delta", "delta": "Male"},
                        {
                            "type": "response.completed",
                            "response": {"usage": {"input_tokens": 7, "output_tokens": 3}},
                        },
                    ]
                ),
            )
        ],
        usage_callback=lambda m, t, i, o: usos.append((m, t, i, o)),
    )
    assert r.complete(system="s", user="u", task="redactar") == "Hola Male"
    assert usos and usos[0][1] == "redactar" and usos[0][2:] == (7, 3)


def test_respaldo_de_texto_desde_el_item_message_sin_deltas():
    r = _runner(
        [
            _FakeResp(
                200,
                _sse(
                    [
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "desde el item"}],
                            },
                        }
                    ]
                ),
            )
        ]
    )
    assert r.complete(system="s", user="u", task="t") == "desde el item"


def test_el_loop_ejecuta_la_tool_y_devuelve_la_respuesta_final():
    llamadas: list = []
    r = _runner(
        [
            _FakeResp(
                200,
                _sse(
                    [
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "function_call",
                                "name": "consultar_cartera",
                                "arguments": '{"telefono_cliente": "52155"}',
                                "call_id": "c1",
                            },
                        }
                    ]
                ),
            ),
            _FakeResp(200, _sse([{"type": "response.output_text.delta", "delta": "Debe 500."}])),
        ]
    )

    def ejecutar(nombre, args):
        llamadas.append((nombre, args))
        return "1 factura, $500"

    salida = r.run_tool_loop(
        system="s",
        user_message="cuánto debe",
        tools=[{"name": "consultar_cartera", "description": "", "input_schema": {}}],
        execute_tool=ejecutar,
    )
    assert salida == "Debe 500."
    assert llamadas == [("consultar_cartera", {"telefono_cliente": "52155"})]


def test_una_tool_que_truena_no_rompe_el_loop():
    r = _runner(
        [
            _FakeResp(
                200,
                _sse(
                    [
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "function_call",
                                "name": "x",
                                "arguments": "{}",
                                "call_id": "c1",
                            },
                        }
                    ]
                ),
            ),
            _FakeResp(200, _sse([{"type": "response.output_text.delta", "delta": "sigo aquí"}])),
        ]
    )

    def truena(nombre, args):
        raise RuntimeError("se cayó Odoo")

    assert (
        r.run_tool_loop(
            system="s",
            user_message="u",
            tools=[{"name": "x", "description": "", "input_schema": {}}],
            execute_tool=truena,
        )
        == "sigo aquí"
    )


# --- rejas y errores honestos -----------------------------------------------
def test_el_tope_de_gasto_corta_antes_de_llamar():
    def sin_cupo():
        raise BudgetExceeded("Se acabó el presupuesto de IA del mes.")

    r = _runner([_FakeResp(200, "")], budget_check=sin_cupo)
    with pytest.raises(BudgetExceeded):
        r.complete(system="s", user="u", task="t")


def test_un_401_dice_que_revises_tu_llave():
    r = _runner([_FakeResp(401, "no autorizado")])
    with pytest.raises(CodexError, match="401"):
        r.complete(system="s", user="u", task="t")


def test_otro_error_del_backend_se_reporta_con_su_codigo():
    r = _runner([_FakeResp(500, "boom")])
    with pytest.raises(CodexError, match="500"):
        r.complete(system="s", user="u", task="t")


def test_test_codex_sin_llave_reporta_not_configured():
    from aiuda_core.engine.codex import test_codex

    v = test_codex(CodexRunner(api_key=""))
    assert v["ok"] is False and v["code"] == "not_configured" and v["mode"] == "api_key"
