"""Capa de proveedor agnóstica: factory make_runner + selección de modelo por rol."""

import json

import pytest
from conftest import FakeResponse

from aiuda_core.config import settings
from aiuda_core.connectors.smart_import import classify_sheet
from aiuda_core.engine.llm import BudgetExceeded, ClaudeRunner
from aiuda_core.engine.provider import CLAUDE_CODE_IDENTITY, ProviderCredential
from aiuda_core.engine.runner import ProviderRunner, ProviderUnavailable, make_runner


def test_make_runner_claude_devuelve_claude_runner():
    cred = ProviderCredential("claude", "api_key", "sk-x")
    assert isinstance(make_runner(cred), ClaudeRunner)


def test_make_runner_sin_credencial_con_env(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    assert isinstance(make_runner(None), ClaudeRunner)


def test_make_runner_sin_credencial_ni_env_sigue_siendo_claude(monkeypatch):
    # Sin panel ni env: igual devuelve un ClaudeRunner (key vacía); el guard del endpoint
    # decide si hay con qué responder. No revienta aquí.
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert isinstance(make_runner(None), ClaudeRunner)


def test_make_runner_codex_da_codex_runner():
    from aiuda_core.engine.codex import CodexRunner

    cred = ProviderCredential("codex", "subscription", "acct-1")
    assert isinstance(make_runner(cred), CodexRunner)


def test_make_runner_proveedor_desconocido_no_disponible():
    cred = ProviderCredential("otro", "api_key", "x")
    with pytest.raises(ProviderUnavailable):
        make_runner(cred)


def test_claude_runner_cumple_protocolo(fake_client_factory):
    runner = ClaudeRunner(client=fake_client_factory())
    assert isinstance(runner, ProviderRunner)


def test_model_for_mapea_roles(fake_client_factory):
    runner = ClaudeRunner(client=fake_client_factory())
    assert runner.model_for("triage") == settings.model_triage
    assert runner.model_for("redaccion") == settings.model_redaccion
    with pytest.raises(ValueError):
        runner.model_for("inventado")


def test_role_default_resuelve_redaccion(fake_client_factory):
    client = fake_client_factory(FakeResponse("ok"))
    ClaudeRunner(client=client).complete(system="s", user="u", task="t")
    assert client.messages.requests[0]["model"] == settings.model_redaccion


def test_role_triage_en_complete(fake_client_factory):
    client = fake_client_factory(FakeResponse("ok"))
    ClaudeRunner(client=client).complete(system="s", user="u", role="triage", task="t")
    assert client.messages.requests[0]["model"] == settings.model_triage


def test_run_tool_loop_usa_redaccion_por_defecto(fake_client_factory):
    client = fake_client_factory(FakeResponse("listo"))  # end_turn → vuelve en la 1ra
    ClaudeRunner(client=client).run_tool_loop(
        system="s", user_message="u", tools=[], execute_tool=lambda n, i: ""
    )
    assert client.messages.requests[0]["model"] == settings.model_redaccion


def test_importacion_con_credencial_suscripcion_antepone_identidad(fake_client_factory):
    # El runner de suscripción threaded a la importación antepone la identidad de Claude Code.
    client = fake_client_factory(FakeResponse(json.dumps({"tipo": "clientes", "confianza": 0.9})))
    runner = ClaudeRunner(
        client=client, credential=ProviderCredential("claude", "subscription", "oauth-x")
    )
    classify_sheet(["Nombre"], [{"Nombre": "Ana"}], runner)
    assert client.messages.requests[0]["system"].startswith(CLAUDE_CODE_IDENTITY)


# --------------------------------------------------------------------------- #
# Tope de gasto: el hook corta ANTES de llamar al proveedor                     #
# --------------------------------------------------------------------------- #
def test_budget_check_corta_antes_de_llamar(fake_client_factory):
    client = fake_client_factory(FakeResponse("nunca debería salir"))

    def agotado():
        raise BudgetExceeded("tope del mes agotado")

    runner = ClaudeRunner(client=client, budget_check=agotado)
    with pytest.raises(BudgetExceeded):
        runner.complete(system="s", user="u", task="t")
    assert client.messages.requests == []  # ni una llamada al proveedor


def test_budget_check_asignable_despues_de_construir(fake_client_factory):
    # La capa cloud engancha el tope después de make_runner (mismo patrón que el
    # usage_callback del engine). Sin hook, el runner llama normal.
    client = fake_client_factory(FakeResponse("ok"))
    runner = ClaudeRunner(client=client)
    runner.complete(system="s", user="u", task="t")
    assert len(client.messages.requests) == 1

    def agotado():
        raise BudgetExceeded("tope")

    runner.budget_check = agotado
    with pytest.raises(BudgetExceeded):
        runner.complete(system="s", user="u", task="t")
    assert len(client.messages.requests) == 1  # la segunda nunca salió


def test_budget_check_corta_a_media_iteracion_del_loop(fake_client_factory):
    # Si el tope se agota entre iteraciones del tool loop, la siguiente llamada no sale.
    class ToolUse:
        type = "tool_use"
        id = "tu_1"
        name = "consultar"
        input: dict = {}

    primera = FakeResponse("", stop_reason="tool_use", content=[ToolUse()])
    client = fake_client_factory(primera, FakeResponse("fin"))
    llamadas = {"n": 0}

    def presupuesto():
        llamadas["n"] += 1
        if llamadas["n"] > 1:  # la primera pasa; la segunda ya no
            raise BudgetExceeded("tope a media corrida")

    runner = ClaudeRunner(client=client, budget_check=presupuesto)
    with pytest.raises(BudgetExceeded):
        runner.run_tool_loop(
            system="s", user_message="u",
            tools=[{"name": "consultar"}], execute_tool=lambda n, i: "dato",
        )
    assert len(client.messages.requests) == 1
