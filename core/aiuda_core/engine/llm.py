"""Wrapper del SDK de Anthropic: loop de tool-use con control fino y registro de uso.

Lo usa el motor dentro del proceso local; la capa HTTP nunca lo llama directo
(ver ARCHITECTURE.md).
"""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import anthropic

from aiuda_core.config import settings
from aiuda_core.engine.provider import (
    LLM_TIMEOUT_S,
    ProviderCredential,
    build_anthropic_client,
    default_credential,
)

logger = logging.getLogger(__name__)

# La redacción de aiuda es ASÍNCRONA: la corrida diaria deja borradores en Aprobaciones y
# esperan tu visto bueno. No hay prisa. Por eso, ante el 429 de ráfaga de la SUSCRIPCIÓN
# (plan personal, límites de ráfaga muy bajos), esperamos de verdad —segundos— y reintentamos
# el MISMO cliente: la ventana de ráfaga suele ceder. Son esperas largas y deliberadas, NO los
# reintentos rápidos del SDK (que re-disparan al instante sin ceder; por eso el cliente de
# suscripción va con max_retries=0). Agotadas las esperas, o si el token se rechaza (401/403),
# se cae a la API key de respaldo (si hay una). Un error de red o un 5xx NO disparan nada: son
# transitorios, no "esta credencial no sirve".

# Regla dura de aiuda: cero emojis en la salida del LLM. Red de seguridad sobre
# todo lo que el modelo redacta (recordatorios, chat, etc.).
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D\U000024C2]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Quita emojis. Cero emojis es regla dura del producto."""
    return _EMOJI_RE.sub("", text)


# Lo que el modelo redacta va DIRECTO al WhatsApp/correo del cliente: markdown de
# reporte (negritas **, encabezados #, separadores ---) se ve roto ahí. La regla de
# formato vive en el prompt (regla 9 de Mariana); esto es la red determinista sobre
# lo obvio. Deliberadamente NO toca *asteriscos simples*, _guiones bajos simples_ ni
# listas con guion: son texto plano legítimo (y WhatsApp los usa como formato propio).
_MD_NEGRITAS_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", flags=re.DOTALL)
_MD_ENCABEZADO_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", flags=re.MULTILINE)
_MD_SEPARADOR_RE = re.compile(r"^[ \t]*([-*_])[ \t]*(?:\1[ \t]*){2,}$\n?", flags=re.MULTILINE)


def strip_markdown(text: str) -> str:
    """Plancha el markdown obvio de reporte sin romper texto legítimo: el cliente
    recibe texto plano conversacional. Red determinista junto a strip_emojis.

    Los separadores salen ANTES que las negritas: si hubiera dos líneas `___`,
    la regex de negritas (que cruza líneas) se comería medio bloque."""
    text = _MD_SEPARADOR_RE.sub("", text)
    text = _MD_ENCABEZADO_RE.sub("", text)
    text = _MD_NEGRITAS_RE.sub(lambda m: m.group(1) or m.group(2), text)
    return re.sub(r"\n{3,}", "\n\n", text)

# usage_callback(model, task, input_tokens, output_tokens)
UsageCallback = Callable[[str, str, int, int], None]

# budget_check() — se invoca ANTES de cada llamada al proveedor; lanza BudgetExceeded
# si el tope de gasto de IA del tenant está agotado. La capa cloud lo inyecta.
BudgetCheck = Callable[[], None]


class BudgetExceeded(Exception):
    """Tope de gasto de IA agotado: la llamada al proveedor NO se hace (corte honesto).

    La lanza el budget_check inyectado; el mensaje explica el motivo al dueño."""


class ClaudeRunner:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        usage_callback: UsageCallback | None = None,
        credential: ProviderCredential | None = None,
        rate_backoff: tuple[int, ...] | None = None,
        budget_check: BudgetCheck | None = None,
    ):
        # Cliente inyectado (tests) gana; si no, se construye desde la credencial efectiva
        # (la explícita o, como fallback self-host, la API key del entorno).
        if client is not None:
            self._client = client
        else:
            cred = credential or default_credential()
            self._client = (
                build_anthropic_client(cred)
                if cred
                # Mismo timeout explícito que build_anthropic_client: sin él, el
                # SDK espera hasta 10 minutos por llamada reteniendo la corrida.
                else anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=LLM_TIMEOUT_S)
            )
        self._usage_callback = usage_callback
        # Tope de gasto: público y asignable después de construir (la capa cloud lo
        # engancha igual que el usage_callback). None = sin tope (self-host, tests).
        self.budget_check: BudgetCheck | None = budget_check

        # Backoff ante 429. Vacío por default: con API key el SDK ya trae sus reintentos.
        # Inyectable para tests y para quien tenga una cuenta con ráfaga apretada.
        self._rate_backoff: tuple[int, ...] = rate_backoff or ()

    def _create(self, **kwargs: Any):
        """Una llamada a messages.create, con espera opcional ante el 429 de ráfaga.

        Reintenta la MISMA llamada, no el loop: reintentar el loop re-ejecutaría tools con
        efectos (registrar_pago, etc.). Un error de red o un 5xx NO disparan nada de esto:
        son transitorios, no 'credencial inválida'."""
        # Corte honesto del tope de gasto: si el tenant agotó su presupuesto de IA, la
        # llamada NO sale (ni en el primer turno ni a media iteración de un tool loop).
        if self.budget_check is not None:
            self.budget_check()
        for delay in (*self._rate_backoff, None):
            try:
                return self._client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                if delay is None:
                    raise
                logger.warning("IA: 429 de ráfaga; espero %ss y reintento.", delay)
                time.sleep(delay)

    def model_for(self, role: str) -> str:
        """Model id de un rol ('triage'|'redaccion') para el proveedor activo.

        Desacopla los call sites de los ids concretos de Claude: un CodexRunner futuro
        mapearía estos mismos roles a sus propios modelos.
        """
        if role == "triage":
            return settings.model_triage
        if role == "redaccion":
            return settings.model_redaccion
        raise ValueError(f"Rol de modelo desconocido: {role}")

    def _record(self, model: str, task: str, usage: Any) -> None:
        if self._usage_callback and usage is not None:
            self._usage_callback(
                model, task, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)
            )

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        role: str = "redaccion",
        task: str,
        max_tokens: int = 1024,
    ) -> str:
        """Una sola llamada texto → texto (redacción, clasificación).

        `role` elige el modelo del proveedor; `model` sigue siendo un override opcional.
        """
        model = model or self.model_for(role)
        response = self._create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self._record(model, task, response.usage)
        return next((b.text for b in response.content if b.type == "text"), "")

    def classify(self, system: str, user: str, *, labels: list[str], task: str) -> str:
        """Clasificación con Haiku. Devuelve siempre una de `labels` (fallback: la última)."""
        raw = self.complete(
            system=system + f"\nResponde ÚNICAMENTE con una de estas etiquetas: {labels}",
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
        """Loop agéntico manual: permite gates de aprobación y logging por iteración."""
        model = model or self.model_for(role)
        messages: list[dict] = [{"role": "user", "content": user_message}]

        for _ in range(max_iterations):
            response = self._create(
                model=model,
                max_tokens=2048,
                system=system,
                tools=tools,
                messages=messages,
            )
            self._record(model, task, response.usage)

            if response.stop_reason != "tool_use":
                return next((b.text for b in response.content if b.type == "text"), "")

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    # block.input ya viene parseado por el SDK
                    result = execute_tool(block.name, dict(block.input))
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
                except Exception as exc:  # el agente puede adaptarse al error
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})

        return "Lo siento, no pude completar esta tarea. Un humano la revisará."


def parse_json_block(text: str) -> dict:
    """Extrae el primer objeto JSON de una respuesta de modelo."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
