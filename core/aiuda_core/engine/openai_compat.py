"""Runner OpenAI-compatible: IA local (Ollama, LM Studio, vLLM) o cualquier
endpoint /v1/chat/completions con tool calling.

Es la tercera pata del BYO-IA y la única 100% privada: el modelo corre en la
máquina del dueño y ningún dato sale de ella. La credencial guarda un JSON
{"base_url", "model", "api_key"} (api_key opcional: Ollama no la necesita).

Contrato: cumple ProviderRunner (complete/classify/run_tool_loop/model_for) con
el MISMO formato de tools que usa el motor (Anthropic: name/description/
input_schema); aquí se traducen a functions de OpenAI.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama
TIMEOUT_S = 180.0  # modelos locales en CPU pueden tardar; honesto antes que colgar


def parse_local_secret(secret: str) -> dict:
    """El secreto de la credencial 'local': JSON {base_url, model, api_key}."""
    try:
        data = json.loads(secret or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "base_url": (data.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        "model": (data.get("model") or "").strip(),
        "api_key": (data.get("api_key") or "").strip(),
    }


def _to_openai_tool(tool: dict) -> dict:
    """Anthropic {name, description, input_schema} → OpenAI function tool."""
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


class CompatRunner:
    """ProviderRunner contra un endpoint OpenAI-compatible."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str,
        api_key: str = "",
        usage_callback: Callable | None = None,
        client: httpx.Client | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._usage_callback = usage_callback
        self.budget_check: Callable[[], None] | None = None
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    # ------------------------------------------------------------------ #
    def model_for(self, role: str) -> str:
        # Un solo modelo local cubre triage y redacción (no hay tier barato aparte).
        if role in ("triage", "redaccion"):
            return self._model
        raise ValueError(f"Rol de modelo desconocido: {role}")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _chat(self, *, messages: list[dict], task: str, model: str,
              tools: list[dict] | None = None, max_tokens: int = 1024) -> dict:
        if self.budget_check is not None:
            self.budget_check()
        payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        response = self._client.post(
            f"{self._base}/chat/completions", json=payload, headers=self._headers()
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        if self._usage_callback is not None:
            self._usage_callback(
                model, task, int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
        return data["choices"][0]["message"]

    # ------------------------------------------------------------------ #
    def complete(self, system: str, user: str, *, task: str, model: str | None = None,
                 role: str = "redaccion", max_tokens: int = 1024) -> str:
        message = self._chat(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            task=task, model=model or self.model_for(role), max_tokens=max_tokens,
        )
        return (message.get("content") or "").strip()

    def classify(self, system: str, user: str, *, labels: list[str], task: str) -> str:
        raw = self.complete(
            system=system + f"\nResponde ÚNICAMENTE con una de estas etiquetas: {labels}",
            user=user, role="triage", task=task, max_tokens=16,
        )
        cleaned = raw.strip().lower()
        return cleaned if cleaned in labels else labels[-1]

    def run_tool_loop(self, *, system: str, user_message: str, tools: list[dict],
                      execute_tool: Callable[[str, dict], str], model: str | None = None,
                      role: str = "redaccion", task: str = "agent_loop",
                      max_iterations: int = 8) -> str:
        model = model or self.model_for(role)
        oa_tools = [_to_openai_tool(t) for t in tools]
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        for _ in range(max_iterations):
            message = self._chat(
                messages=messages, task=task, model=model, tools=oa_tools, max_tokens=2048
            )
            calls = message.get("tool_calls") or []
            if not calls:
                return (message.get("content") or "").strip()
            messages.append(message)
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                try:
                    result = execute_tool(fn.get("name", ""), args)
                except Exception as exc:  # el agente puede adaptarse al error
                    result = f"Error: {exc}"
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
                )
        return "Lo siento, no pude completar esta tarea. Un humano la revisará."


def test_local(secret: str, *, client: httpx.Client | None = None) -> dict:
    """UNA llamada mínima real al endpoint local, mismo camino que el motor.
    Veredicto honesto: ok=True → {ok, mode, model, latency_ms}; ok=False →
    {ok, mode, code, error} (code: config|network|status|unknown)."""
    import time

    cfg = parse_local_secret(secret)
    if not cfg["model"]:
        return {
            "ok": False, "mode": "api_key", "code": "config",
            "error": "Falta el nombre del modelo (p.ej. llama3.1, qwen2.5).",
        }
    runner = CompatRunner(
        base_url=cfg["base_url"], model=cfg["model"], api_key=cfg["api_key"], client=client
    )
    t0 = time.monotonic()
    try:
        runner.complete(system="Responde en una palabra.", user="ping", task="test", max_tokens=8)
        return {
            "ok": True, "mode": "api_key", "model": cfg["model"],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except httpx.ConnectError:
        return {
            "ok": False, "mode": "api_key", "code": "network",
            "error": f"No responde {cfg['base_url']}. ¿Está corriendo Ollama (ollama serve)?",
        }
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = (exc.response.json().get("error") or {}).get("message") or ""
        except Exception:  # noqa: BLE001
            detail = exc.response.text[:120]
        return {
            "ok": False, "mode": "api_key", "code": "status",
            "error": f"El endpoint respondió {exc.response.status_code}. {detail}".strip(),
        }
    except Exception as exc:  # noqa: BLE001 — el test nunca tumba el endpoint
        return {
            "ok": False, "mode": "api_key", "code": "unknown",
            "error": str(exc)[:200] or "Error desconocido al probar la conexión.",
        }
