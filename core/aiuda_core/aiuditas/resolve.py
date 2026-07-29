"""Resuelve la config efectiva de una aiudita para un tenant.

La cobranza corre a nivel tenant (una cartera por negocio), pero la config vive
por-ayudante. Sin un ayudante explícito, gobierna el PRIMERO (por antigüedad) que
tenga la aiudita activa — y a él se le atribuye el trabajo que esa config produce.
Si nadie la tiene, el motor cae a su comportamiento previo sin romper nada.

Para correr COMO un ayudante concreto (corrida manual desde su ficha), el motor usa
`config_de(ayudante, ...)`: sus perillas e instrucciones, no las del primero.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.aiuditas.catalog import aiudita_por_id, config_default
from aiuda_core.models import Ayudante, Tenant


def _ayudantes(session: Session, tenant: Tenant) -> list[Ayudante]:
    return session.scalars(
        select(Ayudante)
        .where(Ayudante.tenant_id == tenant.id)
        .order_by(Ayudante.created_at)
    ).all()


def ayudante_con_aiudita(session: Session, tenant: Tenant, aiudita_id: str) -> Ayudante | None:
    """El ayudante que GOBIERNA esta aiudita a nivel tenant: el más antiguo que la
    tiene activa (su config es la que corre). None si ningún ayudante la tiene."""
    for a in _ayudantes(session, tenant):
        if (a.aiuditas or {}).get(aiudita_id) is not None:
            return a
    return None


def config_de(ayudante: Ayudante, aiudita_id: str) -> dict | None:
    """Config efectiva de una aiudita DE ESTE ayudante, con los defaults rellenados
    (por si el esquema ganó perillas nuevas). None si no la tiene activa."""
    spec = aiudita_por_id(aiudita_id)
    if spec is None:
        return None
    cfg = (ayudante.aiuditas or {}).get(aiudita_id)
    if cfg is None:
        return None
    return {**config_default(spec), **cfg}


def config_or_none(session: Session, tenant: Tenant, aiudita_id: str) -> dict | None:
    a = ayudante_con_aiudita(session, tenant, aiudita_id)
    return config_de(a, aiudita_id) if a is not None else None


def instructions_or_none(session: Session, tenant: Tenant, prefix: str = "") -> str | None:
    """Instrucciones libres del primer ayudante (por antigüedad) que tenga una aiudita del
    prefijo dado (p.ej. "cobranza."). Sin prefijo, el primero con instrucciones. Devuelve
    None si nadie las tiene — el motor cae a su comportamiento previo sin romper nada."""
    for a in _ayudantes(session, tenant):
        if prefix and not any(str(aid).startswith(prefix) for aid in (a.aiuditas or {})):
            continue
        if a.instructions and a.instructions.strip():
            return a.instructions.strip()
    return None
