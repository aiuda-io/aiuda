"""Metering y tope de gasto de IA: el pegamento entre el motor y las cuotas.

Un solo lugar arma el runner del proveedor para un tenant con:

1. `usage_recorder` — cada llamada al proveedor deja un UsageEvent (modelo, tarea,
   tokens de entrada/salida). Es la base del costo estimado y del tope.
2. `budget_check` — se evalúa ANTES de cada llamada (hook en ClaudeRunner._create)
   y lanza BudgetExceeded si el tope que el dueño se puso está agotado. Corte
   honesto: la corrida NO llama a la IA, ni a media iteración.

Los endpoints atrapan BudgetExceeded → 402 con el motivo; los jobs la atrapan →
dejan aviso en la bitácora y siguen sin IA.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from aiuda_server import costs
from aiuda_core.connectors import credentials as cred
from aiuda_core.engine.llm import BudgetExceeded, UsageCallback
from aiuda_core.engine.provider import resolve_credential
from aiuda_core.engine.runner import ProviderRunner, make_runner
from aiuda_core.models import Tenant, UsageEvent

__all__ = ["BudgetExceeded", "budget_check", "tenant_runner", "usage_recorder"]


def usage_recorder(db, tenant_id: str) -> UsageCallback:
    """Callback de uso: registra cada llamada al proveedor como UsageEvent."""

    def _record(model: str, task: str, input_tokens: int, output_tokens: int) -> None:
        db.add(
            UsageEvent(
                tenant_id=tenant_id,
                model=model,
                task=task,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )

    return _record


def budget_check(db, tenant: Tenant):
    """Chequeo de presupuesto para enganchar al runner. Se reevalúa EN CADA llamada
    (los UsageEvents de la misma corrida cuentan vía autoflush): si el tope se agota
    a media corrida, la siguiente llamada ya no sale."""

    def _check() -> None:
        verdict = costs.ia_budget(db, tenant)
        if verdict["agotado"]:
            raise BudgetExceeded(costs.ia_budget_message(verdict))

    return _check


def _codex_token_persist(db, tenant_id: str) -> Callable[[dict], None]:
    """Persiste el bundle de token de Codex tras un refresh, re-cifrándolo POR TENANT.
    Sin esto, la rotación del refresh_token de OpenAI se perdería y el tenant tendría que
    reconectar cada hora. Conserva 'connected' (refresh_secret no toca el status)."""

    def _persist(bundle: dict) -> None:
        cred.refresh_secret(
            db, tenant_id, "ia", {"secret": json.dumps(bundle, separators=(",", ":"))}
        )

    return _persist


def tenant_runner(db, tenant: Tenant) -> ProviderRunner:
    """Runner del proveedor del tenant con metering y tope enganchados. Es la vía
    canónica de la capa HTTP/worker; construir el runner a mano se salta el tope."""
    runner = make_runner(
        resolve_credential(session=db, tenant_id=tenant.id),
        usage_callback=usage_recorder(db, tenant.id),
        token_persist=_codex_token_persist(db, tenant.id),
    )
    runner.budget_check = budget_check(db, tenant)
    return runner
