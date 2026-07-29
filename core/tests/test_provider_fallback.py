"""Fallback de IA: la vía suscripción cede a la API key cuando el token se rechaza o
el plan agota su ráfaga. La conmutación es por llamada (no re-ejecuta el loop) y permanente
para la instancia."""

import httpx
import pytest
from conftest import FakeResponse

from aiuda_core.config import settings
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.engine.provider import CLAUDE_CODE_IDENTITY, ProviderCredential
from aiuda_core.engine.runner import make_runner

_URL = "https://api.anthropic.com/v1/messages"


def _rate_limit():
    import anthropic

    resp = httpx.Response(429, request=httpx.Request("POST", _URL))
    return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _auth_error():
    import anthropic

    resp = httpx.Response(401, request=httpx.Request("POST", _URL))
    return anthropic.AuthenticationError("bad token", response=resp, body=None)


def _conn_error():
    import anthropic

    return anthropic.APIConnectionError(request=httpx.Request("POST", _URL))


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "t1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class _SeqClient:
    """Cliente fake: cada item de la secuencia se lanza (si es Exception) o se devuelve.

    `.messages.create` apunta al propio objeto para imitar el shape del SDK."""

    def __init__(self, *items):
        self._items = list(items)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---- cableado en make_runner ------------------------------------------------


def test_make_runner_suscripcion_arma_fallback(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    runner = make_runner(ProviderCredential("claude", "subscription", "oauth-z"))
    assert runner._fallback_client is not None


def test_make_runner_api_key_no_arma_fallback(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    runner = make_runner(ProviderCredential("claude", "api_key", "sk-panel"))
    assert runner._fallback_client is None


def test_make_runner_suscripcion_sin_env_no_arma_fallback(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    runner = make_runner(ProviderCredential("claude", "subscription", "oauth-z"))
    assert runner._fallback_client is None


# ---- modelo de redacción según la credencial --------------------------------


def test_redaccion_usa_haiku_por_suscripcion(monkeypatch):
    # La suscripción topa 429 con sonnet: su redacción cae a haiku. La api_key conserva sonnet.
    monkeypatch.setattr(settings, "model_redaccion", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "model_redaccion_suscripcion", "claude-haiku-4-5")
    sub = ClaudeRunner(client=_SeqClient(), credential=ProviderCredential("claude", "subscription", "z"))
    api = ClaudeRunner(client=_SeqClient(), credential=ProviderCredential("claude", "api_key", "sk-x"))
    assert sub.model_for("redaccion") == "claude-haiku-4-5"
    assert api.model_for("redaccion") == "claude-sonnet-4-6"
    assert sub.model_for("triage") == api.model_for("triage") == settings.model_triage


# ---- comportamiento del fallback --------------------------------------------


def test_cae_a_api_key_en_429():
    primary = _SeqClient(_rate_limit())
    fallback = _SeqClient(FakeResponse("desde api key"))
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
        rate_backoff=(),  # sin reintentos: cede al primer 429
    )
    out = runner.complete(system="s", user="u", model="m", task="t")
    assert out == "desde api key"
    assert runner.fell_back is True
    assert len(primary.requests) == 1  # se intentó una vez
    assert len(fallback.requests) == 1  # y se reintentó en el respaldo


def test_suscripcion_cede_tras_backoff():
    # 429 en los dos primeros intentos, éxito al tercero: la suscripción se recupera sola con
    # el backoff y NO gasta la API key (fell_back queda False). Esperas de 0s = instantáneo.
    primary = _SeqClient(_rate_limit(), _rate_limit(), FakeResponse("desde suscripción"))
    fallback = _SeqClient(FakeResponse("no debería usarse"))
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
        rate_backoff=(0, 0),
    )
    assert runner.complete(system="s", user="u", model="m", task="t") == "desde suscripción"
    assert runner.fell_back is False
    assert len(primary.requests) == 3  # intento inicial + 2 reintentos
    assert len(fallback.requests) == 0  # nunca tocó la API key


def test_backoff_agotado_cae_a_api_key():
    # 429 en todos los intentos de la suscripción (inicial + 2 reintentos): agotado el backoff,
    # recién ahí cede a la API key.
    primary = _SeqClient(_rate_limit(), _rate_limit(), _rate_limit())
    fallback = _SeqClient(FakeResponse("desde api key"))
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
        rate_backoff=(0, 0),
    )
    assert runner.complete(system="s", user="u", model="m", task="t") == "desde api key"
    assert runner.fell_back is True
    assert len(primary.requests) == 3
    assert len(fallback.requests) == 1


def test_cae_a_api_key_en_token_rechazado():
    primary = _SeqClient(_auth_error())
    fallback = _SeqClient(FakeResponse("ok"))
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
    )
    assert runner.complete(system="s", user="u", model="m", task="t") == "ok"
    assert runner.fell_back is True


def test_no_cae_en_error_transitorio():
    # Un error de conexión NO quema la API key: es transitorio, no "credencial inválida".
    primary = _SeqClient(_conn_error())
    fallback = _SeqClient(FakeResponse("no debería usarse"))
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
    )
    import anthropic

    with pytest.raises(anthropic.APIConnectionError):
        runner.complete(system="s", user="u", model="m", task="t")
    assert runner.fell_back is False
    assert len(fallback.requests) == 0


def test_sin_fallback_propaga_el_error():
    primary = _SeqClient(_rate_limit())
    runner = ClaudeRunner(
        client=primary,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
        rate_backoff=(),
    )
    import anthropic

    with pytest.raises(anthropic.RateLimitError):
        runner.complete(system="s", user="u", model="m", task="t")
    assert runner.fell_back is False


def test_fallback_es_permanente_y_suelta_el_prefijo_en_el_loop():
    # Iteración 1: la suscripción da 429 → se conmuta y se reintenta en el respaldo (tool_use).
    # Iteración 2: ya está en el respaldo (end_turn). El preámbulo de identidad se suelta al
    # conmutar, así que la 2da llamada del respaldo va sin él.
    primary = _SeqClient(_rate_limit())
    fallback = _SeqClient(
        FakeResponse("", stop_reason="tool_use", content=[_ToolUseBlock("t", {})]),
        FakeResponse("listo"),
    )
    runner = ClaudeRunner(
        client=primary,
        fallback_client=fallback,
        credential=ProviderCredential("claude", "subscription", "oauth-z"),
        rate_backoff=(),
    )
    out = runner.run_tool_loop(
        system="Eres el asistente.",
        user_message="u",
        tools=[],
        execute_tool=lambda n, i: "resultado",
    )
    assert out == "listo"
    assert runner.fell_back is True
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 2
    # El reintento (llamada 1 del respaldo) conserva el system ya armado (con identidad,
    # inofensivo para api_key); la llamada 2, tras soltar el prefijo, va sin identidad.
    assert not fallback.requests[1]["system"].startswith(CLAUDE_CODE_IDENTITY)
    assert fallback.requests[1]["system"] == "Eres el asistente."
