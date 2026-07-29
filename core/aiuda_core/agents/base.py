"""Cimientos del motor de aiudantes.

Hoy Cleo (Mariana) era el único agente con herramientas de verdad. Esto generaliza
ese patrón para que CUALQUIER aiudante sea real declarando, no programando a la medida:
una persona, una lista de herramientas y un ejecutor con tenant obligatorio.

Principio: las herramientas de CHAT son de SOLO LECTURA (consultar/buscar). Las
escrituras viven en los flujos con aprobación humana (cobranza por WhatsApp), nunca
en el chat. Así un aiudante deja de ser de cartón sin abrir riesgo: aterriza sus
respuestas en datos reales del negocio, pero no actúa por su cuenta.
"""

from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy.orm import Session

from aiuda_core.models import Tenant

# Un ejecutor de herramientas: recibe (nombre, args) y devuelve texto para el modelo.
ToolFn = Callable[[str, dict], str]


class ToolExecutor:
    """Despacha cada tool a un método `_<nombre>`. El tenant es obligatorio en toda
    query — un aiudante jamás ve datos de otro negocio."""

    def __init__(
        self,
        session: Session,
        tenant: Tenant,
        today: date | None = None,
        caller_phone: str | None = None,
    ):
        self.session = session
        self.tenant = tenant
        self.today = today or datetime.now().date()
        # Teléfono del interlocutor cuando el input es NO confiable (loop con el
        # deudor por WhatsApp). Si está definido, los tools se atan a ese cliente:
        # un deudor no puede consultar ni tocar facturas de otros. None en el chat
        # del dueño (acceso a toda la cartera, ya autenticado).
        self.caller_phone = caller_phone

    def __call__(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            raise ValueError(f"Tool desconocido: {name}")
        return handler(**args)
