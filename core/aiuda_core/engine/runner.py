"""Capa de proveedor agnóstica: una interfaz común (ProviderRunner) y un factory.

El engine habla con un ProviderRunner, no con un cliente concreto. Dos implementaciones:
ClaudeRunner (llm.py, SDK de Anthropic) y CodexRunner (codex.py, Responses API de OpenAI por
suscripción de ChatGPT). make_runner elige según el nombre de la credencial; los call sites no
cambian.

Dirección de imports (sin ciclos): runner.py → {llm.py, codex.py} → provider.py. provider.py
no importa ninguno.
"""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from aiuda_core.engine.llm import ClaudeRunner, UsageCallback
from aiuda_core.engine.provider import ProviderCredential, default_credential


class ProviderUnavailable(Exception):
    """El proveedor solicitado no está disponible todavía (ej. Codex)."""


def _fallback_credential(cred: ProviderCredential | None) -> ProviderCredential | None:
    """Credencial de respaldo cuando la vía primaria es suscripción.

    Solo la suscripción cede: su token OAuth puede rechazarse y su plan personal agota
    ráfaga. La API key del entorno (con tope de gasto bajo) toma el relevo. La vía api_key
    no necesita respaldo: ya trae reintentos y es la vía soportada."""
    if cred is not None and cred.mode == "subscription":
        env = default_credential()
        if env is not None and env.secret != cred.secret:
            return env
    return None


@runtime_checkable
class ProviderRunner(Protocol):
    """Lo que el engine necesita de cualquier proveedor de IA. ClaudeRunner ya lo cumple."""

    def model_for(self, role: str) -> str: ...

    def complete(
        self,
        system: str,
        user: str,
        *,
        task: str,
        model: str | None = None,
        role: str = "redaccion",
        max_tokens: int = 1024,
    ) -> str: ...

    def classify(self, system: str, user: str, *, labels: list[str], task: str) -> str: ...

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
    ) -> str: ...


def make_runner(
    credential: ProviderCredential | None,
    usage_callback: UsageCallback | None = None,
    token_persist: Callable[[dict], None] | None = None,
) -> ProviderRunner:
    """Runner del proveedor de la credencial (o el fallback de entorno si es None).

    claude / sin credencial → ClaudeRunner (con caída a la API key de entorno si la vía es
    suscripción). codex → CodexRunner: con API key (mode=api_key) habla la Responses API
    ESTÁNDAR de OpenAI; con suscripción usa el bundle de token DEL TENANT (cifrado), que
    refresca en memoria y persiste vía ``token_persist`` (no comparte el archivo global).
    """
    cred = credential or default_credential()
    name = cred.name if cred else "claude"
    if name == "claude":
        return ClaudeRunner(
            credential=cred,
            usage_callback=usage_callback,
            fallback_credential=_fallback_credential(cred),
        )
    if name == "codex":
        from aiuda_core.engine.codex import CodexRunner
        from aiuda_core.engine.provider import codex_tokens

        if cred is not None and cred.mode == "api_key":
            # sk-...: la Responses API estándar (api.openai.com). No hay token que refrescar.
            return CodexRunner(credential=cred, usage_callback=usage_callback, api_key=cred.secret)
        return CodexRunner(
            credential=cred,
            usage_callback=usage_callback,
            tokens=codex_tokens(cred),
            on_refresh=token_persist,
        )
    if name in ("claude_cli", "codex_cli"):
        # El CLI del dueño, tal cual: su sesión, su cuenta, sin credenciales
        # que aiuda tenga que guardar.
        from aiuda_core.engine.cli_runner import CliRunner

        return CliRunner(name.removesuffix("_cli"), usage_callback=usage_callback)
    if name == "local":
        from aiuda_core.engine.openai_compat import CompatRunner, parse_local_secret

        cfg = parse_local_secret(cred.secret if cred else "")
        return CompatRunner(
            base_url=cfg["base_url"],
            model=cfg["model"],
            api_key=cfg["api_key"],
            usage_callback=usage_callback,
        )
    raise ProviderUnavailable(f"Proveedor desconocido: {name}")
