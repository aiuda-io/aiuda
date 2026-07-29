"""CompatRunner: IA local (Ollama/OpenAI-compatible) con el contrato ProviderRunner.

Sin red: el cliente httpx se inyecta con un stub que devuelve respuestas del
formato /v1/chat/completions.
"""

import json

import pytest

from aiuda_core.engine.llm import BudgetExceeded
from aiuda_core.engine import openai_compat
from aiuda_core.engine.openai_compat import CompatRunner, parse_local_secret
from aiuda_core.engine.provider import ProviderCredential
from aiuda_core.engine.runner import ProviderRunner, make_runner


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)


class _StubClient:
    """Devuelve respuestas en orden y guarda cada payload enviado."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def post(self, url, json=None, headers=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def _msg(content=None, tool_calls=None, usage=None):
    return _Resp(
        {
            "choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
        }
    )


def test_parse_local_secret_defaults():
    cfg = parse_local_secret("")
    assert cfg["base_url"] == "http://localhost:11434/v1"
    assert cfg["model"] == "" and cfg["api_key"] == ""
    cfg = parse_local_secret(json.dumps({"base_url": "http://x:8000/v1/", "model": "m"}))
    assert cfg["base_url"] == "http://x:8000/v1" and cfg["model"] == "m"


def test_make_runner_local_cumple_protocolo():
    cred = ProviderCredential(
        name="local", mode="api_key", secret=json.dumps({"model": "llama3.1"})
    )
    runner = make_runner(cred)
    assert isinstance(runner, ProviderRunner)
    assert runner.model_for("triage") == "llama3.1"
    assert runner.model_for("redaccion") == "llama3.1"


def test_complete_y_metering():
    eventos = []
    client = _StubClient([_msg(content="hola dueño")])
    runner = CompatRunner(
        model="m", client=client,
        usage_callback=lambda model, task, i, o: eventos.append((model, task, i, o)),
    )
    out = runner.complete(system="s", user="u", task="prueba")
    assert out == "hola dueño"
    assert eventos == [("m", "prueba", 10, 5)]
    sent = client.requests[0]["json"]
    assert sent["model"] == "m"
    assert sent["messages"][0] == {"role": "system", "content": "s"}


def test_classify_cae_a_ultima_etiqueta():
    runner = CompatRunner(model="m", client=_StubClient([_msg(content="banana")]))
    assert runner.classify("s", "u", labels=["a", "b"], task="t") == "b"
    runner = CompatRunner(model="m", client=_StubClient([_msg(content=" A ")]))
    assert runner.classify("s", "u", labels=["a", "b"], task="t") == "a"


def test_tool_loop_traduce_y_ejecuta():
    calls = [
        _msg(tool_calls=[{
            "id": "c1", "type": "function",
            "function": {"name": "sumar", "arguments": json.dumps({"a": 2, "b": 3})},
        }]),
        _msg(content="El total es 5"),
    ]
    client = _StubClient(calls)
    runner = CompatRunner(model="m", client=client)
    ejecutadas = []

    def execute(name, args):
        ejecutadas.append((name, args))
        return "5"

    out = runner.run_tool_loop(
        system="s", user_message="suma 2+3",
        tools=[{"name": "sumar", "description": "suma", "input_schema": {"type": "object"}}],
        execute_tool=execute,
    )
    assert out == "El total es 5"
    assert ejecutadas == [("sumar", {"a": 2, "b": 3})]
    # El tool viajó en formato OpenAI y el resultado regresó como role=tool.
    first = client.requests[0]["json"]
    assert first["tools"][0]["type"] == "function"
    assert first["tools"][0]["function"]["name"] == "sumar"
    second = client.requests[1]["json"]
    assert second["messages"][-1]["role"] == "tool"
    assert second["messages"][-1]["content"] == "5"


def test_budget_check_corta_antes_de_llamar():
    client = _StubClient([_msg(content="nunca")])
    runner = CompatRunner(model="m", client=client)

    def _corta():
        raise BudgetExceeded("tope")

    runner.budget_check = _corta
    with pytest.raises(BudgetExceeded):
        runner.complete(system="s", user="u", task="t")
    assert client.requests == []


def test_test_local_sin_modelo_es_config():
    verdict = openai_compat.test_local(json.dumps({"base_url": "http://x"}))
    assert verdict["ok"] is False and verdict["code"] == "config"


def test_test_local_ok():
    verdict = openai_compat.test_local(
        json.dumps({"model": "m"}), client=_StubClient([_msg(content="pong")])
    )
    assert verdict["ok"] is True and verdict["model"] == "m"
