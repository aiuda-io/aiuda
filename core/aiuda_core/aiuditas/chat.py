"""Chat de un ayudante, capability-first.

No hay "agente Mariana": el ayudante que el dueño creó habla usando exactamente las
aiuditas que le activó. Sus herramientas, su ejecutor y su persona se ARMAN desde esas
aiuditas. Regla dura: el chat es SOLO LECTURA (consultar/buscar); las escrituras viven
en los flujos con aprobación humana, nunca en el chat.

Este módulo se importa bajo demanda (no desde aiuditas/__init__), porque trae los
ejecutores de cada perfil — así importar el catálogo no arrastra el motor.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from aiuda_core.agents.base import ToolExecutor
from aiuda_core.agents.carlos.tools import CARLOS_TOOLS, CarlosToolExecutor
from aiuda_core.agents.cleo.tools import CLEO_CHAT_TOOLS, CleoToolExecutor
from aiuda_core.agents.diego.tools import DIEGO_TOOLS, DiegoToolExecutor
from aiuda_core.agents.valeria.tools import VALERIA_TOOLS, ValeriaToolExecutor
from aiuda_core.aiuditas.catalog import aiudita_por_id
from aiuda_core.models import Tenant


def _schema(tools: list[dict], name: str) -> dict:
    return next(t for t in tools if t["name"] == name)


# aiudita_id -> (schema del tool, clase ejecutora del perfil). Solo aiuditas de chat:
# de SOLO LECTURA y con ejecutor real. Las escrituras (redactar/enviar/registrar) NO
# están aquí a propósito.
CHAT_AIUDITAS: dict[str, tuple[dict, type[ToolExecutor]]] = {
    "cobranza.consultar_cartera": (_schema(CLEO_CHAT_TOOLS, "consultar_cartera"), CleoToolExecutor),
    "ventas.consultar_catalogo": (_schema(CARLOS_TOOLS, "consultar_catalogo"), CarlosToolExecutor),
    "ventas.consultar_cliente": (_schema(CARLOS_TOOLS, "consultar_cliente"), CarlosToolExecutor),
    "recepcion.consultar_agenda": (_schema(VALERIA_TOOLS, "consultar_agenda"), ValeriaToolExecutor),
    "recepcion.buscar_cita": (_schema(VALERIA_TOOLS, "buscar_cita"), ValeriaToolExecutor),
    "conciliacion.consultar_pagos": (_schema(DIEGO_TOOLS, "consultar_pagos"), DiegoToolExecutor),
}


def chat_tools(aiudita_ids) -> list[dict]:
    """Schemas de las herramientas de chat de un ayudante (las de lectura que tiene activas)."""
    return [CHAT_AIUDITAS[a][0] for a in aiudita_ids if a in CHAT_AIUDITAS]


# Puente para chatear/consultar por rol o plantilla (no es un ayudante que el dueño creó):
# mapea slugs de persona internos legacy al perfil de capacidades. Ya no existe la ruta
# /asistentes; el mapa sobrevive para las vistas que aún piden un rol por ese slug.
PERSONA_PERFIL = {
    "mariana": "cobranza",
    "carlos": "ventas",
    "valeria": "recepcion",
    "diego": "conciliacion",
}


def chat_aiuditas_de_perfil(perfil: str) -> list[str]:
    """Las aiuditas de chat (lectura) de un perfil — para chatear con un rol sin ayudante."""
    return [aid for aid in CHAT_AIUDITAS if aid.split(".")[0] == perfil]


class AyudanteChatExecutor:
    """Despacha cada tool al ejecutor del perfil que lo provee. Tenant obligatorio
    (un ayudante jamás ve datos de otro negocio). Solo herramientas de lectura."""

    def __init__(
        self,
        session: Session,
        tenant: Tenant,
        aiudita_ids,
        today: date | None = None,
        caller_phone: str | None = None,
    ):
        """``caller_phone`` acota las consultas al cliente que está del otro lado cuando
        el interlocutor NO es el dueño (un deudor por WhatsApp). Lo aplica cada
        ToolExecutor; aquí solo se transporta."""
        self._dispatch: dict[str, ToolExecutor] = {}
        instancias: dict[type[ToolExecutor], ToolExecutor] = {}
        for aid in aiudita_ids:
            entry = CHAT_AIUDITAS.get(aid)
            if entry is None:
                continue
            schema, cls = entry
            if cls not in instancias:
                instancias[cls] = cls(session, tenant, today=today, caller_phone=caller_phone)
            self._dispatch[schema["name"]] = instancias[cls]

    @property
    def has_tools(self) -> bool:
        return bool(self._dispatch)

    def __call__(self, name: str, args: dict) -> str:
        ex = self._dispatch.get(name)
        if ex is None:
            raise ValueError(f"Tool no disponible para este ayudante: {name}")
        return ex(name, args)


def chat_system_prompt(
    ayudante_name: str,
    business_name: str,
    aiuditas: dict[str, dict],
    instructions: str | None = None,
) -> str:
    """Persona del ayudante derivada de sus aiuditas activas (+ las reglas que el dueño
    escribió en cada una + sus instrucciones libres). Las instrucciones del dueño se
    inyectan DEBAJO de la base de seguridad: agregan, nunca la contradicen."""
    specs = [(aiudita_por_id(aid), cfg) for aid, cfg in aiuditas.items()]
    specs = [(s, cfg) for s, cfg in specs if s is not None]

    base = (
        f'Eres {ayudante_name}, un ayudante de IA del negocio "{business_name}". Hablas con el '
        "dueño o su equipo (no con un cliente). Responde en español de México, breve, cálido y "
        "concreto. Regla inquebrantable: nunca envías mensajes a clientes por tu cuenta; tú "
        "propones y el humano aprueba. No inventes cifras, folios ni fechas: usa tus herramientas "
        "para consultarlos, y si no tienes el dato, dilo y di dónde se consultaría. "
        "Escribe SIEMPRE en texto plano: prohibido emojis y prohibido markdown."
    )
    if instructions and instructions.strip():
        base += (
            "\n\nInstrucciones del dueño (definen tu tono y foco; nunca contradicen las reglas "
            f"inquebrantables de arriba):\n{instructions.strip()}"
        )
    if specs:
        que_hace = "\n".join(f"- {s.label}: {s.linea}" for s, _ in specs)
        base += f"\n\nEsto es lo que sabes hacer:\n{que_hace}"
    reglas = [
        f"- {s.label}: {cfg['reglas'].strip()}"
        for s, cfg in specs
        if s.reglas_libres and isinstance(cfg.get("reglas"), str) and cfg["reglas"].strip()
    ]
    if reglas:
        base += "\n\nReglas que te puso el dueño (respétalas siempre):\n" + "\n".join(reglas)
    return base
