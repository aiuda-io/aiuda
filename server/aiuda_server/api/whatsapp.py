"""Canal WhatsApp del tenant: emparejar wacli por QR, activar la vía oficial y
recibir el webhook de la Cloud API.

wacli (dev/piloto): `wacli auth` abre una sesión de emparejamiento y emite eventos
NDJSON; capturamos el evento `qr_code` y lo convertimos a imagen (segno) para la
consola. Con WACLI_STORE_ROOT cada tenant empareja SU PROPIO store (`--store`),
así la sesión/número de un negocio nunca es la de otro; sin la raíz (self-host de
un solo número) el store default solo puede pertenecer a UN tenant — el segundo
que intente recibe un rechazo honesto, no el número ajeno.

Cloud API (producción): las credenciales se capturan cifradas en el conector
`whatsapp_cloud`; aquí solo se ACTIVA como vía del canal y se recibe su webhook
(verificación GET + mensajes POST firmados con el app secret)."""

import hashlib
import hmac
import json
import select
import subprocess
import time

import segno
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select as sa_select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.config import settings
from aiuda_core.connectors.channel import wacli_store_dir, whatsapp_config
from aiuda_core.connectors.waba import parse_webhook as parse_waba_webhook
from aiuda_core.models import Conversation, IntegrationCredential, Message, Tenant

router = APIRouter()

# Proceso de emparejamiento en curso POR TENANT (cada negocio escanea su propio QR).
_AUTH_PROCS: dict[str, subprocess.Popen] = {}


def _store_args(tenant: Tenant) -> list[str]:
    """`--store` del workspace o nada (store default del host)."""
    store = wacli_store_dir(tenant.evolution_instance)
    return ["--store", store] if store else []


def _stop_auth(tenant_id: str) -> None:
    proc = _AUTH_PROCS.pop(tenant_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _is_authenticated(tenant: Tenant) -> bool:
    try:
        out = subprocess.run(
            [settings.wacli_bin, "auth", "status", *_store_args(tenant), "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(out.stdout or "{}")
        return bool(data.get("data", {}).get("authenticated"))
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return False


def _capture_qr(tenant: Tenant, deadline_s: float = 15.0) -> str | None:
    """Inicia `wacli auth` (con el store del tenant) y devuelve el contenido del QR."""
    _stop_auth(tenant.id)
    try:
        proc = subprocess.Popen(
            [settings.wacli_bin, "auth", "--qr-format", "text", "--events", *_store_args(tenant)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return None
    _AUTH_PROCS[tenant.id] = proc

    end = time.monotonic() + deadline_s
    assert proc.stderr is not None
    while time.monotonic() < end and proc.poll() is None:
        ready, _, _ = select.select([proc.stderr], [], [], end - time.monotonic())
        if not ready:
            break
        line = proc.stderr.readline()
        if not line:
            break
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("event") == "qr_code":
            return evt.get("data", {}).get("code")
        if evt.get("event") == "error":
            break
    return None


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


@router.post("/v1/integrations/whatsapp/qr")
def whatsapp_qr(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Devuelve el QR para emparejar (o avisa si ya está conectado)."""
    dueno = _duena_del_store_default(db, tenant)
    if dueno is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "El WhatsApp de este servidor ya está vinculado a otro negocio. Para "
                "varios negocios cada uno necesita su propio store (WACLI_STORE_ROOT) "
                "o el canal oficial de WhatsApp Business."
            ),
        )
    if _is_authenticated(tenant):
        _mark(tenant, db, "wacli")
        return {"connected": True, "qr": None}

    code = _capture_qr(tenant)
    if not code:
        raise HTTPException(
            status_code=502,
            detail="No se pudo generar el QR. Revisa que wacli esté instalado en el servidor.",
        )
    qr = segno.make(code, error="m")
    return {"connected": False, "qr": qr.svg_data_uri(scale=6, border=2)}


@router.get("/v1/integrations/whatsapp/status")
def whatsapp_status(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    connected = _is_authenticated(tenant)
    if connected:
        _stop_auth(tenant.id)
        # No robar el store default: solo marca conectado si nadie más lo posee.
        if _duena_del_store_default(db, tenant) is None:
            _mark(tenant, db, "wacli")
        else:
            connected = False
    return {"connected": connected}


@router.delete("/v1/integrations/whatsapp/session")
def whatsapp_logout(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    _stop_auth(tenant.id)
    try:
        subprocess.run(
            [settings.wacli_bin, "auth", "logout", *_store_args(tenant)],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
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
