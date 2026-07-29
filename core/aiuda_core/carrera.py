"""Plan de carrera de un ayudante: sube de nivel por trabajo REAL acumulado.

La señal NO es cosmética: las "acciones" se DERIVAN de filas reales cada vez que
se consultan (propuestas en la bandeja, enviadas; mensajes y promesas en el caso
de cobranza) — no hay un contador guardado que pueda inflarse o desfasarse.
Trabajar sube el nivel; borrar el trabajo lo baja. Quién cuenta las acciones:

  - Ayudantes del dueño: recordatorios/cotizaciones ATRIBUIDOS (meta.ayudante_id,
    lo estampa el motor al redactar) en pending_approval, approved o sent. Las
    rechazadas no dan carrera.
  - Agentes por rol (/v1/agents, home): conteos por slug (pendientes + enviados,
    más mensajes y promesas para cobranza).

Una sola fuente de verdad de los umbrales: el backend calcula el nivel y el
frontend solo lo pinta (nada de duplicar la escala en TypeScript).
"""

from __future__ import annotations

NIVELES: tuple[tuple[int, str], ...] = (
    (0, "Aprendiz"),
    (10, "Junior"),
    (50, "Senior"),
    (200, "Experto"),
)


def nivel_por_acciones(acciones: int) -> dict:
    """Nivel actual por acciones acumuladas, umbral del siguiente y progreso [0..1].

    `siguiente` es None en el nivel máximo (progreso 1.0)."""
    acciones = max(0, int(acciones))
    actual = NIVELES[0]
    siguiente: tuple[int, str] | None = None
    for i, nivel in enumerate(NIVELES):
        if acciones >= nivel[0]:
            actual = nivel
            siguiente = NIVELES[i + 1] if i + 1 < len(NIVELES) else None
    if siguiente is None:
        return {"nivel": actual[1], "siguiente": None, "progreso": 1.0}
    progreso = (acciones - actual[0]) / (siguiente[0] - actual[0])
    return {"nivel": actual[1], "siguiente": siguiente[0], "progreso": min(progreso, 1.0)}
