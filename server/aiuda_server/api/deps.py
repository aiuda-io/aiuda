"""Dependencias compartidas del API local: sesión de BD y el workspace único.

aiuda corre en la computadora del dueño. No hay cuentas, logins ni
multi-tenancy: hay UN workspace (una fila ``Tenant``) que se crea solo en el
primer arranque. ``get_tenant``, ``get_principal`` y ``require_role`` conservan
su firma para no tocar los ~50 endpoints que dependen de ellas — y para que el
modo multi-usuario (LAN u operado por un tercero) pueda reintroducir roles sin
re-cablear los routers. El aislamiento de red vive aparte: el API escucha solo
en 127.0.0.1 con token de sesión por arranque.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from aiuda_core.config import settings
from aiuda_core.db import get_sessionmaker
from aiuda_core.models import Tenant
from aiuda_core.models.base import new_id


def get_db():
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass
class Principal:
    """Quién hace la petición: la consola de esta computadora, o un aparato
    emparejado (el teléfono del dueño, o el de alguien de su equipo)."""

    tenant: Tenant
    role: str = "owner"  # owner | admin | collaborator (rango para el modo multi-usuario)
    source: str = "local"  # local | aparato
    email: str | None = None
    user: object | None = None  # compat con audit.record (no hay tabla de usuarios en local)
    # El aparato que hizo la petición, si vino de uno. Sin esto la bitácora diría
    # que el dueño aprobó lo que aprobó el teléfono de alguien más, que es
    # justamente lo que la bitácora existe para poder demostrar.
    dispositivo_id: str | None = None
    dispositivo_nombre: str | None = None

    @property
    def quien(self) -> str:
        """Para la bitácora, en palabras: 'esta computadora' o el nombre del aparato."""
        return self.dispositivo_nombre or "esta computadora"

    def puede_aprobar(self, monto: float | None = None) -> bool:
        """Desde la consola de la propia computadora se aprueba todo. Desde un
        aparato, manda su papel y su tope."""
        if self.dispositivo_id is None:
            return True
        return bool(self._dispositivo and self._dispositivo.puede_aprobar(monto))

    _dispositivo: object | None = None


ROLE_RANK = {"collaborator": 1, "admin": 2, "owner": 3}

DEFAULT_WORKSPACE_NAME = "Mi negocio"

# El primer arranque recibe varias peticiones a la vez (la consola pide su
# estado, el resumen y el catálogo casi al mismo tiempo). Sin este candado cada
# una veía la base vacía y creaba SU propio workspace: el dueño terminaba con
# cinco negocios fantasma y datos repartidos entre ellos.
_alta_workspace = threading.Lock()


def get_workspace(db) -> Tenant:
    """El workspace local. Si una base importada trae varios, manda
    ``settings.workspace_id``; si no, el más antiguo. Si no existe ninguno, se
    crea UNA sola vez."""
    if getattr(settings, "workspace_id", ""):
        chosen = db.get(Tenant, settings.workspace_id)
        if chosen is not None:
            return chosen
    existente = db.scalars(select(Tenant).order_by(Tenant.created_at)).first()
    if existente is not None:
        return existente
    with _alta_workspace:
        # Otra petición pudo crearlo mientras esperábamos el candado. Se cierra
        # la transacción de lectura que esta sesión ya traía: si no, la
        # re-consulta puede contestar con la foto de antes de esperar (y el
        # dueño termina con dos negocios). Aquí no hay nada escrito que perder:
        # el workspace se resuelve antes de tocar nada.
        db.rollback()
        db.expire_all()
        existente = db.scalars(select(Tenant).order_by(Tenant.created_at)).first()
        if existente is not None:
            return existente
        tenant = Tenant(
            name=DEFAULT_WORKSPACE_NAME,
            owner_phone="",
            evolution_instance=new_id(),
        )
        db.add(tenant)
        db.flush()
        db.commit()  # visible de inmediato para las demás peticiones
        return tenant


def get_principal(request: Request, db=Depends(get_db)) -> Principal:
    tenant = get_workspace(db)
    # El guardián ya resolvió el aparato (y ya decidió si podía entrar). Aquí solo
    # se le pone nombre y apellido a quien está pidiendo, para la bitácora.
    aparato = request.scope.get("aiuda_aparato")
    if aparato is None:
        return Principal(tenant=tenant)
    return Principal(
        tenant=tenant,
        role="owner" if aparato.papel == "dueno" else "collaborator",
        source="aparato",
        dispositivo_id=aparato.id,
        dispositivo_nombre=aparato.nombre,
        _dispositivo=aparato,
    )


def get_tenant(principal: Principal = Depends(get_principal)) -> Tenant:
    """Compat: la mayoría de endpoints solo necesitan el workspace resuelto."""
    return principal.tenant


def solo_el_dueno(principal: Principal = Depends(get_principal)) -> Principal:
    """Declaración por endpoint: esta acción es del dueño (la consola de esta
    computadora, o su propio aparato emparejado como dueño).

    Hablar en nombre del negocio con un cliente (mensajes, adjuntos) o tocar sus
    bajas (opt-out) no es "trabajo del día" de un invitado: sin esto, cualquier
    teléfono invitado del WiFi le escribía a los clientes reales sin tope ni
    rastro."""
    if ROLE_RANK.get(principal.role, 0) < ROLE_RANK["owner"]:
        raise HTTPException(
            status_code=403,
            detail="Solo el dueño puede hacer esto. Pídeselo al dueño.",
        )
    return principal


def require_role(min_role: str):
    """El rango del principal debe alcanzar el mínimo declarado, de verdad.

    Era un no-op ("en local el dueño lo es todo") y dejó de ser cierto cuando
    entraron los aparatos: un invitado emparejado llegaba a 15 endpoints que se
    creían protegidos (la bitácora, el link de cobro). La consola local y el
    aparato del dueño son owner; un invitado es collaborator y aquí se queda."""
    if min_role not in ROLE_RANK:
        raise ValueError(f"rol desconocido: {min_role}")

    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if ROLE_RANK.get(principal.role, 0) < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=403,
                detail="Tu aparato no tiene permiso para esto. Pídeselo al dueño.",
            )
        return principal

    return _dep
