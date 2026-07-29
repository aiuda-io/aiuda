"""Catálogo de aiuditas: la fuente de verdad capability-first de aiuda.

Un agente del usuario = nombre + apariencia + sus aiuditas, cada una con su config.
El motor arma el ejecutor desde las aiuditas activas; ya no hay ejecutor por persona.
"""

from aiuda_core.aiuditas.catalog import (
    AIUDITAS,
    PERFILES,
    Aiudita,
    Opcion,
    Perfil,
    Perilla,
    PerillaTipo,
    aiudita_por_id,
    aiuditas_de_perfil,
    catalog_payload,
    config_default,
    validar_config,
)

__all__ = [
    "AIUDITAS",
    "PERFILES",
    "Aiudita",
    "Opcion",
    "Perfil",
    "Perilla",
    "PerillaTipo",
    "aiudita_por_id",
    "aiuditas_de_perfil",
    "catalog_payload",
    "config_default",
    "validar_config",
]
