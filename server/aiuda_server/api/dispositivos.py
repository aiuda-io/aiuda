"""Emparejar teléfonos con esta computadora, de un escaneo.

El dueño abre su consola, prende la red local y aparece un QR. Quien lo escanee
en los próximos minutos queda dentro, con el papel que el dueño le puso. No hay
correo, ni contraseña, ni cuenta que crear: es el aparato el que queda
emparejado, y se saca de la lista igual de fácil.

El código del QR vive **en memoria** y a propósito: es de un solo uso, dura poco
y si aiuda se reinicia deja de valer. Un código de emparejamiento no es algo que
deba sobrevivir a nada.

Del token del aparato solo se guarda su huella. El token completo se dice UNA
vez, cuando el teléfono lo canjea.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from aiuda_core.models import Dispositivo, Tenant
from aiuda_server.api.deps import get_db, get_tenant

router = APIRouter()

VIGENCIA_CODIGO = timedelta(minutes=5)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def huella_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# El código que enseña el QR                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class _Invitacion:
    codigo: str
    papel: str
    tope: float | None
    caduca: datetime


_candado = threading.Lock()
_invitacion: _Invitacion | None = None


def _guardar_invitacion(papel: str, tope: float | None) -> _Invitacion:
    global _invitacion
    with _candado:
        _invitacion = _Invitacion(
            codigo=secrets.token_urlsafe(9),
            papel=papel,
            tope=tope,
            caduca=_ahora() + VIGENCIA_CODIGO,
        )
        return _invitacion


def _canjear(codigo: str) -> _Invitacion | None:
    """Un código sirve una sola vez. Se compara sin dar pistas por el tiempo que
    tarda la comparación."""
    global _invitacion
    with _candado:
        pendiente = _invitacion
        if pendiente is None or _ahora() > pendiente.caduca:
            _invitacion = None
            return None
        if not secrets.compare_digest(codigo, pendiente.codigo):
            return None
        _invitacion = None
        return pendiente


def _olvidar_invitacion() -> None:
    global _invitacion
    with _candado:
        _invitacion = None


# --------------------------------------------------------------------------- #
# Quién es el que llama                                                        #
# --------------------------------------------------------------------------- #
def dispositivo_de(request: Request, db) -> Dispositivo | None:
    """El aparato detrás de esta petición, si viene de uno.

    Vale tanto el encabezado (lo que usa la app del teléfono) como el token de
    sesión de la consola, que no es un aparato y devuelve None: quien entra desde
    la consola de la propia computadora ya es el dueño.
    """
    crudo = request.headers.get("authorization", "")
    if not crudo.lower().startswith("bearer "):
        return None
    token = crudo[7:].strip()
    if not token:
        return None
    aparato = db.scalars(
        select(Dispositivo).where(Dispositivo.token_hash == huella_token(token))
    ).first()
    if aparato is None or not aparato.activo:
        return None
    return aparato


# --------------------------------------------------------------------------- #
# Prender la red local                                                         #
# --------------------------------------------------------------------------- #
CLAVE_CONFIG = "red_local"


def _estado_red(request: Request, tenant: Tenant) -> dict:
    from aiuda_server import red_local

    estado = red_local.escucha.estado()
    estado["quiere_prendida"] = bool((tenant.config or {}).get(CLAVE_CONFIG))
    # macOS pregunta una vez si aiuda puede ver la red local. Si le dijeron que
    # no, todo esto se cae en silencio; aquí se dice, con a dónde ir a arreglarlo.
    permiso = red_local.permiso_concedido() if estado["prendida"] else None
    estado["permiso_del_sistema"] = permiso
    if permiso is False:
        estado["ajustes"] = red_local.AJUSTES_RED_LOCAL
    return estado


@router.get("/v1/red-local")
def ver_red(request: Request, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    _solo_el_dueno(request, db, "Solo el dueño ve el estado de la red.")
    return _estado_red(request, tenant)


class CambioRed(BaseModel):
    prendida: bool


@router.put("/v1/red-local")
def cambiar_red(
    cuerpo: CambioRed,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> dict:
    """El interruptor del dueño. Prendido, sus aparatos pueden llegarle a esta
    computadora; apagado, aiuda vuelve a hablar solo consigo mismo."""
    _solo_el_dueno(request, db, "Solo el dueño prende y apaga la red local.")

    from aiuda_server import red_local

    if cuerpo.prendida:
        if red_local.direccion_lan() is None:
            raise HTTPException(
                409,
                "Esta computadora no está en ninguna red. Conéctala al WiFi de tu "
                "negocio y vuelve a intentar.",
            )
        red_local.escucha.prender(request.app)
    else:
        red_local.escucha.apagar(request.app)
        _olvidar_invitacion()

    tenant.config = {**(tenant.config or {}), CLAVE_CONFIG: cuerpo.prendida}
    db.add(tenant)
    db.flush()
    return _estado_red(request, tenant)


# --------------------------------------------------------------------------- #
# Lo que ve el dueño                                                           #
# --------------------------------------------------------------------------- #
def _solo_el_dueno(request: Request, db, mensaje: str) -> None:
    """La consola de esta computadora siempre es el dueño. Un aparato, solo si lo es."""
    quien = dispositivo_de(request, db)
    if quien is not None and quien.papel != "dueno":
        raise HTTPException(403, mensaje)


def _payload(d: Dispositivo) -> dict:
    return {
        "id": d.id,
        "nombre": d.nombre,
        "papel": d.papel,
        "tope_aprobacion": float(d.tope_aprobacion) if d.tope_aprobacion is not None else None,
        "activo": d.activo,
        "ultimo_visto": d.ultimo_visto.isoformat() if d.ultimo_visto else None,
        "revocado_en": d.revocado_en.isoformat() if d.revocado_en else None,
        "creado": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/v1/dispositivos")
def listar(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    aparatos = db.scalars(
        select(Dispositivo)
        .where(Dispositivo.tenant_id == tenant.id)
        .order_by(Dispositivo.created_at)
    ).all()
    return {"dispositivos": [_payload(d) for d in aparatos]}


class NuevaInvitacion(BaseModel):
    papel: str = Field(default="invitado", pattern="^(dueno|invitado)$")
    # Hasta cuánto puede aprobar solo. Vacío = ve y propone, pero no aprueba.
    tope_aprobacion: float | None = Field(default=None, ge=0)


@router.post("/v1/dispositivos/invitacion")
def crear_invitacion(
    cuerpo: NuevaInvitacion,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> dict:
    """El QR que va a escanear el teléfono. Dura cinco minutos y sirve una vez.

    Solo el dueño invita: un invitado no puede meter a nadie más, ni siquiera con
    un papel más chico que el suyo.
    """
    _solo_el_dueno(request, db, "Solo el dueño puede invitar a otro aparato.")

    from aiuda_server import red_local

    invitacion = _guardar_invitacion(cuerpo.papel, cuerpo.tope_aprobacion)
    cert = red_local.certificado()
    ip = red_local.direccion_lan()
    puerto = getattr(request.app.state, "puerto_red_local", None)

    if ip is None or puerto is None:
        _olvidar_invitacion()
        raise HTTPException(
            409,
            "Primero prende la red local: tus aparatos todavía no pueden ver esta "
            "computadora.",
        )

    # Lo que lee el teléfono. Va la huella del certificado: así el teléfono acepta
    # a ESTA computadora y a ninguna otra, aunque alguien se ponga en medio.
    contenido = {
        "v": 1,
        "host": ip,
        "puerto": puerto,
        "huella": cert.huella,
        "codigo": invitacion.codigo,
        "negocio": tenant.name,
    }
    return {
        "qr": contenido,
        "qr_svg": _svg(_enlace(contenido)),
        "caduca_en": int(VIGENCIA_CODIGO.total_seconds()),
        "papel": invitacion.papel,
        "tope_aprobacion": invitacion.tope,
    }


def _enlace(contenido: dict) -> str:
    """Lo que de verdad se dibuja en el QR.

    Un enlace y no un JSON: cabe en menos cuadritos (o sea, se lee de más lejos y
    con peor luz), y la cámara del iPhone lo reconoce como algo que se abre, así
    que la app se levanta sola sin que nadie explique nada.
    """
    from urllib.parse import urlencode

    datos = urlencode(
        {
            "h": contenido["host"],
            "p": contenido["puerto"],
            "f": contenido["huella"],
            "c": contenido["codigo"],
            "n": contenido["negocio"],
        }
    )
    return f"aiuda://emparejar?{datos}"


def _svg(texto: str) -> str:
    import segno

    return segno.make(texto, error="m").svg_data_uri(scale=6, border=2)


@router.delete("/v1/dispositivos/invitacion")
def cancelar_invitacion(request: Request, db=Depends(get_db)) -> dict:
    """El dueño cerró la pantalla del QR: el código deja de servir ya."""
    _solo_el_dueno(request, db, "Solo el dueño cancela una invitación.")
    _olvidar_invitacion()
    return {"cancelada": True}


class Emparejar(BaseModel):
    codigo: str = Field(min_length=1, max_length=64)
    nombre: str = Field(min_length=1, max_length=80)


@router.post("/v1/emparejar")
def emparejar(
    cuerpo: Emparejar, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
) -> dict:
    """Lo llama el teléfono, con el código que acaba de leer del QR.

    Es el único camino que no pide el token de la sesión: el teléfono todavía no
    tiene ninguno. Lo que lo protege es el código, que dura cinco minutos, sirve
    una vez y solo lo pudo ver quien tuvo la pantalla del dueño enfrente.
    """
    invitacion = _canjear(cuerpo.codigo)
    if invitacion is None:
        raise HTTPException(
            403, "Ese código ya no sirve. Pídele a tu computadora que enseñe uno nuevo."
        )

    token = secrets.token_urlsafe(32)
    aparato = Dispositivo(
        tenant_id=tenant.id,
        nombre=cuerpo.nombre.strip(),
        papel=invitacion.papel,
        tope_aprobacion=invitacion.tope,
        token_hash=huella_token(token),
        ultimo_visto=_ahora(),
    )
    db.add(aparato)
    db.flush()
    # El token completo se dice aquí y nunca más: de él solo queda la huella.
    return {"token": token, "dispositivo": _payload(aparato), "negocio": tenant.name}


class CambioDispositivo(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    papel: str | None = Field(default=None, pattern="^(dueno|invitado)$")
    tope_aprobacion: float | None = Field(default=None, ge=0)


@router.patch("/v1/dispositivos/{dispositivo_id}")
def cambiar(
    dispositivo_id: str,
    cuerpo: CambioDispositivo,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> dict:
    _solo_el_dueno(request, db, "Solo el dueño cambia los papeles.")
    aparato = db.get(Dispositivo, dispositivo_id)
    if aparato is None or aparato.tenant_id != tenant.id:
        raise HTTPException(404, "Ese aparato no está en tu lista.")
    if cuerpo.nombre is not None:
        aparato.nombre = cuerpo.nombre.strip()
    if cuerpo.papel is not None:
        aparato.papel = cuerpo.papel
    if cuerpo.tope_aprobacion is not None:
        aparato.tope_aprobacion = cuerpo.tope_aprobacion
    db.flush()
    return _payload(aparato)


@router.post("/v1/dispositivos/{dispositivo_id}/revocar")
def revocar(
    dispositivo_id: str,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
) -> dict:
    """Sacar un aparato. No se borra la fila: el dueño merece poder ver que ese
    teléfono estuvo dentro y cuándo salió."""
    quien = dispositivo_de(request, db)
    if quien is not None and quien.papel != "dueno":
        raise HTTPException(403, "Solo el dueño saca aparatos.")
    aparato = db.get(Dispositivo, dispositivo_id)
    if aparato is None or aparato.tenant_id != tenant.id:
        raise HTTPException(404, "Ese aparato no está en tu lista.")
    if quien is not None and quien.id == aparato.id:
        raise HTTPException(400, "No te puedes sacar a ti mismo desde este aparato.")
    if aparato.activo:
        aparato.revocado_en = _ahora()
        db.flush()
    return _payload(aparato)


@router.get("/v1/dispositivos/yo")
def quien_soy(request: Request, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)) -> dict:
    """Lo primero que pregunta la app del teléfono al abrir: si sigue dentro y
    qué puede hacer. Si la revocaron, se entera aquí."""
    aparato = dispositivo_de(request, db)
    if aparato is None:
        raise HTTPException(401, "Este aparato ya no está emparejado.")
    aparato.ultimo_visto = _ahora()
    db.flush()
    return {"dispositivo": _payload(aparato), "negocio": tenant.name}
