"""OpenAI por suscripcion de ChatGPT (Sign in with ChatGPT / Codex).

Igual que la via de suscripcion de Claude (token de `claude setup-token`), esto usa tu
suscripcion PERSONAL de ChatGPT para alimentar la app. OpenAI no documenta oficialmente
este uso en apps de terceros, aunque tampoco lo prohibe explicitamente como Anthropic. Es
opt-in y bajo tu riesgo; la UI lo advierte.

Aislamiento por workspace: el bundle de token {access, refresh, account_id} vive CIFRADO en
su fila (IntegrationCredential 'ia'); `CodexRunner` autentica con ese bundle EN MEMORIA y, al
rotar el token (refresh contra auth.openai.com), lo persiste re-cifrado — NUNCA en un
`~/.codex/auth.json` global compartido.
El archivo local queda solo como fallback de self-host mono-usuario. El motor pega al backend de
Codex (chatgpt.com/backend-api/codex/responses), Responses API en streaming. Protocolo verificado
en vivo contra una cuenta real (2026-07): `gpt-5.x` general (los *-codex los rechaza la cuenta
ChatGPT), `stream:true` obligatorio, sin `max_output_tokens`, texto por deltas, tool calls como
items function_call.

Direccion de imports (sin ciclos): runner.py -> codex.py -> provider.py.
"""

import base64
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from aiuda_core.config import settings
from aiuda_core.engine.llm import BudgetCheck, UsageCallback
from aiuda_core.engine.provider import ProviderCredential

logger = logging.getLogger(__name__)

# OAuth de Codex (fuente: doc oficial developers.openai.com/codex/auth + CLI open source).
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_SCOPE = "openid profile email offline_access"
# Backend de Codex (Responses API con la suscripcion, NO api.openai.com).
BACKEND_RESPONSES = "https://chatgpt.com/backend-api/codex/responses"
# Se manda tal cual el CLI oficial para que el backend acepte el token de suscripcion.
ORIGINATOR = "codex_cli_rs"
RESPONSES_BETA = "responses=experimental"
# Responses API ESTANDAR con API key (sk-...): la via soportada y facturada de OpenAI.
# Mismo protocolo SSE que el backend de Codex; solo cambian el endpoint y los headers (sin
# chatgpt-account-id ni originator). CodexRunner la usa cuando se construye con api_key.
API_RESPONSES = "https://api.openai.com/v1/responses"

# --- "Iniciar sesion con ChatGPT" por device code (sin pegar auth.json) ------------------
# Flujo device (estilo RFC 8628, variante de OpenAI). Fuente: openai/codex, codex-rs/login/
# src/device_code_auth.rs + server.rs. La consola pide un user_code, el dueno lo aprueba en
# el navegador, y el backend sondea hasta canjear los tokens. NADA se escribe en disco.
AUTH_BASE = "https://auth.openai.com"
DEVICE_USERCODE_URL = f"{AUTH_BASE}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{AUTH_BASE}/api/accounts/deviceauth/token"
# La pagina que el dueno abre para meter el codigo (aprobacion de OpenAI).
DEVICE_VERIFY_URL = f"{AUTH_BASE}/codex/device"
# redirect_uri que /oauth/token exige al canjear el device code (no hay servidor local).
DEVICE_REDIRECT_URI = f"{AUTH_BASE}/deviceauth/callback"
# El backend no manda expiracion; el CLI oficial corta a los 15 min.
DEVICE_EXPIRES_SECS = 15 * 60


def auth_path() -> Path:
    """Ruta del auth.json que el CLI de codex escribe (override por CODEX_HOME)."""
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "auth.json"


def _jwt_exp(token: str) -> int | None:
    """Lee el claim `exp` de un JWT sin verificar firma (solo para saber si expiro)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # padding base64url
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _account_id_from_id_token(id_token: str) -> str:
    """Saca `chatgpt_account_id` del id_token (JWT) que OpenAI devuelve al canjear la sesion.
    Vive anidado bajo el claim namespaced `https://api.openai.com/auth` (fuente: codex-rs
    token_data.rs). Mismo decode base64url que `_jwt_exp`, sin verificar firma. '' si no esta."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # padding base64url
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return ""
    auth = data.get("https://api.openai.com/auth") if isinstance(data, dict) else None
    if isinstance(auth, dict):
        return (auth.get("chatgpt_account_id") or "").strip()
    return ""


def read_tokens(path: Path | None = None) -> dict | None:
    """Lee {access_token, account_id, refresh_token} de auth.json. None si no hay sesion."""
    p = path or auth_path()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    tok = data.get("tokens") or {}
    access = (tok.get("access_token") or "").strip()
    if not access:
        return None
    return {
        "access_token": access,
        "account_id": (tok.get("account_id") or "").strip(),
        "refresh_token": (tok.get("refresh_token") or "").strip(),
    }


def logged_in(path: Path | None = None) -> bool:
    """Hay una sesion de codex utilizable en la maquina."""
    return read_tokens(path) is not None


def tokens_from_json(text: str) -> dict | None:
    """Parses el contenido de un auth.json (el dueño lo pega tras correr `codex login` en SU
    maquina) al bundle {access_token, account_id, refresh_token}. Acepta el formato completo
    de codex ({"tokens": {...}}) o un objeto plano con los campos. None si no trae access."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tok = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    access = (tok.get("access_token") or "").strip()
    if not access:
        return None
    return {
        "access_token": access,
        "account_id": (tok.get("account_id") or "").strip(),
        "refresh_token": (tok.get("refresh_token") or "").strip(),
    }


def _write_refreshed(path: Path, new: dict) -> None:
    """Reescribe auth.json conservando el formato de codex (mismo archivo, un solo origen
    de verdad para codex y aiuda). Escritura atomica."""
    p = path
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        data = {}
    tokens = dict(data.get("tokens") or {})
    tokens["access_token"] = new["access_token"]
    if new.get("id_token"):
        tokens["id_token"] = new["id_token"]
    if new.get("refresh_token"):
        tokens["refresh_token"] = new["refresh_token"]
    data["tokens"] = tokens
    data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, p)


def refresh_bundle(refresh_token: str) -> dict | None:
    """Canjea el refresh_token por tokens nuevos SIN tocar disco. El bundle del workspace
    vive cifrado en la base, no en un archivo global.
    Devuelve {access_token, refresh_token, id_token} o None si el refresh falla. OpenAI
    ROTA el refresh_token: si el body trae uno nuevo, se propaga; si no, se conserva el
    anterior (así la próxima corrida no se queda sin con qué refrescar)."""
    try:
        r = httpx.post(
            TOKEN_URL,
            json={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": OAUTH_SCOPE,
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        logger.warning("codex: fallo de red al refrescar el token: %s", exc)
        return None
    if r.status_code != 200:
        logger.warning("codex: refresh rechazado (%s). Hay que reconectar OpenAI.", r.status_code)
        return None
    body = r.json()
    access = (body.get("access_token") or "").strip()
    if not access:
        return None
    return {
        "access_token": access,
        "refresh_token": (body.get("refresh_token") or "").strip() or refresh_token,
        "id_token": body.get("id_token"),
    }


def refresh_access(refresh_token: str, path: Path | None = None) -> str | None:
    """Vía self-host (archivo local): canjea el refresh_token y lo persiste en auth.json.
    Devuelve el access nuevo, o None si el refresh falla (el usuario debe reconectar).
    Reusa ``refresh_bundle`` para el canje; solo esta variante toca disco."""
    p = path or auth_path()
    new = refresh_bundle(refresh_token)
    if new is None:
        return None
    _write_refreshed(p, new)
    return new["access_token"]


def current_access(path: Path | None = None, *, skew: int = 120) -> tuple[str, str] | None:
    """(access_token vigente, account_id). Refresca si el token expiro. None si no hay sesion
    o el refresh fallo. `skew`: margen en segundos para refrescar antes de la expiracion."""
    toks = read_tokens(path)
    if toks is None:
        return None
    access, account, refresh = toks["access_token"], toks["account_id"], toks["refresh_token"]
    exp = _jwt_exp(access)
    if exp is not None and exp - skew <= time.time() and refresh:
        renewed = refresh_access(refresh, path)
        if renewed:
            access = renewed
    return access, account


def device_start(http_post: Callable[..., httpx.Response] | None = None) -> dict:
    """Arranca "Iniciar sesion con ChatGPT" por device code. Pide un user_code al backend de
    OpenAI; el dueno lo aprueba en su navegador y luego se sondea (``device_poll``). Devuelve
    lo que la consola necesita: el codigo, la URL a abrir, el intervalo de sondeo y la
    expiracion. Levanta CodexError si OpenAI no responde. `http_post` inyectable para tests."""
    post = http_post or httpx.post
    try:
        r = post(DEVICE_USERCODE_URL, json={"client_id": CLIENT_ID}, timeout=30)
    except httpx.HTTPError as exc:
        raise CodexError(f"No se pudo iniciar sesion con ChatGPT: {exc}") from exc
    if r.status_code != 200:
        raise CodexError(f"OpenAI rechazo el inicio de sesion (codigo {r.status_code}).")
    body = r.json()
    device_auth_id = (body.get("device_auth_id") or "").strip()
    user_code = (body.get("user_code") or body.get("usercode") or "").strip()
    if not device_auth_id or not user_code:
        raise CodexError("OpenAI no devolvio un codigo de dispositivo utilizable.")
    try:
        interval = int(body.get("interval") or 5)
    except (TypeError, ValueError):
        interval = 5
    return {
        "device_code": device_auth_id,
        "user_code": user_code,
        "verification_uri": DEVICE_VERIFY_URL,
        "interval": max(1, interval),
        "expires_in": DEVICE_EXPIRES_SECS,
    }


def device_poll(
    device_code: str,
    user_code: str,
    http_post: Callable[..., httpx.Response] | None = None,
) -> dict:
    """Sondea UNA vez el device code (la consola lo llama en bucle segun `interval`).
      pendiente -> {"status": "pending"}
      listo     -> {"status": "success", "bundle": {access_token, refresh_token, account_id}}
      error     -> {"status": "error", "error": "..."}
    Mientras el dueno no autorice, OpenAI responde 403/404 (pendiente). Al autorizar devuelve
    un authorization_code + code_verifier (el PKCE lo genera el server) que se canjea de
    inmediato por los tokens en /oauth/token. `http_post` inyectable para tests."""
    post = http_post or httpx.post
    try:
        r = post(
            DEVICE_TOKEN_URL,
            json={"device_auth_id": device_code, "user_code": user_code},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return {"status": "error", "error": f"No se pudo sondear a OpenAI: {exc}"}
    if r.status_code in (403, 404):
        return {"status": "pending"}
    if r.status_code != 200:
        return {"status": "error", "error": f"OpenAI respondio {r.status_code} al autorizar."}
    data = r.json()
    auth_code = (data.get("authorization_code") or "").strip()
    verifier = (data.get("code_verifier") or "").strip()
    if not auth_code or not verifier:
        return {"status": "error", "error": "OpenAI autorizo pero no devolvio el codigo para canjear."}
    bundle = _exchange_device_code(auth_code, verifier, http_post=post)
    if bundle is None:
        return {"status": "error", "error": "No se pudo canjear la sesion de ChatGPT. Reintenta."}
    return {"status": "success", "bundle": bundle}


def _exchange_device_code(
    auth_code: str,
    code_verifier: str,
    *,
    http_post: Callable[..., httpx.Response] | None = None,
) -> dict | None:
    """Canjea el authorization_code (con el code_verifier de PKCE) por el bundle de tokens en
    /oauth/token (form-urlencoded, como el CLI). Devuelve {access_token, refresh_token,
    account_id} o None si el canje falla. account_id sale del id_token (JWT)."""
    post = http_post or httpx.post
    try:
        r = post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": DEVICE_REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        logger.warning("codex: canje de device code fallo (red): %s", exc)
        return None
    if r.status_code != 200:
        logger.warning("codex: canje de device code rechazado (%s).", r.status_code)
        return None
    body = r.json()
    access = (body.get("access_token") or "").strip()
    if not access:
        return None
    return {
        "access_token": access,
        "refresh_token": (body.get("refresh_token") or "").strip(),
        "account_id": _account_id_from_id_token(body.get("id_token") or ""),
    }


def _headers(access: str, account: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access}",
        "chatgpt-account-id": account,
        "OpenAI-Beta": RESPONSES_BETA,
        "originator": ORIGINATOR,
        "Content-Type": "application/json",
    }


def _api_key_headers(api_key: str) -> dict[str, str]:
    """Headers de la Responses API ESTANDAR con API key: solo Bearer + Content-Type (sin los
    headers propios del backend de Codex, que api.openai.com no espera)."""
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _to_openai_tool(tool: dict) -> dict:
    """Traduce una tool del formato Anthropic ({name, description, input_schema}) al de la
    Responses API de OpenAI ({type:function, name, description, parameters})."""
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
    }


class CodexError(Exception):
    """Fallo hablando con el backend de Codex (token, red, o respuesta invalida)."""


class CodexRunner:
    """ProviderRunner sobre la suscripcion de ChatGPT. Espeja la interfaz de ClaudeRunner
    (model_for/complete/classify/run_tool_loop) hablando la Responses API en streaming."""

    def __init__(
        self,
        credential: ProviderCredential | None = None,
        usage_callback: UsageCallback | None = None,
        budget_check: BudgetCheck | None = None,
        *,
        tokens: dict | None = None,
        api_key: str | None = None,
        on_refresh: Callable[[dict], None] | None = None,
        auth_path_override: Path | None = None,
        http_post: Callable[..., httpx.Response] | None = None,
    ):
        self._credential = credential
        self._usage_callback = usage_callback
        # Tope de gasto: publico y asignable despues de construir (igual que ClaudeRunner).
        self.budget_check: BudgetCheck | None = budget_check
        # Via API KEY (sk-...): habla la Responses API ESTANDAR de OpenAI (api.openai.com), no
        # el backend de Codex. Es la via soportada/facturada. Si esta, manda sobre `tokens`
        # (una API key no se refresca ni tiene account_id). None => via suscripcion.
        self._api_key = (api_key or "").strip() or None
        # Bundle de token por workspace: {access_token, refresh_token,
        # account_id}, descifrado de la fila del tenant. Vive EN MEMORIA durante la
        # corrida; al rotar (refresh) se persiste vía on_refresh, nunca en un archivo
        # global compartido. Si es None, cae al archivo local (self-host mono-usuario).
        self._tokens = dict(tokens) if tokens else None
        self._on_refresh = on_refresh
        self._auth_path = auth_path_override
        # Inyectable para tests: por default, el stream real con httpx.
        self._http_post = http_post

    @property
    def mode(self) -> str:
        """Via efectiva: 'api_key' (Responses API estandar) o 'subscription' (backend Codex)."""
        return "api_key" if self._api_key else "subscription"

    def _endpoint(self) -> str:
        """A donde va el POST del stream: api.openai.com (API key) o el backend de Codex."""
        return API_RESPONSES if self._api_key else BACKEND_RESPONSES

    def _request_headers(self, access: str, account: str) -> dict[str, str]:
        """Headers segun la via: API key (Bearer simple) o suscripcion (headers de Codex)."""
        if self._api_key:
            return _api_key_headers(self._api_key)
        return _headers(access, account)

    # -- sesion (per-tenant en memoria, o archivo local self-host) -----------
    def _has_session(self) -> bool:
        """Hay un token utilizable para este runner (API key, bundle del tenant o archivo)."""
        if self._api_key:
            return True
        if self._tokens is not None:
            return bool((self._tokens.get("access_token") or "").strip())
        return read_tokens(self._auth_path) is not None

    def _access(self) -> tuple[str, str] | None:
        """(access_token vigente, account_id). API key: se usa tal cual, sin account ni
        refresh. Con bundle per-tenant refresca EN MEMORIA y persiste vía on_refresh; sin
        bundle usa el archivo local (self-host)."""
        if self._api_key:
            return self._api_key, ""
        if self._tokens is None:
            return current_access(self._auth_path)
        access = (self._tokens.get("access_token") or "").strip()
        account = (self._tokens.get("account_id") or "").strip()
        refresh = (self._tokens.get("refresh_token") or "").strip()
        if not access:
            return None
        exp = _jwt_exp(access)
        if exp is not None and exp - 120 <= time.time() and refresh:
            forced = self._force_refresh()
            if forced is not None:
                access, account = forced
        return access, account

    def _force_refresh(self) -> tuple[str, str] | None:
        """Refresca el token tras expiracion o un 401. Per-tenant: rota en memoria y
        persiste; self-host: reescribe el archivo. None si el refresh falla (reconectar)."""
        if self._api_key:
            return None  # una API key no se refresca; un 401 = key invalida, hay que reconectar
        if self._tokens is not None:
            refresh = (self._tokens.get("refresh_token") or "").strip()
            new = refresh_bundle(refresh) if refresh else None
            if not new:
                return None
            self._tokens = {
                **self._tokens,
                "access_token": new["access_token"],
                "refresh_token": new["refresh_token"],
            }
            if self._on_refresh is not None:
                self._on_refresh(dict(self._tokens))
            return new["access_token"], (self._tokens.get("account_id") or "").strip()
        toks = read_tokens(self._auth_path)
        renewed = (
            refresh_access(toks["refresh_token"], self._auth_path)
            if toks and toks.get("refresh_token")
            else None
        )
        if not renewed:
            return None
        return renewed, (toks.get("account_id") or "").strip()

    # -- roles -> modelos ----------------------------------------------------
    def model_for(self, role: str) -> str:
        if role == "triage":
            return settings.model_codex_triage
        if role == "redaccion":
            return settings.model_codex
        raise ValueError(f"Rol de modelo desconocido: {role}")

    # -- llamada base (SSE) --------------------------------------------------
    def _post_stream(self, headers: dict, body: dict) -> httpx.Response:
        endpoint = self._endpoint()
        if self._http_post is not None:
            return self._http_post(endpoint, headers=headers, json=body)
        client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))
        return client.stream("POST", endpoint, headers=headers, json=body)

    def _run(self, model: str, instructions: str, input_items: list[dict], tools: list[dict] | None):
        """Una vuelta a la Responses API. Devuelve (texto, output_items, tool_calls, usage).

        output_items: los items crudos (reasoning/message/function_call) para reenviar en el
        siguiente turno de un tool loop. tool_calls: subconjunto function_call.
        """
        if self.budget_check is not None:
            self.budget_check()  # corte honesto del tope ANTES de gastar

        cur = self._access()
        if cur is None:
            raise CodexError(
                "No hay sesion de OpenAI (ChatGPT). Reconecta en Proveedor de IA."
            )
        access, account = cur

        body: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_items,
            "stream": True,
            "store": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        text, items, usage, retried = self._consume(self._request_headers(access, account), body)
        # 401: token vencido entre el read y el post. Refresca una vez y reintenta.
        if retried == 401:
            forced = self._force_refresh()
            if forced is None:
                raise CodexError("La sesion de OpenAI no autorizo (401). Reconecta OpenAI.")
            access, account = forced
            text, items, usage, retried = self._consume(self._request_headers(access, account), body)
            if retried:
                raise CodexError(f"El backend de Codex respondio {retried}.")
        elif retried:
            raise CodexError(f"El backend de Codex respondio {retried}.")

        tool_calls = [it for it in items if it.get("type") == "function_call"]
        return text, items, tool_calls, usage

    def _consume(self, headers: dict, body: dict):
        """Ejecuta el POST y parsea el SSE. Devuelve (texto, items, usage, error_status).
        error_status es 0 si todo bien, o el codigo HTTP si el backend rechazo."""
        text_parts: list[str] = []
        items: list[dict] = []
        usage: dict | None = None

        resp = self._post_stream(headers, body)
        # Cliente inyectado (tests) devuelve una Response ya leida; el real es un stream.
        is_stream_ctx = hasattr(resp, "__enter__")
        ctx = resp if is_stream_ctx else _NullCtx(resp)
        with ctx as r:
            if r.status_code != 200:
                detail = r.read() if is_stream_ctx else getattr(r, "content", b"")
                logger.warning("codex: backend %s: %s", r.status_code, detail[:200])
                return "", [], None, r.status_code
            lines = r.iter_lines() if is_stream_ctx else r.text.splitlines()
            for line in lines:
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    ev = json.loads(payload)
                except ValueError:
                    continue
                etype = ev.get("type")
                if etype == "response.output_text.delta":
                    text_parts.append(ev.get("delta", ""))
                elif etype == "response.output_item.done":
                    items.append(ev.get("item") or {})
                elif etype == "response.completed":
                    usage = (ev.get("response") or {}).get("usage")
        text = "".join(text_parts)
        if not text:  # respaldo: reconstruye del item message si no hubo deltas
            text = _text_from_items(items)
        return text, items, usage, 0

    def _record(self, model: str, task: str, usage: dict | None) -> None:
        if self._usage_callback and usage:
            self._usage_callback(
                model, task, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
            )

    # -- interfaz ProviderRunner --------------------------------------------
    def complete(
        self,
        system: str,
        user: str,
        *,
        task: str,
        model: str | None = None,
        role: str = "redaccion",
        max_tokens: int = 1024,  # el backend de Codex no acepta max_output_tokens; se ignora
    ) -> str:
        model = model or self.model_for(role)
        input_items = [{"role": "user", "content": [{"type": "input_text", "text": user}]}]
        text, _items, _tc, usage = self._run(model, system, input_items, None)
        self._record(model, task, usage)
        return text

    def classify(self, system: str, user: str, *, labels: list[str], task: str) -> str:
        raw = self.complete(
            system=system + f"\nResponde UNICAMENTE con una de estas etiquetas: {labels}",
            user=user,
            role="triage",
            task=task,
            max_tokens=16,
        )
        cleaned = raw.strip().lower()
        return cleaned if cleaned in labels else labels[-1]

    def run_tool_loop(
        self,
        *,
        system: str,
        user_message: str,
        tools: list[dict],
        execute_tool: Callable[[str, dict], str],
        model: str | None = None,
        role: str = "redaccion",
        task: str = "agent_loop",
        max_iterations: int = 8,
    ) -> str:
        """Loop agentico manual (gates de aprobacion y logging por iteracion), como el de
        ClaudeRunner pero sobre la Responses API. Los items del turno (reasoning/message/
        function_call) se reenvian tal cual en el siguiente, y cada tool responde con un
        item function_call_output."""
        model = model or self.model_for(role)
        oa_tools = [_to_openai_tool(t) for t in tools]
        input_items: list[dict] = [
            {"role": "user", "content": [{"type": "input_text", "text": user_message}]}
        ]

        for _ in range(max_iterations):
            text, items, tool_calls, usage = self._run(model, system, input_items, oa_tools)
            self._record(model, task, usage)

            if not tool_calls:
                return text

            input_items.extend(items)  # reenvia reasoning + function_call del modelo
            for call in tool_calls:
                try:
                    args = json.loads(call.get("arguments") or "{}")
                    result = execute_tool(call.get("name", ""), dict(args))
                except Exception as exc:  # el agente puede adaptarse al error
                    result = f"Error: {exc}"
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id", ""),
                        "output": result,
                    }
                )

        return "Lo siento, no pude completar esta tarea. Un humano la revisara."


class _NullCtx:
    """Envuelve una Response ya materializada (tests) para el mismo `with` que el stream real."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


def _text_from_items(items: list[dict]) -> str:
    """Reconstruye el texto del item message (respaldo si no hubo deltas de texto)."""
    parts: list[str] = []
    for it in items:
        if it.get("type") == "message":
            for c in it.get("content") or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts)


def test_codex(runner: CodexRunner | None = None) -> dict:
    """Prueba REAL: una llamada minima al backend de Codex por el mismo camino del motor.
    Nunca relanza; devuelve un veredicto honesto (misma forma que test_credential de Claude).
      ok=True  -> {ok, mode, model, latency_ms}
      ok=False -> {ok, mode, code, error}  (code: not_configured|auth|network|status|unknown)

    Con ``runner`` (el del tenant, con su bundle cifrado o su API key) la sesion se verifica
    per-tenant; sin el, cae al archivo local (self-host). El `mode` del veredicto refleja la
    via real del runner (api_key vs subscription)."""
    r = runner or CodexRunner()
    mode = r.mode
    if not r._has_session():
        return {
            "ok": False,
            "mode": mode,
            "code": "not_configured",
            "error": "No hay sesion de OpenAI. Conecta con 'Iniciar sesion con ChatGPT' o tu API key.",
        }
    model = settings.model_codex
    t0 = time.monotonic()
    try:
        r.complete(system="Responde en una palabra.", user="ping", task="provider_test", role="redaccion")
        return {"ok": True, "mode": mode, "model": model, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except CodexError as exc:
        msg = str(exc)
        code = "auth" if "401" in msg or "sesion" in msg.lower() else "status"
        return {"ok": False, "mode": mode, "code": code, "error": msg}
    except httpx.HTTPError as exc:
        return {"ok": False, "mode": mode, "code": "network", "error": f"No se pudo conectar con OpenAI: {exc}"}
    except Exception as exc:  # noqa: BLE001 — el test nunca tumba el endpoint
        return {"ok": False, "mode": mode, "code": "unknown", "error": str(exc)[:200] or "Error desconocido."}
