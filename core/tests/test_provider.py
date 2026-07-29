"""Resolución de credencial del proveedor y construcción del cliente Anthropic."""

from conftest import FakeResponse

from aiuda_core.config import settings
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.engine.provider import (
    CLAUDE_CODE_IDENTITY,
    OAUTH_BETA,
    ProviderCredential,
    build_anthropic_client,
    credential_from_config,
    default_credential,
    oauth_system_prefix,
    resolve_credential,
)


def test_build_client_api_key_usa_x_api_key():
    cred = ProviderCredential(name="claude", mode="api_key", secret="sk-real")
    client = build_anthropic_client(cred)
    headers = {k.lower(): v for k, v in client.auth_headers.items()}
    assert headers.get("x-api-key") == "sk-real"
    assert "authorization" not in headers


def test_build_client_subscription_usa_bearer_y_beta():
    cred = ProviderCredential(name="claude", mode="subscription", secret="oauth-xyz")
    client = build_anthropic_client(cred)
    headers = {k.lower(): v for k, v in client.auth_headers.items()}
    assert headers.get("authorization") == "Bearer oauth-xyz"
    assert "x-api-key" not in headers
    # El header beta de OAuth viaja como default header.
    default = {k.lower(): v for k, v in client.default_headers.items()}
    assert default.get("anthropic-beta") == OAUTH_BETA


def test_oauth_system_prefix_solo_en_suscripcion():
    sub = ProviderCredential(name="claude", mode="subscription", secret="x")
    api = ProviderCredential(name="claude", mode="api_key", secret="x")
    assert oauth_system_prefix(sub) == CLAUDE_CODE_IDENTITY
    assert oauth_system_prefix(api) is None
    assert oauth_system_prefix(None) is None


def test_credential_from_config():
    cfg = {"provider": {"name": "claude", "mode": "subscription", "secret": "oauth-z"}}
    cred = credential_from_config(cfg)
    assert cred == ProviderCredential("claude", "subscription", "oauth-z")
    # Sin secreto o sin provider → None
    assert credential_from_config({"provider": {"name": "claude", "mode": "api_key"}}) is None
    assert credential_from_config({}) is None
    assert credential_from_config(None) is None
    # name/mode inválidos → None (no se confía en config corrupta)
    assert credential_from_config({"provider": {"name": "x", "mode": "api_key", "secret": "s"}}) is None


def test_default_credential_cae_al_entorno(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert default_credential() is None
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    assert default_credential() == ProviderCredential("claude", "api_key", "sk-env")


def test_resolve_credential_panel_gana_al_entorno(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    cfg = {"provider": {"name": "claude", "mode": "api_key", "secret": "sk-panel"}}
    assert resolve_credential(cfg).secret == "sk-panel"  # el panel manda
    assert resolve_credential({}).secret == "sk-env"  # sin panel, el entorno


def test_runner_antepone_identidad_en_suscripcion(fake_client_factory):
    # Cliente fake + credencial de suscripción explícita: el system lleva el prefijo.
    client = fake_client_factory(FakeResponse("ok"))
    cred = ProviderCredential("claude", "subscription", "oauth-z")
    runner = ClaudeRunner(client=client, credential=cred)
    runner.complete(system="Eres el asistente.", user="hola", model="m", task="t")
    sent = client.messages.requests[0]["system"]
    assert sent.startswith(CLAUDE_CODE_IDENTITY)
    assert "Eres el asistente." in sent


def test_runner_sin_credencial_no_antepone_nada(fake_client_factory):
    client = fake_client_factory(FakeResponse("ok"))
    runner = ClaudeRunner(client=client)  # como en el resto de los tests del engine
    runner.complete(system="Eres el asistente.", user="hola", model="m", task="t")
    assert client.messages.requests[0]["system"] == "Eres el asistente."


def test_el_cliente_lleva_timeout_explicito_en_ambas_vias():
    """El default del SDK son 10 MINUTOS por llamada (con reintentos): una
    redacción colgada retenía la transacción de la corrida y el dueño veía
    "database is locked" al querer aprobar. Ambas vías llevan timeout propio."""
    from aiuda_core.engine.provider import LLM_TIMEOUT_S

    api = build_anthropic_client(ProviderCredential(name="claude", mode="api_key", secret="sk-x"))
    sub = build_anthropic_client(
        ProviderCredential(name="claude", mode="subscription", secret="oauth-x")
    )
    assert api.timeout == LLM_TIMEOUT_S
    assert sub.timeout == LLM_TIMEOUT_S
    # Y el fallback self-host del runner (API key del entorno) también.
    runner = ClaudeRunner(credential=None)
    assert runner._client.timeout == LLM_TIMEOUT_S
