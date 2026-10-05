"""Canal WhatsApp del tenant: instalar y emparejar wacli por QR, activar la vía
oficial y recibir el webhook de la Cloud API.

wacli: el proceso de emparejamiento (`wacli auth`) y el de sincronización
(`wacli sync --follow`) son del supervisor ``aiuda_server.wacli_sync``; aquí solo
se le pide empezar, cancelar o cerrar, y se le pregunta el estado EN VIVO. El QR
vigente (wacli lo rota) se convierte a imagen (segno) para la consola. Con
WACLI_STORE_ROOT cada tenant empareja SU PROPIO store (`--store`), así la
sesión/número de un negocio nunca es la de otro; sin la raíz (un solo número) el
store default solo puede pertenecer a UN tenant: el segundo que intente recibe
un rechazo honesto, no el número ajeno.

Cloud API (producción): las credenciales se capturan cifradas en el conector
`whatsapp_cloud`; aquí solo se ACTIVA como vía del canal y se recibe su webhook
(verificación GET + mensajes POST firmados con el app secret)."""

import hashlib
import hmac
import json

import segno
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select as sa_select

from aiuda_server import wacli_sync
from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.config import settings
from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.channel import wacli_store_dir, whatsapp_config
from aiuda_core.connectors.wacli import explicar_fallo_wacli
from aiuda_core.connectors.waba import parse_webhook as parse_waba_webhook
from aiuda_core.models import Conversation, IntegrationCredential, Message, Tenant

router = APIRouter()


def _mark(tenant: Tenant, db, via: str | None) -> None:
    """Fija (o borra, con via=None) la conexión del canal en tenant.config. La
    instancia queda explícita: es la que el poller de entrada manda al webhook."""
    cfg = dict(tenant.config or {})
    integrations = dict(cfg.get("integrations") or {})
    if via:
        integrations["whatsapp"] = {"via": via, "instance": tenant.evolution_instance}
    else:
        integrations.pop("whatsapp", None)
    cfg["integrations"] = integrations
    tenant.config = cfg
    db.add(tenant)
    db.flush()


def _duena_del_store_default(db, tenant: Tenant) -> Tenant | None:
    """En modo mono (sin WACLI_STORE_ROOT) el store default es UNO: si otro negocio
    ya lo tiene conectado por wacli, este tenant no puede emparejarlo también."""
    if wacli_store_dir(tenant.evolution_instance):
        return None  # multi-store: cada quien el suyo, no hay conflicto
    otros = db.scalars(sa_select(Tenant).where(Tenant.id != tenant.id)).all()
    for t in otros:
        wa = whatsapp_config(t)
        if wa and (wa.get("via") or settings.whatsapp_provider) == "wacli":
            return t
    return None


def _qr_imagen(code: str | None) -> str | None:
    return segno.make(code, error="m").svg_data_uri(scale=6, border=2) if code else None


def _estado_vivo(tenant: Tenant, db) -> dict:
    """El estado del WhatsApp del negocio tal como está AHORA en wacli, no como
    quedó guardado. Si la sesión está vinculada y el store es suyo, se anota la
    vía y se deja corriendo el sync (por si se vinculó fuera de la consola)."""
    instance = tenant.evolution_instance
    store = wacli_store_dir(instance)
    foto = wacli_sync.estado(instance, store)
    vinculado = foto["estado"] in wacli_sync.VINCULADOS
    if vinculado:
        # No robar el store default: solo es suyo si nadie más lo posee.
        if _duena_del_store_default(db, tenant) is None:
            if (whatsapp_config(tenant) or {}).get("via") != "wacli":
                _mark(tenant, db, "wacli")
            foto["estado"] = wacli_sync.arrancar(instance, store)
        else:
            vinculado = False
    return {
        "connected": vinculado,
        "estado": foto["estado"],
        "desde": foto["desde"],
        "telefono": foto["telefono"] if vinculado else None,
        "qr": _qr_imagen(foto["qr"]),
        # Lo último que falló, ya en español (el QR caducó, no hay internet...).
        "aviso": (
            explicar_fallo_wacli(foto["error"])
            if foto["error"] and foto["estado"] in (wacli_sync.SIN_VINCULAR, wacli_sync.SIN_CONEXION)
            else None
        ),
        **_instalacion(),
    }


@router.post("/v1/integrations/whatsapp/qr")
def whatsapp_qr(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Devuelve el QR para emparejar (o avisa si ya está conectado)."""
    dueno = _duena_del_store_default(db, tenant)
    if dueno is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "El WhatsApp de esta computadora ya está vinculado a otro negocio. "
                "Cada negocio necesita su propio número."
            ),
        )
    if wacli_bin.resolver() is None:
        raise HTTPException(status_code=409, detail=wacli_bin.SIN_INSTALAR)
    if _estado_vivo(tenant, db)["connected"]:
        return {"connected": True, "qr": None}

    instance = tenant.evolution_instance
    store = wacli_store_dir(instance)
    code = wacli_sync.vincular(instance, store)
    if not code:
        error = wacli_sync.estado(instance, store)["error"]
        raise HTTPException(
            status_code=502,
            detail=(
                explicar_fallo_wacli(error)
                if error
                else "No se pudo generar el código QR. Intenta de nuevo en un momento."
            ),
        )
    return {"connected": False, "qr": _qr_imagen(code)}


@router.delete("/v1/integrations/whatsapp/qr")
def whatsapp_qr_cancelar(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """El dueño cerró la ventana sin escanear: el emparejamiento se cancela para
    que no se quede ocupando el WhatsApp de esta computadora. Si alcanzó a
    escanear, no se cancela nada y el negocio queda anotado como vinculado."""
    wacli_sync.cancelar_vinculacion(tenant.evolution_instance)
    return {"connected": _estado_vivo(tenant, db)["connected"]}


@router.get("/v1/integrations/whatsapp/status")
def whatsapp_status(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    return _estado_vivo(tenant, db)


def _instalacion() -> dict:
    """Lo que la consola necesita para ofrecer Instalar: si ya hay un wacli, cuál
    versión, y si esta computadora no puede instalarlo, por qué."""
    binario = wacli_bin.resolver()
    return {
        "instalado": binario is not None,
        "version": wacli_bin.version(binario) if binario else None,
        # La que instala este aiuda. Si ya es la instalada, "Actualizar" no
        # serviría de nada y la consola no lo ofrece.
        "version_fijada": wacli_bin.WACLI_VERSION,
        "no_se_puede": None if binario else wacli_bin.puede_instalarse(),
    }


@router.post("/v1/integrations/whatsapp/instalar")
def whatsapp_instalar():
    """Instala el conector de WhatsApp con un clic: lo baja del release oficial,
    verifica su suma y lo deja en la carpeta de datos. Nada que teclear."""
    try:
        wacli_bin.instalar()
    except wacli_bin.WacliInstallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    wacli_sync.tras_instalar()
    return _instalacion()


@router.delete("/v1/integrations/whatsapp/session")
def whatsapp_logout(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Desvincula el número. Si wacli no pudo cerrar la sesión se dice, y el
    negocio sigue marcado como vinculado: decir "desconectado" con la sesión
    viva sería mentir."""
    instance = tenant.evolution_instance
    store = wacli_store_dir(instance)
    error = wacli_sync.desvincular(instance, store)
    if error is not None:
        wacli_sync.arrancar(instance, store)  # sigue vinculado: el sync vuelve
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo cerrar la sesión de WhatsApp. Revisa tu internet e intenta "
                "de nuevo; también puedes quitarla desde tu teléfono, en Dispositivos "
                "vinculados."
            ),
        )
    _mark(tenant, db, None)
    return {"connected": False}


# --- Vía oficial (Cloud API): activar como canal del negocio -----------------


@router.post("/v1/integrations/whatsapp-cloud/activate")
def activate_whatsapp_cloud(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Convierte la Cloud API en LA vía del canal WhatsApp del negocio. Requiere
    credenciales ya capturadas (cifradas). El envío usa plantillas aprobadas fuera
    de la ventana de 24 h; el estado sigue 'pendiente de verificar en vivo' hasta
    que la prueba de conexión pase contra Meta."""
    from aiuda_core.connectors.credentials import get_credential

    creds = get_credential(db, tenant.id, "whatsapp_cloud")
    if not creds or not creds.get("access_token") or not creds.get("phone_number_id"):
        raise HTTPException(
            status_code=409,
            detail="Primero captura las credenciales de WhatsApp Business (token y número).",
        )
    _mark(tenant, db, "whatsapp_cloud")
    return {"via": "whatsapp_cloud", "instance": tenant.evolution_instance}


# --- Webhook de la Cloud API (Meta) ------------------------------------------


def _tenant_por_phone_number_id(db, phone_number_id: str) -> Tenant | None:
    """El tenant dueño del número oficial. El phone_number_id vive en el
    public_config de la credencial (no es secreto): se rutea SIN descifrar nada."""
    rows = db.scalars(
        sa_select(IntegrationCredential).where(
            IntegrationCredential.provider == "whatsapp_cloud",
            IntegrationCredential.status != "disabled",
        )
    ).all()
    for row in rows:
        if (row.public_config or {}).get("phone_number_id") == phone_number_id:
            return db.get(Tenant, row.tenant_id)
    return None


@router.get("/v1/webhooks/whatsapp-cloud")
def waba_verify(
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    """Verificación del webhook (la hace Meta al registrarlo): responde el
    challenge solo si el verify token coincide con el configurado."""
    if (
        settings.waba_verify_token
        and mode == "subscribe"
        and token == settings.waba_verify_token
    ):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verify token inválido")


def _firma_valida(raw: bytes, header: str) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app_secret, cuerpo crudo)."""
    if not settings.waba_app_secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.waba_app_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


@router.post("/v1/webhooks/whatsapp-cloud")
async def waba_webhook(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    """Mensajes entrantes del canal oficial. Cada mensaje se rutea al tenant DUEÑO
    del número que lo recibió (metadata.phone_number_id → credencial del tenant);
    la firma del app secret es obligatoria (sin ella no se acepta ningún evento)."""
    raw = await request.body()
    if not _firma_valida(raw, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=403, detail="Firma del webhook inválida")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"status": "ignored"}

    accepted = 0
    for incoming in parse_waba_webhook(payload):
        tenant = _tenant_por_phone_number_id(db, incoming.phone_number_id)
        if tenant is None:
            continue  # número sin negocio en aiuda: no es nuestro
        conversation = db.scalar(
            sa_select(Conversation).where(
                Conversation.tenant_id == tenant.id,
                Conversation.remote_phone == incoming.remote_phone,
            )
        )
        if conversation is None:
            conversation = Conversation(
                tenant_id=tenant.id, remote_phone=incoming.remote_phone
            )
            db.add(conversation)
            db.flush()
        if incoming.wa_message_id:
            duplicate = db.scalar(
                sa_select(Message).where(
                    Message.tenant_id == tenant.id,
                    Message.wa_message_id == incoming.wa_message_id,
                )
            )
            if duplicate is not None:
                continue  # Meta reintenta si no respondemos <5s
        message = Message(
            tenant_id=tenant.id,
            conversation_id=conversation.id,
            direction="in",
            body=incoming.body,
            wa_message_id=incoming.wa_message_id or None,
        )
        db.add(message)
        db.flush()
        from aiuda_server.worker.main import process_incoming_message_blocking

        background.add_task(process_incoming_message_blocking, tenant.id, message.id)
        accepted += 1
    return {"status": "accepted" if accepted else "ignored", "messages": accepted}
