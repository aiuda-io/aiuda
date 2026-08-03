"""OpenAI por la Responses API estandar (api.openai.com), con TU API key.

Es la via soportada y facturada de OpenAI. Mismo protocolo SSE que usa el CLI de Codex;
aqui solo se habla el endpoint publico con `Authorization: Bearer sk-...`.

QUE SE QUITO Y POR QUE. Este modulo tambien sabia hablarle a
chatgpt.com/backend-api/codex/responses con el token de una suscripcion personal de
ChatGPT, mandando `originator: codex_cli_rs` "tal cual el CLI oficial para que el backend
acepte el token". Eso es hacerse pasar por otro cliente para pasar un control de acceso, y
en un proyecto Apache-2.0 le transfiere el riesgo a quien lo instale y a cada fork. Con
ello se fueron el device flow ("Iniciar sesion con ChatGPT"), el refresh de tokens y el
`~/.codex/auth.json`.

Quien quiera usar su suscripcion tiene la via legitima: instalar `codex` y elegirlo como
proveedor (`codex_cli`). Ese binario se autentica con SU sesion y aiuda nunca ve el token.

Protocolo verificado en vivo (2026-07): `stream:true` obligatorio, sin `max_output_tokens`,
texto por deltas, tool calls como items function_call.

Direccion de imports (sin ciclos): runner.py -> codex.py -> provider.py.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from aiuda_core.config import settings
from aiuda_core.engine.llm import BudgetCheck, UsageCallback
from aiuda_core.engine.provider import ProviderCredential

logger = logging.getLogger(__name__)

# Responses API ESTANDAR con API key (sk-...): la via soportada y facturada de OpenAI.
API_RESPONSES = "https://api.openai.com/v1/responses"


def _api_key_headers(api_key: str) -> dict[str, str]:
    """Headers de la Responses API estandar: Bearer + Content-Type, nada mas."""
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
    """Fallo hablando con la Responses API (llave, red, o respuesta invalida)."""


class CodexRunner:
    """ProviderRunner sobre la Responses API de OpenAI con la API key del dueno. Espeja la
    interfaz de ClaudeRunner (model_for/complete/classify/run_tool_loop) en streaming."""

    def __init__(
        self,
        credential: ProviderCredential | None = None,
        usage_callback: UsageCallback | None = None,
        budget_check: BudgetCheck | None = None,
        *,
        api_key: str | None = None,
        http_post: Callable[..., httpx.Response] | None = None,
    ):
        self._credential = credential
        self._usage_callback = usage_callback
        # Tope de gasto: publico y asignable despues de construir (igual que ClaudeRunner).
        self.budget_check: BudgetCheck | None = budget_check
        self._api_key = (api_key or "").strip() or None
        # Inyectable para tests: por default, el stream real con httpx.
        self._http_post = http_post

    @property
    def mode(self) -> str:
        return "api_key"

    def _has_session(self) -> bool:
        return self._api_key is not None

    # -- roles -> modelos ----------------------------------------------------
    def model_for(self, role: str) -> str:
        if role == "triage":
            return settings.model_codex_triage
        if role == "redaccion":
            return settings.model_codex
        raise ValueError(f"Rol de modelo desconocido: {role}")

    # -- llamada base (SSE) --------------------------------------------------
    def _post_stream(self, headers: dict, body: dict) -> httpx.Response:
        if self._http_post is not None:
            return self._http_post(API_RESPONSES, headers=headers, json=body)
        client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))
        return client.stream("POST", API_RESPONSES, headers=headers, json=body)

    def _run(self, model: str, instructions: str, input_items: list[dict], tools: list[dict] | None):
        """Una vuelta a la Responses API. Devuelve (texto, output_items, tool_calls, usage).

        output_items: los items crudos (reasoning/message/function_call) para reenviar en el
        siguiente turno de un tool loop. tool_calls: subconjunto function_call.
        """
        if self.budget_check is not None:
            self.budget_check()  # corte honesto del tope ANTES de gastar

        if self._api_key is None:
            raise CodexError("Falta tu API key de OpenAI. Conectala en Tu IA.")

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

        text, items, usage, retried = self._consume(_api_key_headers(self._api_key), body)
        if retried == 401:
            raise CodexError("Tu API key de OpenAI no autorizo (401). Revisala en Tu IA.")
        if retried:
            raise CodexError(f"OpenAI respondio {retried}.")

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
                logger.warning("codex: OpenAI respondio %s: %s", r.status_code, detail[:200])
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

    Con ``runner`` (el del tenant, con su API key descifrada) se verifica su llave."""
    r = runner or CodexRunner()
    mode = r.mode
    if not r._has_session():
        return {
            "ok": False,
            "mode": mode,
            "code": "not_configured",
            "error": "Falta tu API key de OpenAI. Pegala en Tu IA.",
        }
    model = settings.model_codex
    t0 = time.monotonic()
    try:
        r.complete(system="Responde en una palabra.", user="ping", task="provider_test", role="redaccion")
        return {"ok": True, "mode": mode, "model": model, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except CodexError as exc:
        msg = str(exc)
        code = "auth" if "401" in msg or "key" in msg.lower() else "status"
        return {"ok": False, "mode": mode, "code": code, "error": msg}
    except httpx.HTTPError as exc:
        return {"ok": False, "mode": mode, "code": "network", "error": f"No se pudo conectar con OpenAI: {exc}"}
    except Exception as exc:  # noqa: BLE001 — el test nunca tumba el endpoint
        return {"ok": False, "mode": mode, "code": "unknown", "error": str(exc)[:200] or "Error desconocido."}
