"""La prueba de conexión del proveedor: veredicto honesto por el mismo camino del motor."""

import anthropic
import httpx

from aiuda_core.engine.provider import (
    CLAUDE_CODE_IDENTITY,
    ProviderCredential,
)
# Alias: pytest colectaría `test_credential` como caso de prueba por el prefijo `test_`.
from aiuda_core.engine.provider import test_credential as check_credential


class _FakeMessages:
    def __init__(self, result=None, exc=None, sink=None):
        self._result, self._exc, self._sink = result, exc, sink

    def create(self, **kwargs):
        if self._sink is not None:
            self._sink.append(kwargs)
        if self._exc:
            raise self._exc
        return self._result


class _FakeClient:
    def __init__(self, result=None, exc=None, sink=None):
        self.messages = _FakeMessages(result, exc, sink)


def _resp(code: int) -> httpx.Response:
    return httpx.Response(code, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _api_key() -> ProviderCredential:
    return ProviderCredential(name="claude", mode="api_key", secret="sk-ant-x")


def _sub() -> ProviderCredential:
    return ProviderCredential(name="claude", mode="subscription", secret="oauth-tok")


def test_exito_reporta_ok_y_latencia():
    r = check_credential(_api_key(), client=_FakeClient(result=object()))
    assert r["ok"] is True
    assert r["mode"] == "api_key"
    assert "latency_ms" in r and r["latency_ms"] >= 0
    assert r["model"]  # el modelo probado


def test_suscripcion_antepone_identidad_claude_code():
    # Anthropic rechaza el token OAuth si el system no declara la identidad de Claude Code.
    sink: list[dict] = []
    r = check_credential(_sub(), client=_FakeClient(result=object(), sink=sink))
    assert r["ok"] is True
    assert sink and sink[0].get("system") == CLAUDE_CODE_IDENTITY


def test_api_key_no_manda_prefijo():
    sink: list[dict] = []
    check_credential(_api_key(), client=_FakeClient(result=object(), sink=sink))
    assert "system" not in sink[0]


def test_token_rechazado_mapea_auth():
    exc = anthropic.AuthenticationError("no", response=_resp(401), body=None)
    r = check_credential(_sub(), client=_FakeClient(exc=exc))
    assert r["ok"] is False and r["code"] == "auth"


def test_rate_limit_mapea_rate_limit():
    exc = anthropic.RateLimitError("slow", response=_resp(429), body=None)
    r = check_credential(_sub(), client=_FakeClient(exc=exc))
    assert r["ok"] is False and r["code"] == "rate_limit"


def test_permiso_denegado_mapea_permission():
    exc = anthropic.PermissionDeniedError("nope", response=_resp(403), body=None)
    r = check_credential(_sub(), client=_FakeClient(exc=exc))
    assert r["ok"] is False and r["code"] == "permission"


def test_error_inesperado_no_relanza():
    r = check_credential(_api_key(), client=_FakeClient(exc=ValueError("boom")))
    assert r["ok"] is False and r["code"] == "unknown" and "boom" in r["error"]
