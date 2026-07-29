"""Webhook de estado de las LLAMADAS DE VOZ (Twilio).

Cuando aiuda coloca una llamada de recordatorio, le pide a Twilio que avise el
resultado a este endpoint (StatusCallback). Aquí ligamos ese veredicto al
recordatorio correcto y hacemos verdad la entrega:

  - completed            → la llamada se contestó: el recordatorio queda 'sent'
                           (ya lo estaba al colocarse) con el resultado registrado.
  - no-answer/busy/failed → nadie contestó / la llamada no conectó: se marca
                           'failed' con el motivo VISIBLE, para que el dueño lo vea y
                           reintente (mismo trato honesto que WhatsApp/correo).

Seguridad: la firma X-Twilio-Signature es OBLIGATORIA (HMAC-SHA1 de la URL del
callback + los parámetros del POST ordenados, en base64, con el auth_token del
tenant como clave). Sin firma válida no se acepta ningún evento. El tenant dueño se
identifica por el AccountSid (público, en la credencial cifrada): se rutea SIN
descifrar, igual que el webhook oficial de WhatsApp rutea por phone_number_id.
"""

import base64
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select as sa_select

from aiuda_server.api.deps import get_db
from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.twilio_voz import parse_status_webhook
from aiuda_core.engine import approval
from aiuda_core.models import IntegrationCredential, Reminder, Tenant

router = APIRouter()

log = logging.getLogger("aiuda.twilio_voz")


def _tenant_por_account_sid(db, account_sid: str) -> Tenant | None:
    """El tenant dueño de la cuenta de Twilio. El account_sid vive en public_config de
    la credencial (no es secreto): se rutea SIN descifrar nada."""
    if not account_sid:
        return None
    rows = db.scalars(
        sa_select(IntegrationCredential).where(
            IntegrationCredential.provider == "twilio_voz",
            IntegrationCredential.status != "disabled",
        )
    ).all()
    for row in rows:
        if (row.public_config or {}).get("account_sid") == account_sid:
            return db.get(Tenant, row.tenant_id)
    return None


def _firma_valida(url: str, params: dict, header: str, auth_token: str) -> bool:
    """X-Twilio-Signature = base64(HMAC-SHA1(auth_token, url + concat(params ordenados))).

    Twilio ordena los parámetros del POST por nombre y los concatena como
    clave+valor (sin separador) al final de la URL exacta del callback. Se valida
    contra la URL CONFIGURADA (la que Twilio recibió), no la reconstruida del request,
    para no depender de cómo el proxy reescribe el host/esquema."""
    if not auth_token or not header or not url:
        return False
    base = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), base.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, header)


def _reminder_por_call_sid(db, tenant_id: str, call_sid: str) -> Reminder | None:
    """El recordatorio de voz cuyo Call SID guardamos al colocar la llamada
    (meta.voz.call_sid). Se filtra por el canal y se cruza en Python el JSON (portable
    entre SQLite de test y Postgres de prod)."""
    rows = db.scalars(
        sa_select(Reminder).where(
            Reminder.tenant_id == tenant_id,
            Reminder.channel == "voz",
        )
    ).all()
    for r in rows:
        if ((r.meta or {}).get("voz") or {}).get("call_sid") == call_sid:
            return r
    return None


@router.post("/v1/webhooks/twilio-voz")
async def twilio_voz_status(request: Request, db=Depends(get_db)):
    """Estado de una llamada de recordatorio. Valida la firma con el auth_token del
    tenant dueño de la cuenta y marca la entrega sobre el recordatorio ligado por Call
    SID. Un evento sin firma válida se rechaza (403)."""
    form = dict((await request.form()).items())
    estado = parse_status_webhook(form)
    if estado is None:
        return {"status": "ignored"}  # POST que no es de estado de llamada

    tenant = _tenant_por_account_sid(db, estado.account_sid)
    if tenant is None:
        # Cuenta desconocida: no podemos autenticar el evento (no tenemos su token).
        raise HTTPException(status_code=403, detail="Cuenta de Twilio desconocida")
    try:
        creds = cred.get_credential(db, tenant.id, "twilio_voz")
    except Exception as exc:  # noqa: BLE001 — credencial ilegible: no autenticamos
        log.warning("no se pudo leer la credencial de Twilio: %s", exc)
        raise HTTPException(status_code=403, detail="No se pudo validar la firma")
    auth_token = (creds or {}).get("auth_token", "")
    callback_url = settings.twilio_voz_status_callback_url
    if not _firma_valida(
        callback_url, form, request.headers.get("X-Twilio-Signature", ""), auth_token
    ):
        raise HTTPException(status_code=403, detail="Firma del webhook inválida")

    reminder = _reminder_por_call_sid(db, tenant.id, estado.call_sid)
    if reminder is None:
        return {"status": "ignored"}  # llamada sin recordatorio ligado (o ya purgado)

    voz_meta = dict((reminder.meta or {}).get("voz") or {})
    if voz_meta.get("estado") == estado.status:
        return {"status": "duplicate"}  # Twilio reintenta el callback: idempotente

    voz_meta["estado"] = estado.status
    if estado.duration:
        voz_meta["duracion"] = estado.duration
    meta = {**(reminder.meta or {}), "voz": voz_meta}

    if estado.ok:
        # Contestó: el recordatorio ya está 'sent' (se marcó al colocar la llamada);
        # dejamos constancia del resultado y limpiamos cualquier motivo de falla viejo.
        voz_meta["resultado"] = "contestada"
        meta.pop("motivo_fallo", None)
        reminder.meta = meta
        db.add(reminder)
        db.flush()
        return {"status": "completed", "reminder": reminder.id}

    # No conectó: falla honesta con motivo visible. Si el recordatorio seguía 'sent'
    # (se colocó), lo pasamos a 'failed' para que el dueño lo vea y reintente.
    motivo = f"Llamada no conectada: {estado.motivo_falla}"
    voz_meta["resultado"] = estado.motivo_falla
    if reminder.status == "sent":
        approval.advance(reminder, "failed")
    meta["motivo_fallo"] = motivo
    reminder.meta = meta
    db.add(reminder)
    db.flush()
    return {"status": "failed", "reminder": reminder.id, "motivo": estado.motivo_falla}
