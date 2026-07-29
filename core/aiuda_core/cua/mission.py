"""Misiones CUA: integraciones con sistemas que no tienen API.

Un Computer Use Agent opera la interfaz como lo haría un humano (portal del
SAT, banca web, ERP legacy, portales de tribunales). aiuda lo trata como un
conector más, con tres reglas:

1. Declarativo: la misión dice QUÉ extraer/hacer, no cómo hacer clic.
2. Solo lectura por defecto: escribir en un sistema requiere opt-in explícito.
3. Evidencia siempre: capturas y bitácora de pasos — la procedencia de un dato
   extraído por CUA es verificable ("extraído del portal X, evidencia adjunta").
"""

from dataclasses import dataclass, field


@dataclass
class Mission:
    objetivo: str  # en lenguaje natural: "Descarga los CFDI recibidos del mes"
    sistema: str  # nombre del sistema: "Portal SAT", "BBVA empresas", "ERP interno"
    url_inicio: str
    datos_a_extraer: dict[str, str]  # campo -> descripción de qué buscar
    solo_lectura: bool = True
    max_pasos: int = 40
    notas: str = ""  # contexto del negocio: cómo navegar, qué ignorar


@dataclass
class MissionResult:
    success: bool
    data: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)  # rutas de capturas
    steps_log: list[str] = field(default_factory=list)
    error: str | None = None


def build_mission_prompt(mission: Mission) -> str:
    """El contrato que recibe el agente de cómputo. Determinista y auditable."""
    campos = "\n".join(f"- {campo}: {desc}" for campo, desc in mission.datos_a_extraer.items())
    escritura = (
        "Tienes permiso de capturar/registrar datos donde la misión lo indique."
        if not mission.solo_lectura
        else "MODO SOLO LECTURA: no llenes formularios, no envíes, no borres, no descargues "
        "ejecutables. Si una acción modificaría algo, detente y repórtalo."
    )
    notas = f"\nNotas del negocio:\n{mission.notas}\n" if mission.notas else ""
    return (
        f"Eres un asistente operando «{mission.sistema}» en nombre de un negocio mexicano.\n"
        f"Inicia en: {mission.url_inicio}\n\n"
        f"Objetivo: {mission.objetivo}\n\n"
        f"Datos a extraer:\n{campos}\n\n"
        f"{escritura}\n"
        f"{notas}\n"
        f"Al terminar, responde ÚNICAMENTE un objeto JSON con las llaves exactas de los "
        f"datos a extraer (usa null si algo no se encontró) y una llave extra "
        f'"_resumen" con lo que hiciste en una oración.'
    )
