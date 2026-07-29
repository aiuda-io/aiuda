"""CodexRunner: OpenAI por suscripción de ChatGPT (Responses API). SSE mockeado, sin red.

El protocolo real (endpoint, headers, gpt-5.x, stream obligatorio, formato de function_call)
se verificó en vivo contra una cuenta ChatGPT; aquí se prueba la LÓGICA del runner: traducción
de tools, acumulación de texto por deltas, el loop de tools reenviando items, el registro de
uso, el corte por tope, y los errores honestos.
"""

import json
import time

import pytest

from aiuda_core.engine import codex
from aiuda_core.engine.codex import CodexError, CodexRunner, _jwt_exp, _to_openai_tool
from aiuda_core.engine.llm import BudgetExceeded


def _sse(events: list[dict]) -> str:
    return "".join(f"data: {json.dumps(e)}\n" for e in events)


class _FakeResp:
    """Respuesta ya materializada (no-stream): el runner la consume por r.text."""

    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text
        self.content = text.encode()


def _post_seq(responses: list[_FakeResp]):
    it = iter(responses)

    def post(url, headers=None, json=None):  # noqa: A002
        return next(it)

    return post


@pytest.fixture()
def auth_file(tmp_path):
    """auth.json falso con un access_token NO-JWT (sin exp): current_access no refresca."""
    p = tmp_path / "auth.json"
    p.write_text(
        json.dumps(
            {"tokens": {"access_token": "faketoken", "account_id": "acct-1", "refresh_token": "r-1"}}
        )
    )
    return p


# --- helpers puros ----------------------------------------------------------
def test_traduce_tool_anthropic_a_openai():
    tool = {"name": "cobrar", "description": "Cobra.", "input_schema": {"type": "object", "properties": {"x": {"type": "number"}}}}
    out = _to_openai_tool(tool)
    assert out == {
        "type": "function",
        "name": "cobrar",
        "description": "Cobra.",
        "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
    }


def test_jwt_exp_lee_expiracion():
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1234567890}).encode()).decode().rstrip("=")
    assert _jwt_exp(f"h.{payload}.sig") == 1234567890
    assert _jwt_exp("no-es-jwt") is None


def test_read_tokens_y_logged_in(tmp_path):
    assert codex.read_tokens(tmp_path / "nope.json") is None
    assert codex.logged_in(tmp_path / "nope.json") is False
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"tokens": {"access_token": "a", "account_id": "acc", "refresh_token": "r"}}))
    toks = codex.read_tokens(p)
    assert toks == {"access_token": "a", "account_id": "acc", "refresh_token": "r"}
    assert codex.logged_in(p) is True


def test_model_for_usa_settings_codex(auth_file):
    r = CodexRunner(auth_path_override=auth_file)
    assert r.model_for("triage").startswith("gpt-5")
    assert r.model_for("redaccion").startswith("gpt-5")
    with pytest.raises(ValueError):
        r.model_for("desconocido")


# --- complete (texto por deltas) -------------------------------------------
def test_complete_acumula_texto_y_registra_uso(auth_file):
    events = [
        {"type": "response.output_text.delta", "delta": "lis"},
        {"type": "response.output_text.delta", "delta": "to"},
        {"type": "response.output_item.done", "item": {"type": "message", "content": [{"type": "output_text", "text": "listo"}]}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 10, "output_tokens": 3}}},
    ]
    uso = []
    r = CodexRunner(
        auth_path_override=auth_file,
        usage_callback=lambda m, t, i, o: uso.append((m, t, i, o)),
        http_post=_post_seq([_FakeResp(200, _sse(events))]),
    )
    assert r.complete(system="s", user="u", task="redaccion_test") == "listo"
    assert uso == [("gpt-5.5", "redaccion_test", 10, 3)]


def test_complete_respaldo_texto_desde_item_message_sin_deltas(auth_file):
    events = [
        {"type": "response.output_item.done", "item": {"type": "message", "content": [{"type": "output_text", "text": "solo item"}]}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 1}}},
    ]
    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([_FakeResp(200, _sse(events))]))
    assert r.complete(system="s", user="u", task="t") == "solo item"


# --- run_tool_loop (round-trip) --------------------------------------------
def test_tool_loop_ejecuta_tool_y_devuelve_respuesta_final(auth_file):
    turno1 = [
        {"type": "response.output_item.done", "item": {"type": "reasoning", "content": [], "summary": []}},
        {"type": "response.output_item.done", "item": {"type": "function_call", "name": "registrar_pago", "arguments": '{"monto": 500}', "call_id": "call_1"}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 20, "output_tokens": 5}}},
    ]
    turno2 = [
        {"type": "response.output_text.delta", "delta": "Pago registrado."},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 30, "output_tokens": 2}}},
    ]
    ejecutadas = []

    def execute(name, args):
        ejecutadas.append((name, args))
        return "folio A-1"

    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([_FakeResp(200, _sse(turno1)), _FakeResp(200, _sse(turno2))]))
    tools = [{"name": "registrar_pago", "description": "Registra.", "input_schema": {"type": "object", "properties": {"monto": {"type": "number"}}}}]
    out = r.run_tool_loop(system="s", user_message="pago de 500", tools=tools, execute_tool=execute)
    assert ejecutadas == [("registrar_pago", {"monto": 500})]
    assert out == "Pago registrado."


def test_tool_loop_tool_que_truena_no_rompe_el_loop(auth_file):
    turno1 = [
        {"type": "response.output_item.done", "item": {"type": "function_call", "name": "x", "arguments": "{}", "call_id": "c1"}},
        {"type": "response.completed", "response": {"usage": {}}},
    ]
    turno2 = [
        {"type": "response.output_text.delta", "delta": "sigo vivo"},
        {"type": "response.completed", "response": {"usage": {}}},
    ]

    def boom(name, args):
        raise RuntimeError("falla")

    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([_FakeResp(200, _sse(turno1)), _FakeResp(200, _sse(turno2))]))
    out = r.run_tool_loop(system="s", user_message="u", tools=[{"name": "x", "description": "", "input_schema": {}}], execute_tool=boom)
    assert out == "sigo vivo"


# --- cortes y errores honestos ---------------------------------------------
def test_budget_check_corta_antes_de_llamar(auth_file):
    def sin_cupo():
        raise BudgetExceeded("tope agotado")

    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([]))  # no debe llamarse
    r.budget_check = sin_cupo
    with pytest.raises(BudgetExceeded):
        r.complete(system="s", user="u", task="t")


def test_backend_error_da_codex_error(auth_file):
    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([_FakeResp(500, '{"detail":"boom"}')]))
    with pytest.raises(CodexError):
        r.complete(system="s", user="u", task="t")


def test_sin_sesion_da_codex_error(tmp_path):
    r = CodexRunner(auth_path_override=tmp_path / "nope.json", http_post=_post_seq([]))
    with pytest.raises(CodexError):
        r.complete(system="s", user="u", task="t")


def test_401_sin_refresh_da_codex_error(auth_file, monkeypatch):
    monkeypatch.setattr(codex, "refresh_access", lambda *a, **k: None)
    r = CodexRunner(auth_path_override=auth_file, http_post=_post_seq([_FakeResp(401, "no autorizado")]))
    with pytest.raises(CodexError):
        r.complete(system="s", user="u", task="t")


def test_test_codex_sin_sesion_reporta_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "auth_path", lambda: tmp_path / "nope.json")
    v = codex.test_codex()
    assert v["ok"] is False and v["code"] == "not_configured"


# --- bundle por workspace: sin archivo global, cierra la fuga ----------------
def _jwt_token(exp: int) -> str:
    import base64

    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


def _ok_events():
    return [
        {"type": "response.output_text.delta", "delta": "hola"},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1, "output_tokens": 1}}},
    ]


def test_bundle_per_tenant_no_toca_el_archivo_global(monkeypatch, tmp_path):
    """Con tokens per-tenant el runner autentica con el bundle EN MEMORIA, no con
    ~/.codex/auth.json. Apuntamos auth_path a un archivo inexistente: si lo tocara, fallaría."""
    monkeypatch.setattr(codex, "auth_path", lambda: tmp_path / "no-existe.json")
    bundle = {"access_token": _jwt_token(int(time.time()) + 3600), "refresh_token": "r", "account_id": "acct-1"}
    r = CodexRunner(tokens=bundle, http_post=_post_seq([_FakeResp(200, _sse(_ok_events()))]))
    assert r._has_session() is True
    assert r.complete(system="s", user="u", task="t") == "hola"


def test_bundle_expirado_refresca_en_memoria_y_persiste(monkeypatch):
    """Access expirado → refresca vía refresh_bundle (sin disco) y persiste vía on_refresh
    con el refresh_token ROTADO. La corrida usa el token nuevo."""
    monkeypatch.setattr(
        codex, "refresh_bundle", lambda rt: {"access_token": "nuevo", "refresh_token": "r-rotado", "id_token": None}
    )
    persisted: dict = {}
    seen: dict = {}

    def post(url, headers=None, json=None):  # noqa: A002
        seen.update(headers or {})
        return _FakeResp(200, _sse(_ok_events()))

    bundle = {"access_token": _jwt_token(int(time.time()) - 10), "refresh_token": "r-viejo", "account_id": "acct-1"}
    r = CodexRunner(tokens=bundle, on_refresh=lambda b: persisted.update(b), http_post=post)
    assert r.complete(system="s", user="u", task="t") == "hola"
    assert seen["Authorization"] == "Bearer nuevo"
    assert persisted["access_token"] == "nuevo" and persisted["refresh_token"] == "r-rotado"


def test_bundle_401_fuerza_refresh_y_reintenta(monkeypatch):
    """401 en la primera llamada → _force_refresh per-tenant y reintento con el token nuevo."""
    monkeypatch.setattr(
        codex, "refresh_bundle", lambda rt: {"access_token": "nuevo", "refresh_token": "r2", "id_token": None}
    )
    persisted: dict = {}
    bundle = {"access_token": _jwt_token(int(time.time()) + 3600), "refresh_token": "r1", "account_id": "acct-1"}
    r = CodexRunner(
        tokens=bundle,
        on_refresh=lambda b: persisted.update(b),
        http_post=_post_seq([_FakeResp(401, "no autorizado"), _FakeResp(200, _sse(_ok_events()))]),
    )
    assert r.complete(system="s", user="u", task="t") == "hola"
    assert persisted["access_token"] == "nuevo"


# --- device code ("Iniciar sesion con ChatGPT" sin pegar auth.json) ----------
class _JsonResp:
    """Respuesta del backend OAuth (no-stream): el flujo device la consume por .json()."""

    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _id_token_with_account(account_id: str) -> str:
    """id_token (JWT) con el account_id anidado bajo el claim namespaced que usa OpenAI."""
    import base64

    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"h.{b64}.s"


def test_account_id_from_id_token_lee_el_claim_namespaced():
    assert codex._account_id_from_id_token(_id_token_with_account("acct-xyz")) == "acct-xyz"
    assert codex._account_id_from_id_token("no-es-jwt") == ""
    # Un JWT sin el claim de auth -> "".
    import base64

    b = base64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).decode().rstrip("=")
    assert codex._account_id_from_id_token(f"h.{b}.s") == ""


def test_device_start_pide_codigo_y_devuelve_lo_que_la_consola_necesita():
    calls = []

    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        calls.append((url, json))
        return _JsonResp(200, {"device_auth_id": "dev-1", "user_code": "ABCD-1234", "interval": 7})

    out = codex.device_start(http_post=post)
    assert out["device_code"] == "dev-1"
    assert out["user_code"] == "ABCD-1234"
    assert out["verification_uri"] == codex.DEVICE_VERIFY_URL
    assert out["interval"] == 7
    assert out["expires_in"] == codex.DEVICE_EXPIRES_SECS
    # Pidio el usercode al endpoint correcto, con el client_id publico.
    assert calls[0] == (codex.DEVICE_USERCODE_URL, {"client_id": codex.CLIENT_ID})


def test_device_start_acepta_alias_usercode_y_da_intervalo_minimo():
    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        return _JsonResp(200, {"device_auth_id": "d", "usercode": "WXYZ", "interval": 0})

    out = codex.device_start(http_post=post)
    assert out["user_code"] == "WXYZ"
    assert out["interval"] == 5  # 0/ausente -> default sano


def test_device_start_rechazado_da_codex_error():
    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        return _JsonResp(500, {})

    with pytest.raises(CodexError):
        codex.device_start(http_post=post)


def test_device_poll_pendiente_mientras_no_autoriza():
    for status in (403, 404):

        def post(url, json=None, data=None, timeout=None, _s=status):  # noqa: A002
            return _JsonResp(_s, {})

        assert codex.device_poll("dev-1", "ABCD-1234", http_post=post) == {"status": "pending"}


def test_device_poll_exito_canjea_codigo_y_arma_bundle():
    id_token = _id_token_with_account("acct-9")
    vistos = []

    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        vistos.append(url)
        if url == codex.DEVICE_TOKEN_URL:
            # OpenAI exige device_auth_id + user_code en el poll.
            assert json == {"device_auth_id": "dev-1", "user_code": "ABCD-1234"}
            return _JsonResp(200, {"authorization_code": "auth-1", "code_challenge": "chal", "code_verifier": "ver-1"})
        # Canje en /oauth/token: form con el code + code_verifier (PKCE) + redirect del device.
        assert url == codex.TOKEN_URL
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "auth-1"
        assert data["code_verifier"] == "ver-1"
        assert data["redirect_uri"] == codex.DEVICE_REDIRECT_URI
        assert data["client_id"] == codex.CLIENT_ID
        return _JsonResp(200, {"access_token": "acc", "refresh_token": "ref", "id_token": id_token})

    out = codex.device_poll("dev-1", "ABCD-1234", http_post=post)
    assert out["status"] == "success"
    assert out["bundle"] == {"access_token": "acc", "refresh_token": "ref", "account_id": "acct-9"}
    assert vistos == [codex.DEVICE_TOKEN_URL, codex.TOKEN_URL]


def test_device_poll_canje_fallido_da_error():
    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        if url == codex.DEVICE_TOKEN_URL:
            return _JsonResp(200, {"authorization_code": "a", "code_verifier": "v"})
        return _JsonResp(400, {})  # /oauth/token rechaza

    out = codex.device_poll("dev-1", "x", http_post=post)
    assert out["status"] == "error"


def test_device_poll_status_inesperado_da_error():
    def post(url, json=None, data=None, timeout=None):  # noqa: A002
        return _JsonResp(500, {})

    out = codex.device_poll("dev-1", "x", http_post=post)
    assert out["status"] == "error" and "500" in out["error"]


# --- via API KEY: Responses API ESTANDAR de OpenAI (no el backend de Codex) ---
def test_api_key_usa_endpoint_estandar_y_bearer_simple():
    seen = {}

    def post(url, headers=None, json=None):  # noqa: A002
        seen["url"] = url
        seen["headers"] = headers
        return _FakeResp(200, _sse(_ok_events()))

    r = CodexRunner(api_key="sk-test", http_post=post)
    assert r.mode == "api_key"
    assert r._has_session() is True  # una API key siempre es sesion utilizable
    assert r.complete(system="s", user="u", task="t") == "hola"
    assert seen["url"] == codex.API_RESPONSES
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    # Sin los headers propios del backend de Codex (api.openai.com no los espera).
    assert "chatgpt-account-id" not in seen["headers"]
    assert "originator" not in seen["headers"]


def test_api_key_no_refresca_en_401():
    # Con API key un 401 = key invalida: no hay refresh, se levanta el error honesto.
    r = CodexRunner(api_key="sk-mala", http_post=_post_seq([_FakeResp(401, "no autorizado")]))
    with pytest.raises(CodexError):
        r.complete(system="s", user="u", task="t")


def test_test_codex_reporta_mode_api_key():
    r = CodexRunner(api_key="sk-test", http_post=_post_seq([_FakeResp(200, _sse(_ok_events()))]))
    v = codex.test_codex(r)
    assert v["ok"] is True and v["mode"] == "api_key"
