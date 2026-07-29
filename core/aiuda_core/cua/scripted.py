"""Agente de GUION para misiones CUA: determinista, sin IA.

NO es el agente de computer-use: es un cliente falso (misma interfaz que el cliente
Anthropic que usa el runner) que emite una secuencia FIJA de acciones para operar los
portales de prueba locales (`cua/portales.py`). Sirve para dos cosas:

1. Verificar el ciclo completo del CUA — instrucción del dueño → prompt → acciones en un
   Chromium real → evidencia/bitácora — sin credencial de IA y sin gastar tokens.
2. Sembrar corridas de demostración honestas: el resumen dice tal cual que fue un guion.

Sí lee el prompt real que arma el runner (por eso prueba que la instrucción del dueño
llega): del prompt del tribunal extrae el número de expediente indicado y lo teclea. Los
"datos extraídos" que entrega son los MISMOS que muestran los portales de prueba; contra
cualquier otro portal este guion no sabe operar y no debe usarse.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

# Lo que cada portal de prueba muestra (idéntico al HTML en cua/portales/). El guion
# entrega esto como "datos extraídos": coherente con lo que la evidencia enseña.
DATOS_PORTAL = {
    "banca_movimientos": {
        "depositos": [
            {"fecha": "2026-06-28", "monto": 12500.00, "concepto": "SPEI recibido - Joyeria Aurora"},
            {"fecha": "2026-06-29", "monto": 4800.00, "concepto": "Deposito ventanilla - Ferreteria del Valle"},
            {"fecha": "2026-07-01", "monto": 2150.50, "concepto": "SPEI recibido - Taqueria El Sol"},
            {"fecha": "2026-07-02", "monto": 9300.00, "concepto": "Transferencia - Cliente 88213"},
        ]
    },
    "sat_cfdi_recibidos": {
        "cfdis": [
            {"folio": "A1B2-4411", "emisor": "Papeleria Central SA de CV", "monto": 1860.00, "fecha": "2026-07-01"},
            {"folio": "C3D4-8032", "emisor": "Transportes Norte SA de CV", "monto": 7540.00, "fecha": "2026-07-02"},
            {"folio": "E5F6-1290", "emisor": "Servicios TI Cumbre SC", "monto": 11600.00, "fecha": "2026-07-04"},
            {"folio": "G7H8-5567", "emisor": "Comercializadora Rio SA de CV", "monto": 3220.00, "fecha": "2026-07-06"},
        ]
    },
}

ACUERDOS_PORTAL = {
    "123/2026": [
        {"fecha": "2026-06-30", "sintesis": "Se admite la demanda y se ordena emplazar a la parte demandada."},
        {"fecha": "2026-07-04", "sintesis": "Se tiene por contestada la demanda; se abre periodo probatorio."},
    ],
    "77/2025": [
        {"fecha": "2026-06-18", "sintesis": "Se difiere la audiencia incidental a peticion de ambas partes."},
        {"fecha": "2026-07-02", "sintesis": "Se dicta sentencia interlocutoria; se condena al pago de costas."},
    ],
}

# Expediente que el guion busca cuando la instrucción del dueño no indica uno.
EXPEDIENTE_DEFAULT = "123/2026"

_RE_EXPEDIENTE = re.compile(r"expediente\s+(\d{1,5}/\d{4})", re.IGNORECASE)


def _accion(n: int, action: str, **params) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"guion-{n}", input={"action": action, **params})


def _texto(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def _resp(*blocks) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks))


def _prompt_de(messages: list) -> str:
    """El prompt de la misión que armó el runner (primer bloque de texto del user)."""
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    return str(b.get("text") or "")
    return ""


def expediente_en(texto: str) -> str:
    """Número de expediente indicado en la instrucción (o el default del guion)."""
    m = _RE_EXPEDIENTE.search(texto)
    return m.group(1) if m else EXPEDIENTE_DEFAULT


def _guion(plantilla: str, prompt: str) -> tuple[list[list], dict]:
    """(turnos de acciones, datos finales) del guion para esa plantilla. Los portales de
    prueba se navegan por teclado: autofocus en el primer campo, Tab y Enter (submit)."""
    n = iter(range(1, 100))
    # El wait inicial deja asentar la página (como el agente real, que primero mira la
    # captura); el final deja que el submit pinte antes de la última evidencia.
    if plantilla == "banca_movimientos":
        turnos = [
            [_accion(next(n), "wait", duration=0.5)],
            [_accion(next(n), "type", text="demo")],
            [_accion(next(n), "key", text="Tab")],
            [_accion(next(n), "type", text="aiuda123")],
            [_accion(next(n), "key", text="Return")],
            [_accion(next(n), "wait", duration=0.5)],
        ]
        return turnos, DATOS_PORTAL[plantilla]
    if plantilla == "sat_cfdi_recibidos":
        turnos = [
            [_accion(next(n), "wait", duration=0.5)],
            [_accion(next(n), "type", text="LABO860415XY1")],
            [_accion(next(n), "key", text="Tab")],
            [_accion(next(n), "type", text="aiuda123")],
            [_accion(next(n), "key", text="Return")],
            [_accion(next(n), "wait", duration=0.5)],
        ]
        return turnos, DATOS_PORTAL[plantilla]
    if plantilla == "tribunal_acuerdos":
        exp = expediente_en(prompt)
        turnos = [
            [_accion(next(n), "wait", duration=0.5)],
            [_accion(next(n), "type", text=exp)],
            [_accion(next(n), "key", text="Return")],
            [_accion(next(n), "wait", duration=0.5)],
        ]
        return turnos, {"acuerdos": ACUERDOS_PORTAL.get(exp, [])}
    raise ValueError(f"El guion no conoce la plantilla {plantilla!r}.")


class _MensajesGuion:
    def __init__(self, plantilla: str):
        self._plantilla = plantilla
        self._turnos: list[list] | None = None
        self._final: dict = {}
        self._i = 0

    async def create(self, **kw):
        if self._turnos is None:  # primer turno: lee el prompt real y arma el guion
            prompt = _prompt_de(kw.get("messages") or [])
            self._turnos, self._final = _guion(self._plantilla, prompt)
        if self._i < len(self._turnos):
            turno = self._turnos[self._i]
            self._i += 1
            return _resp(*turno)
        final = {
            **self._final,
            "_resumen": (
                "Corrida de verificación con guion determinista (sin IA) sobre el "
                "portal de prueba local."
            ),
        }
        return _resp(_texto(json.dumps(final, ensure_ascii=False)))


class AgenteGuion:
    """Cliente estilo Anthropic (async) que sigue el guion de una plantilla. Úsalo donde
    el runner acepta `client`: `CuaRunner(client=AgenteGuion("banca_movimientos"))`."""

    def __init__(self, plantilla: str):
        self.plantilla = plantilla
        self.beta = SimpleNamespace(messages=_MensajesGuion(plantilla))
