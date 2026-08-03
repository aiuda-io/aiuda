"""Trabajos del motor local.

Tareas:
- process_incoming_message: mensaje de WhatsApp → Cleo → respuesta
- send_reminder: recordatorio aprobado → envío real (WhatsApp o correo)
- run_daily: corrida diaria de recordatorios + resumen al dueño (cron 8:00 MX);
  también propone (HITL) las respuestas a correos entrantes nuevos
- send_correo_reply: respuesta del humano en un hilo de correo → SMTP con threading

Aislamiento por tenant: cada envío sale por la instancia de WhatsApp DEL tenant
dueño (``resolve_whatsapp``) o por SU cuenta de correo (``resolve_correo``). Un
tenant sin canal conectado no envía nada — y nunca por el número o buzón de otro
negocio.
"""

import logging
import shlex
import subprocess
import threading
import time
from contextlib import contextmanager, nullcontext as _nullcontext
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from aiuda_core.config import settings
from aiuda_core.connectors.channel import (
    CHANNELS,
    get_channel_sender,
    get_correo_sender,
    get_whatsapp_sender,
    resolve_correo,
    resolve_voz,
    resolve_whatsapp,
)
from aiuda_core.db import session_scope
from aiuda_core.engine.engine import CleoEngine, OutsideSendWindow, ShadowHold
from aiuda_core.engine.llm import BudgetExceeded
from aiuda_core.optout import OPT_OUT_CONFIRMATION, OptedOut, is_opt_out, mark_opt_out
from aiuda_core.phones import match_key
from aiuda_core.models import Conversation, Customer, Invoice, Message, Reminder, Tenant, utcnow

MX_TZ = ZoneInfo("America/Mexico_City")
log = logging.getLogger("aiuda.worker")

# Un envío a la vez por proceso: pausar/reiniciar el sync de wacli no puede solaparse
# (dos envíos pisándose el stop/start volverían a chocar con el lock). Serializa también
# los envíos del chat para que no compitan por el store.
_send_lock = threading.Lock()

# Una corrida diaria a la vez por proceso: dos disparos solapados del cron redactarían y
# auto-enviarían la MISMA cobranza dos veces (ambos leen "sin recordatorio activo" a la vez).
# Asume uvicorn de un solo worker (config del VPS mono-usuario).
_daily_lock = threading.Lock()


def _run_sync_cmd(cmd: str, label: str) -> None:
    if not cmd:
        return
    try:
        subprocess.run(shlex.split(cmd), capture_output=True, timeout=20)
    except Exception as exc:  # noqa: BLE001 — pausar/reanudar el sync no debe tumbar el envío
        log.warning("sync %s falló (%s): %s", label, cmd, exc)


@contextmanager
def _sync_paused():
    """Libera el lock del store de wacli durante el envío y lo reanuda al terminar.

    `wacli sync --follow` retiene el lock SQLite y `wacli send` espera ~30s a que se
    libere. Igual que fastapi_service: paramos el sync, enviamos (~2s) y lo reiniciamos.
    Serializado por `_send_lock` para que dos envíos no se solapen el stop/start. Si no
    hay comandos configurados, sólo serializa (el envío cae al --lock-wait de siempre)."""
    with _send_lock:
        _run_sync_cmd(settings.wacli_sync_stop_cmd, "stop")
        if settings.wacli_sync_stop_cmd and settings.wacli_sync_settle_secs > 0:
            time.sleep(settings.wacli_sync_settle_secs)
        try:
            yield
        finally:
            _run_sync_cmd(settings.wacli_sync_start_cmd, "start")


def _pause_for(wa) -> object:
    """Contexto de envío según el provider: sólo wacli pelea el lock del store con su
    daemon de sync; la Cloud API y Evolution son HTTP y no necesitan pausar nada."""
    return _sync_paused() if (wa is not None and wa.provider == "wacli") else _nullcontext()


def _today():
    return datetime.now(MX_TZ).date()


def _service_window_fn(session, tenant_id: str):
    """Ventana de servicio de la Cloud API: ¿el cliente escribió hace <24 h?

    Dentro de la ventana Meta acepta texto libre; fuera, solo plantillas aprobadas.
    Se decide con NUESTRO registro de entrantes (por match_key, para que 52 vs 521
    no rompa el cruce)."""

    def _within(phone: str) -> bool:
        key = match_key(phone)
        if not key:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = session.execute(
            select(Conversation.remote_phone)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Message.tenant_id == tenant_id,
                Message.direction == "in",
                Message.created_at >= cutoff,
            )
        ).all()
        return any(match_key(remote) == key for (remote,) in rows)

    return _within


def _tenant_sender(session, tenant: Tenant, wa=None):
    """Sender de WhatsApp DEL tenant (o None si no tiene el canal conectado)."""
    wa = wa or resolve_whatsapp(session, tenant)
    if wa is None:
        return None
    window = _service_window_fn(session, tenant.id) if wa.provider == "whatsapp_cloud" else None
    return get_whatsapp_sender(wa, window)


def _build_engine(session, tenant: Tenant, run=None) -> CleoEngine:
    from aiuda_server.metering import budget_check

    # Canal por tenant (wacli | whatsapp_cloud | evolution) — ver connectors/channel.py
    engine = CleoEngine(
        session,
        tenant,
        send_whatsapp=_tenant_sender(session, tenant),
    )
    if run is not None:
        # La corrida queda grabada: qué redactó, con qué prompt y cuánto tardó. El
        # wrapper reenvía la asignación de abajo al runner de adentro; sin eso, el tope
        # de gasto se apagaría en silencio.
        from aiuda_core.observabilidad import envolver

        engine.runner = envolver(engine.runner, run, session, tenant)
    # Tope de gasto de IA: se engancha al runner (mismo patrón que el usage_callback).
    # Con el tope agotado, NINGUNA llamada al proveedor sale de este engine.
    engine.runner.budget_check = budget_check(session, tenant)
    return engine


def _aviso_tope(session, tenant: Tenant, motivo: str) -> None:
    """Deja constancia HONESTA del corte de IA: una vez por mes por tenant escribe la
    bitácora (auditable) y guarda el aviso en tenant.config (la consola lo muestra en
    el centro de mando).
    Si el negocio conectó Slack, el mismo aviso sale a su canal (una vez, por el
    mismo guard mensual); si no, no pasa nada."""
    from aiuda_server import audit
    from aiuda_core.connectors.slack import aviso_al_equipo

    mes = datetime.now(MX_TZ).strftime("%Y-%m")
    cfg = dict(tenant.config or {})
    previo = cfg.get("ia_tope_aviso") or {}
    if previo.get("mes") == mes:
        return  # ya avisado este mes: no spamear la bitácora
    cfg["ia_tope_aviso"] = {"mes": mes, "at": datetime.now(MX_TZ).isoformat(), "motivo": motivo}
    tenant.config = cfg
    session.add(tenant)
    audit.record(
        session,
        tenant_id=tenant.id,
        action="ia.tope",
        entity_type="tenant",
        entity_id=tenant.id,
        after={"motivo": motivo, "mes": mes},
    )
    aviso_al_equipo(session, tenant.id, f"aiuda · La IA se pausó este mes: {motivo}")
    log.warning("IA cortada para tenant %s: %s", tenant.id, motivo)


def process_incoming_message_blocking(tenant_id: str, message_id: str) -> None:
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        message = session.get(Message, message_id)
        if tenant is None or message is None or message.tenant_id != tenant_id:
            return
        conversation = session.get(Conversation, message.conversation_id)
        if conversation.human_takeover:
            return  # el humano tiene el control: el agente no interviene
        engine = _build_engine(session, tenant)

        # ¿Es el dueño? Sus mensajes pueden ser comandos de aprobación. Se compara por los
        # últimos 10 dígitos (match_key): el owner_phone y el teléfono del webhook pueden
        # venir en formatos distintos (52 vs 521, con/sin sufijos) y una igualdad exacta
        # dejaría al dueño sin reconocer.
        owner_key = match_key(tenant.owner_phone)
        is_owner = bool(owner_key) and match_key(conversation.remote_phone) == owner_key
        if is_owner:
            from aiuda_core.engine.owner import handle_owner_command

            owner_reply = handle_owner_command(session, tenant, message.body)
            if owner_reply is not None:
                engine.send_whatsapp(tenant.owner_phone, owner_reply.text)
                session.add(
                    Message(
                        tenant_id=tenant.id,
                        conversation_id=conversation.id,
                        direction="out",
                        body=owner_reply.text,
                    )
                )
                for reminder, phone in owner_reply.send_reminders:
                    # Mismo blindaje que send_reminder_blocking: si un envío truena o
                    # el cliente pidió la baja, se marca el veredicto y se SIGUE — una
                    # excepción aquí haría rollback y perdería la respuesta al dueño.
                    try:
                        engine.send(reminder, phone)
                    except OptedOut:
                        from aiuda_core.engine import approval

                        log.info("envío bloqueado por opt-out: %s", reminder.id)
                        approval.advance(reminder, "failed")
                        reminder.meta = {**(reminder.meta or {}), "motivo_fallo": "opt-out"}
                    except (OutsideSendWindow, ShadowHold) as exc:
                        log.info("envío retenido (%s): %s", type(exc).__name__, reminder.id)
                    except Exception as exc:  # noqa: BLE001
                        from aiuda_core.engine import approval

                        log.exception("envío falló: %s", reminder.id)
                        if reminder.status == "approved":
                            approval.advance(reminder, "failed")
                        if reminder.status == "failed":
                            reminder.meta = {
                                **(reminder.meta or {}),
                                "motivo_fallo": f"No salió: {str(exc)[:200]}",
                            }
                return
            # No era comando: el agente le responde con los datos de su negocio

        # Opt-out (BAJA/STOP) de un cliente: se registra, se confirma UNA vez con texto
        # determinista (sin LLM) y no se procesa más. El dueño nunca se auto-da de baja.
        if not is_owner and is_opt_out(message.body):
            mark_opt_out(session, tenant, conversation.remote_phone, via="whatsapp")
            if engine.send_whatsapp is not None:
                try:
                    engine.send_whatsapp(conversation.remote_phone, OPT_OUT_CONFIRMATION)
                except Exception as exc:  # noqa: BLE001 — la baja queda aunque la confirmación falle
                    log.warning("confirmación de baja no enviada: %s", exc)
            session.add(
                Message(
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    direction="out",
                    body=OPT_OUT_CONFIRMATION,
                )
            )
            return

        # Historial reciente del hilo: sin él, el agente contestaría cada
        # mensaje como si fuera el primero.
        previous = session.scalars(
            select(Message)
            .where(
                Message.tenant_id == tenant.id,
                Message.conversation_id == conversation.id,
                Message.id != message.id,
            )
            .order_by(Message.created_at.desc())
            .limit(10)
        ).all()
        history = "\n".join(
            f"[{'Cliente' if m.direction == 'in' else 'Dueño' if m.author == 'human' else 'Tú (agente)'}]: {m.body}"
            for m in reversed(previous)
        )

        try:
            reply = engine.handle_incoming(
                conversation.remote_phone, message.body, _today(), history=history
            )
        except BudgetExceeded as exc:
            # Corte honesto: tope de IA agotado. No se responde con IA; el mensaje
            # queda en la bandeja para que un humano lo atienda, y se deja aviso.
            _aviso_tope(session, tenant, str(exc))
            return
        if not reply.strip():
            return
        engine.send_whatsapp(conversation.remote_phone, reply)
        session.add(
            Message(
                tenant_id=tenant.id,
                conversation_id=conversation.id,
                direction="out",
                body=reply,
            )
        )


def pendiente_canal_msg(channel: str) -> str:
    """Aviso honesto cuando se aprueba sin canal conectado: NO es un fallo, es una
    espera. El recordatorio queda APROBADO y sale cuando el dueño conecte el canal
    (o pulse "Enviar ahora"). 'failed' se reserva para un intento REAL que tronó."""
    nombre = {
        "whatsapp": "WhatsApp", "correo": "el correo",
        "voz": "las llamadas de voz (Twilio)", "sms": "SMS",
    }.get(channel, channel)
    return f"Aprobado. Se enviará cuando conectes {nombre}."


# Recordatorios EN VUELO en este proceso. Dos clics en "Enviar ahora" (o el
# barrido encimado con un clic) agendan dos tareas y ambas leían 'approved': el
# cliente recibía el mismo cobro dos veces (wacli tarda ~10s, la ventana es
# real). Una tarea reclama el vuelo; la encimada se va sin tocar nada. Asume un
# solo proceso, igual que _daily_lock.
_envio_reminder_lock = threading.Lock()
_envios_en_curso: set[str] = set()


def send_reminder_blocking(tenant_id: str, reminder_id: str) -> None:
    with _envio_reminder_lock:
        if reminder_id in _envios_en_curso:
            log.info("envío ya en curso para %s; se omite el disparo encimado", reminder_id)
            return
        _envios_en_curso.add(reminder_id)
    try:
        _send_reminder_impl(tenant_id, reminder_id)
    finally:
        with _envio_reminder_lock:
            _envios_en_curso.discard(reminder_id)


def _sin_marca_en_vuelo(meta: dict | None) -> dict:
    return {k: v for k, v in (meta or {}).items() if k != "envio_en_curso"}


def _send_reminder_impl(tenant_id: str, reminder_id: str) -> None:
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        reminder = session.get(Reminder, reminder_id)
        if tenant is None or reminder is None or reminder.tenant_id != tenant_id:
            return
        if reminder.status != "approved":
            return  # ya tuvo veredicto (otro disparo llegó primero): nada que enviar
        # Canal decidido al aprobar; el destinatario sale del dato que pide el canal.
        channel = reminder.channel or "whatsapp"
        customer = None
        if reminder.invoice_id:
            invoice = session.get(Invoice, reminder.invoice_id)
            customer = session.get(Customer, invoice.customer_id) if invoice else None
        field = CHANNELS.get(channel, {}).get("recipient_field", "phone")
        if field == "email":
            # Respuestas de correo traen su destinatario en meta.correo.para (el
            # hilo puede no tener factura/cliente ligado); cobranza usa el email
            # del cliente de la factura.
            meta_correo = (reminder.meta or {}).get("correo") or {}
            recipient = meta_correo.get("para") or (customer.email if customer else None)
        else:
            recipient = (customer.phone if customer else None) or reminder.recipient_phone
        # La instancia DEL tenant dueño del recordatorio: sin canal conectado no hay
        # sender (y jamás se sale por el número o buzón de otro negocio).
        wa = resolve_whatsapp(session, tenant)
        window = (
            _service_window_fn(session, tenant.id)
            if (wa is not None and wa.provider == "whatsapp_cloud")
            else None
        )
        if channel == "correo":
            correo = resolve_correo(session, tenant)
            correo_opts = (
                _correo_opts_para(session, tenant, reminder, customer, recipient)
                if (correo is not None and recipient)
                else None
            )
            sender = get_channel_sender(channel, wa, window, correo=correo, correo_opts=correo_opts)
        elif channel == "voz":
            # Llamada de voz (Twilio): el recordatorio se DICE por teléfono. Guardamos el
            # Call SID en el recordatorio para que el StatusCallback (webhook) ligue el
            # veredicto de la llamada (contestó / no contestó) al recordatorio correcto.
            voz = resolve_voz(session, tenant)

            def _guardar_call_sid(sid: str, _rem=reminder) -> None:
                voz_meta = {**((_rem.meta or {}).get("voz") or {}), "call_sid": sid, "estado": "en_curso"}
                _rem.meta = {**(_rem.meta or {}), "voz": voz_meta}

            voz_opts = {
                "status_callback": settings.twilio_voz_status_callback_url or None,
                "on_call": _guardar_call_sid,
            }
            sender = get_channel_sender(channel, wa, window, voz=voz, voz_opts=voz_opts)
        else:
            sender = get_channel_sender(channel, wa, window)
        if sender is None:
            # Canal NO conectado: no es un fallo, es una espera. El recordatorio queda
            # APROBADO y honesto; sale cuando el dueño conecte el canal (o pulse "Enviar
            # ahora" — el barrido de aprobados varados ya existe). Antes esto marcaba
            # 'failed' y la UI mentía con "Enviados": el bug que reportó José. 'failed' se
            # reserva para un intento REAL de envío que tronó (ver el except de abajo).
            meta = {**(reminder.meta or {}), "pendiente_canal": pendiente_canal_msg(channel)}
            meta.pop("motivo_fallo", None)  # si se reintenta un failed viejo, borra el veredicto
            reminder.meta = meta
            return
        if not recipient:
            # Sí hay canal, pero falta el dato de contacto del cliente (teléfono/correo):
            # esto SÍ pide acción del dueño y no lo arregla conectar un canal. Failed honesto
            # con motivo visible.
            from aiuda_core.engine import approval

            approval.advance(reminder, "failed")
            motivo = "el cliente no tiene correo" if channel == "correo" else "el cliente no tiene teléfono"
            reminder.meta = {**(reminder.meta or {}), "motivo_fallo": motivo}
            return
        engine = _build_engine(session, tenant)
        # Marca durable de EN VUELO. Si quedó de una corrida que murió entre el
        # envío y el 'sent', el WhatsApp pudo haber salido: reenviar a ciegas es
        # cobrar doble. Queda 'failed' con el motivo visible y reenviar es
        # decisión del dueño, no del barrido de varados.
        from aiuda_core.engine import approval

        if (reminder.meta or {}).get("envio_en_curso"):
            approval.advance(reminder, "failed")
            reminder.meta = {
                **_sin_marca_en_vuelo(reminder.meta),
                "motivo_fallo": (
                    "El envío anterior se interrumpió a la mitad; confirma con el "
                    "cliente si le llegó antes de reenviar."
                ),
            }
            return
        # La marca se COMMITEA antes de tocar el canal: es exactamente lo que un
        # apagón dejaría atrás para que el siguiente intento no repita el cobro.
        reminder.meta = {**(reminder.meta or {}), "envio_en_curso": utcnow().isoformat()}
        session.commit()
        # Sólo wacli choca con el lock del sync; Cloud API/Evolution/email no lo necesitan.
        pause = _pause_for(wa) if channel == "whatsapp" else _nullcontext()
        try:
            with pause:
                engine.send(reminder, recipient, sender)
        except OptedOut as exc:
            # El cliente pidió la baja: no es fallo del canal, es su decisión. Queda
            # 'failed' con el motivo visible; no se reintenta solo.
            log.info("envío bloqueado por opt-out: %s", reminder_id)
            approval.advance(reminder, "failed")
            reminder.meta = {**(reminder.meta or {}), "motivo_fallo": "opt-out", "detalle": str(exc)}
        except OutsideSendWindow:
            # Horario de no-molestar: no es un fallo. Queda aprobado y la próxima
            # corrida dentro de ventana lo envía.
            log.info("envío diferido (fuera de horario): %s", reminder_id)
        except ShadowHold:
            # Modo sombra: no se envía a clientes reales. Queda aprobado para revisar.
            log.info("envío retenido (modo sombra): %s", reminder_id)
        except Exception as exc:  # noqa: BLE001
            # Falla real del canal (wacli caído, número inválido, red). NO se propaga: si
            # la excepción sube, session_scope hace rollback y el estado se pierde, dejando
            # el recordatorio atorado (el bug que reportó José). Se marca 'failed' con el
            # motivo VISIBLE para que la UI diga qué pasó y ofrezca reintentar.
            # send_approved_reminder ya lo marca al tronar el envío; esto cubre el resto y
            # corta la propagación.
            log.exception("envío falló: %s", reminder_id)
            if reminder.status == "approved":
                approval.advance(reminder, "failed")
            if reminder.status == "failed":
                canal = CHANNELS.get(channel, {}).get("label", channel)
                reminder.meta = {
                    **(reminder.meta or {}),
                    "motivo_fallo": f"No salió por {canal}: {str(exc)[:200]}",
                }
        # Hubo veredicto (sent/failed) o retención deliberada (sombra/horario): la
        # marca de en-vuelo se limpia. Solo una muerte del proceso la deja puesta.
        reminder.meta = _sin_marca_en_vuelo(reminder.meta)


def _mark_delivery(tenant_id: str, message_id: str | None, status: str) -> None:
    """Fija el estado de entrega del saliente. Sin message_id no hace nada (compat)."""
    if not message_id:
        return
    with session_scope() as session:
        msg = session.get(Message, message_id)
        if msg is not None and msg.tenant_id == tenant_id:
            msg.delivery = status
            session.add(msg)


def send_human_message_blocking(
    tenant_id: str, phone: str, body: str, message_id: str | None = None
) -> None:
    """Envío en SEGUNDO PLANO de un mensaje del humano (chat de la ficha o del hilo).

    Clave de velocidad: el endpoint ya guardó el mensaje y respondió; el envío (lento,
    porque `wacli send` levanta conexión) ocurre aquí sin bloquear la consola.

    `message_id` cierra la mentira del `queued:true`: al terminar marca el mensaje como
    `sent` o `failed`. Si el proceso muere antes, el mensaje queda en `pending` y el barrido
    de la corrida diaria lo reintenta. Un `pending` viejo = envío que nunca obtuvo veredicto."""
    if not phone or not body:
        _mark_delivery(tenant_id, message_id, "failed")
        return
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        # Modo sombra: la consola promete "nada sale a clientes reales" y eso
        # incluye lo que el humano escribe desde la ficha o el hilo. Queda 'held'
        # en el historial (el barrido solo rescata 'pending', no lo re-dispara).
        if tenant is not None and bool((tenant.config or {}).get("modo_sombra")):
            log.info("modo sombra: mensaje humano a %s retenido (no se envió)", phone)
            _mark_delivery(tenant_id, message_id, "held")
            return
        wa = resolve_whatsapp(session, tenant) if tenant is not None else None
        if wa is None:
            _mark_delivery(tenant_id, message_id, "failed")  # sin canal: honesto, no se barre
            return
        # La ventana de 24 h (Cloud API) se decide aquí, con la sesión viva; el envío
        # ocurre después, ya sin sesión.
        within = (
            _service_window_fn(session, tenant_id)(phone)
            if wa.provider == "whatsapp_cloud"
            else False
        )
    with _pause_for(wa):
        ok = _safe_send(
            f"mensaje a {phone}",
            lambda: get_whatsapp_sender(wa, lambda _p: within)(phone, body),
        )
    _mark_delivery(tenant_id, message_id, "sent" if ok else "failed")


def send_human_file_blocking(
    tenant_id: str, phone: str, file_path: str, caption: str, filename: str
) -> None:
    """Igual que send_human_message_blocking pero para un archivo (PDF/imagen). Borra el
    temporal al terminar, pase lo que pase."""
    import os

    try:
        if not phone:
            return
        with session_scope() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is not None and bool((tenant.config or {}).get("modo_sombra")):
                log.info("modo sombra: adjunto a %s retenido (no se envió)", phone)
                return
            wa = resolve_whatsapp(session, tenant) if tenant is not None else None
            if wa is None:
                return
            if wa.provider != "wacli":
                # Honesto: el adjunto por Cloud API (media upload) aún no está cableado.
                log.warning("adjunto omitido: el canal del negocio no es wacli")
                return
        from aiuda_core.connectors.wacli import WacliClient

        with _pause_for(wa):
            _safe_send(
                f"archivo a {phone}",
                lambda: WacliClient(store_dir=wa.store_dir).send_file(
                    phone, file_path, caption=caption, filename=filename
                ),
            )
    finally:
        try:
            os.remove(file_path)
            os.rmdir(os.path.dirname(file_path))
        except OSError:
            pass


# ---------- Correo (canal email): asunto, envío enhebrado, respuesta humana y propuestas ----------


def _asunto_correo(session, reminder: Reminder) -> str:
    """El asunto de un recordatorio que sale por correo: el del hilo si es respuesta
    (ya viene como 'Re: …'), o uno claro derivado del trabajo (título / factura)."""
    meta = (reminder.meta or {}).get("correo") or {}
    if meta.get("asunto"):
        return meta["asunto"]
    if reminder.title:
        return reminder.title
    if reminder.invoice_id:
        invoice = session.get(Invoice, reminder.invoice_id)
        if invoice is not None:
            return f"Recordatorio de pago · Factura {invoice.folio}"
    return "Recordatorio de pago"


def _correo_opts_para(session, tenant, reminder: Reminder, customer, destinatario: str) -> dict:
    """Arma el envío por correo de UN recordatorio: si es respuesta a un hilo
    (meta.correo.conversation_id), asunto Re: + In-Reply-To/References del hilo;
    si es cobranza nueva, crea/reusa el hilo por remitente+asunto para que la
    respuesta del cliente caiga a la MISMA conversación. `on_sent` deja el correo
    enviado en el hilo con su Message-ID."""
    from aiuda_core.engine.correo import hilo_para_envio, registrar_saliente, reply_headers

    conv = None
    meta = (reminder.meta or {}).get("correo") or {}
    if meta.get("conversation_id"):
        conv = session.get(Conversation, meta["conversation_id"])
        if conv is not None and conv.tenant_id != tenant.id:
            conv = None
    if conv is not None:
        headers = reply_headers(session, tenant, conv)
        asunto = headers["asunto"] or _asunto_correo(session, reminder)
        in_reply_to, references = headers["in_reply_to"], headers["references"]
    else:
        asunto = _asunto_correo(session, reminder)
        conv = hilo_para_envio(
            session, tenant, destinatario, (customer.name if customer else ""), asunto
        )
        in_reply_to, references = "", ()
    conv_id = conv.id

    def _al_enviar(message_id: str) -> None:
        c = session.get(Conversation, conv_id)
        if c is not None:
            registrar_saliente(session, tenant, c, reminder.message, message_id, author="agent")

    return {
        "asunto": asunto,
        "in_reply_to": in_reply_to,
        "references": references,
        "on_sent": _al_enviar,
    }


def send_correo_reply_blocking(tenant_id: str, conversation_id: str, message_id: str) -> None:
    """Envío en SEGUNDO PLANO de la respuesta del HUMANO en un hilo de correo.

    El endpoint ya guardó el mensaje (delivery=pending) y respondió; aquí sale por
    SMTP con asunto 'Re: …' e In-Reply-To/References del hilo, y el veredicto queda
    en el mensaje (sent/failed). El Message-ID generado se guarda en el mensaje:
    la siguiente respuesta del cliente enhebra contra él."""
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        conv = session.get(Conversation, conversation_id)
        msg = session.get(Message, message_id)
        if (
            tenant is None or conv is None or msg is None
            or conv.tenant_id != tenant_id or msg.tenant_id != tenant_id
        ):
            _mark_delivery(tenant_id, message_id, "failed")
            return
        # Modo sombra: tampoco el correo humano sale a clientes reales.
        if bool((tenant.config or {}).get("modo_sombra")):
            log.info("modo sombra: respuesta de correo retenida (no se envió)")
            msg.delivery = "held"
            session.add(msg)
            return
        from aiuda_core.engine.correo import reply_headers

        correo = resolve_correo(session, tenant)
        headers = reply_headers(session, tenant, conv)
        if correo is None or not headers["para"]:
            msg.delivery = "failed"  # sin canal o hilo sin remitente: honesto
            return
        sender = get_correo_sender(
            correo,
            asunto=headers["asunto"],
            in_reply_to=headers["in_reply_to"],
            references=headers["references"],
            on_sent=lambda mid: setattr(msg, "wa_message_id", (mid or "")[:128] or None),
        )
        ok = _safe_send(f"correo a {headers['para']}", lambda: sender(headers["para"], msg.body))
        msg.delivery = "sent" if ok else "failed"
        session.add(msg)


def procesar_correo_pendientes(session, tenant, engine) -> int:
    """Propuestas HITL para los correos entrantes nuevos (cola en
    ``Tenant.config['correo_pendientes']``, la llena sync_correo).

    Por CONVERSACIÓN (no por correo: si llegaron tres seguidos, una sola propuesta
    con el último y el historial), el agente redacta una respuesta que queda
    ``pending_approval`` con canal correo en el Centro — NUNCA contesta solo. BAJA
    por correo se registra y confirma sin LLM. Con el tope de IA agotado, lo no
    procesado espera la próxima corrida. Devuelve cuántas propuestas dejó."""
    from aiuda_core.engine.correo import (
        CORREO_PENDIENTES_KEY,
        hilo_meta,
        registrar_saliente,
        reply_headers,
    )
    from aiuda_core.identity import resolve_customer_by_email

    cola = list((tenant.config or {}).get(CORREO_PENDIENTES_KEY) or [])
    if not cola:
        return 0

    # Agrupa por conversación conservando el orden: se responde al ÚLTIMO entrante.
    por_conv: dict[str, Message] = {}
    for mid in cola:
        msg = session.get(Message, mid)
        if msg is not None and msg.tenant_id == tenant.id:
            por_conv[msg.conversation_id] = msg

    # Propuestas de correo aún vivas (evita amontonar una por corrida al mismo hilo).
    abiertas = {
        ((r.meta or {}).get("correo") or {}).get("conversation_id")
        for r in session.scalars(
            select(Reminder).where(
                Reminder.tenant_id == tenant.id,
                Reminder.status == "pending_approval",
                Reminder.channel == "correo",
            )
        ).all()
    }

    propuestas = 0
    restantes: list[str] = []
    pendientes = list(por_conv.items())
    for idx, (conv_id, msg) in enumerate(pendientes):
        conv = session.get(Conversation, conv_id)
        if conv is None or conv.human_takeover:
            continue  # el humano lleva el hilo: sin propuesta (se descarta de la cola)
        meta = hilo_meta(tenant, conv.id)
        remitente = meta.get("de", "")

        # BAJA por correo: registro determinista + confirmación única, sin LLM.
        if is_opt_out(msg.body):
            mark_opt_out(session, tenant, remitente or conv.remote_phone, via="correo")
            correo = resolve_correo(session, tenant)
            if correo is not None and remitente:
                headers = reply_headers(session, tenant, conv)
                sender = get_correo_sender(
                    correo, asunto=headers["asunto"],
                    in_reply_to=headers["in_reply_to"], references=headers["references"],
                    on_sent=lambda mid, c=conv: registrar_saliente(
                        session, tenant, c, OPT_OUT_CONFIRMATION, mid
                    ),
                )
                _safe_send(
                    f"confirmación de baja a {remitente}",
                    lambda: sender(remitente, OPT_OUT_CONFIRMATION),
                )
            continue

        if conv.id in abiertas:
            # Ya hay una propuesta esperando aprobación para este hilo: este entrante
            # se re-encola y, resuelta aquella, la próxima corrida propone con TODO
            # el historial (no se amontonan dos propuestas del mismo hilo).
            restantes.append(msg.id)
            continue

        cliente = resolve_customer_by_email(session, tenant.id, remitente)
        historial = session.scalars(
            select(Message)
            .where(
                Message.tenant_id == tenant.id,
                Message.conversation_id == conv.id,
                Message.id != msg.id,
            )
            .order_by(Message.created_at.desc())
            .limit(10)
        ).all()
        history = "\n".join(
            f"[{'Cliente' if m.direction == 'in' else 'Dueño' if m.author == 'human' else 'Tú (agente)'}]: {m.body}"
            for m in reversed(historial)
        )
        quien = f"{meta.get('nombre') or (cliente.name if cliente else '')} <{remitente}>".strip()
        origen = (
            f"Correo de {quien}"
            + (f" con asunto {meta.get('asunto')!r}" if meta.get("asunto") else "")
            + ". Redacta la RESPUESTA como un correo breve y profesional (sin encabezados"
            " ni firma: solo el cuerpo); un humano la revisará antes de enviarla"
        )
        try:
            # Tools atadas al cliente (su teléfono) si lo hay; si no, al remitente:
            # nunca ven facturas de otro cliente.
            respuesta = engine.handle_incoming(
                (cliente.phone if cliente and cliente.phone else remitente),
                msg.body, _today(), history=history, origen=origen,
            )
        except BudgetExceeded as exc:
            _aviso_tope(session, tenant, str(exc))
            # Lo no procesado (este y los que siguen) espera a la próxima corrida.
            restantes.extend(m.id for _, m in pendientes[idx:])
            break
        if respuesta.strip():
            session.add(
                Reminder(
                    tenant_id=tenant.id,
                    agent="mariana",
                    title=f"Correo de {meta.get('nombre') or remitente or 'cliente'}",
                    bucket="respuesta_correo",
                    tone="amable",
                    message=respuesta.strip(),
                    channel="correo",
                    status="pending_approval",
                    meta={
                        "correo": {
                            "para": remitente,
                            "conversation_id": conv.id,
                            "responde_a": msg.id,
                            "asunto": "",  # se resuelve al enviar (Re: del hilo)
                        }
                    },
                )
            )
            propuestas += 1

    cfg = dict(tenant.config or {})
    cfg[CORREO_PENDIENTES_KEY] = restantes
    tenant.config = cfg
    session.add(tenant)
    session.flush()
    return propuestas


def _process_writebacks(session, tenant):
    """Inyecta a los sistemas de origen lo confirmado en aiuda (si hay conector).
    Credenciales por tenant desde la tabla cifrada (fallback a config/settings)."""
    from aiuda_core.connectors.credentials import ctor_kwargs, get_credential
    from aiuda_core.engine.writeback import process_outbox

    odoo = None
    shopify = None
    odoo_creds = get_credential(session, tenant.id, "odoo")
    if odoo_creds and odoo_creds.get("url"):
        from aiuda_core.connectors.odoo import OdooConnector

        odoo = OdooConnector(**ctor_kwargs("odoo", odoo_creds))
    shopify_creds = get_credential(session, tenant.id, "shopify")
    if shopify_creds and shopify_creds.get("access_token"):
        from aiuda_core.connectors.shopify import ShopifyClient

        shopify = ShopifyClient(**ctor_kwargs("shopify", shopify_creds))
    gcal = None
    gcal_creds = get_credential(session, tenant.id, "googlecalendar")
    if gcal_creds and gcal_creds.get("token"):
        from aiuda_core.connectors.gcal import GoogleCalendarClient

        gcal = GoogleCalendarClient(**ctor_kwargs("googlecalendar", gcal_creds))
    # tenant va siempre: habilita el ejecutor de conexiones a la medida (custom).
    return process_outbox(session, tenant, odoo_client=odoo, shopify_client=shopify, gcal_client=gcal)


def process_writebacks_blocking(tenant_id: str) -> None:
    """Reintento manual desde la consola: procesa el outbox del tenant fuera del
    request (el conector habla con el sistema fuente y puede tardar)."""
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is not None:
            _process_writebacks(session, tenant)


def _safe_send(label: str, send_fn) -> bool:
    """Envía sin tumbar la corrida: en free no hay canal (wacli) y el envío truena.
    Si falla, lo registra y sigue — lo redactado queda en Aprobaciones de todos modos."""
    try:
        send_fn()
        return True
    except Exception as exc:  # noqa: BLE001 — un canal caído no debe abortar el día
        log.warning("envío omitido (%s): %s", label, exc)
        return False


def run_daily_blocking(
    now: datetime | None = None, horas_cubiertas: list[int] | None = None
) -> dict:
    """Corrida diaria con guard anti-solapamiento. Si ya hay una corriendo en el proceso,
    omite el disparo duplicado (dos disparos solapados del cron mandarían doble cobranza)."""
    if not _daily_lock.acquire(blocking=False):
        log.info("corrida diaria ya en curso; se omite el disparo duplicado")
        return {"skipped": True}
    try:
        return _run_daily_impl(now, horas_cubiertas)
    finally:
        _daily_lock.release()


def _run_daily_impl(
    now: datetime | None = None, horas_cubiertas: list[int] | None = None
) -> dict:
    """Corrida diaria, reutilizable por el cron del worker y por el trigger HTTP
    (free tier sin worker continuo). Para cada tenant: sincroniza fuentes, redacta
    recordatorios y manda el resumen a su hora. Degrada con gracia: si no hay canal de
    envío (o cae fuera del horario de no-molestar), redacta y deja todo en Aprobaciones
    sin fallar. Idempotente: correr cada hora no duplica (cooldown + recordatorio activo).

    Pensada para correr CADA HORA: así cada negocio recibe su resumen a la hora que
    configuró y los auto-envíos respetan su franja. `now` es inyectable para pruebas.

    `horas_cubiertas` son las horas de reloj que esta corrida está saldando: el
    scheduler las manda cuando la máquina estuvo dormida y se perdieron horas. Sin
    ellas se asume solo la hora de `now`. Es lo que hace que el resumen de las 8
    salga (tarde) si la laptop se abrió a las 11, en vez de perderse ese día.

    La corrida de cada tenant va POR ETAPAS, cada una con su propia transacción
    (antes era UNA sola que envolvía también las llamadas al LLM): un error de la
    IA ya no revierte lo sincronizado, y la base no se queda retenida minutos
    mientras el proveedor contesta ("database is locked" cuando el dueño quería
    aprobar). Etapas: 1) sync + write-back, 2) redacción (IA), 3) auto-envíos
    (por el mismo camino idempotente de send_reminder_blocking), 4) resumen."""
    from aiuda_server.api.integrations import fuentes_preferidas
    from aiuda_server.costs import ia_budget, ia_budget_message
    from aiuda_core.engine.sync import sync_fuentes

    current = now or datetime.now(MX_TZ)
    today = current.date()
    horas = list(horas_cubiertas) if horas_cubiertas else [current.hour]
    report = {
        "tenants": 0, "drafted": 0, "sent": 0, "send_skipped": 0, "summaries": 0,
        "ia_cortada": 0, "correo_propuestas": 0,
    }
    with session_scope() as session:
        tenant_ids = session.scalars(select(Tenant.id)).all()
    for tenant_id in tenant_ids:
        # Aislamiento por tenant: un negocio con un problema (p.ej. una credencial
        # ilegible que hace fallar el resolver, o una fuente caída) no debe abortar
        # la corrida de los demás. Se registra y se sigue.
        try:
            # 1) Fuentes primero, en SU transacción: la cartera de las fuentes
            #    conectadas entra (tienda, Odoo…) respetando "de dónde lee" cada
            #    capacidad, los pagos detectados entran a conciliación (Diego
            #    propone, el humano confirma) y el outbox se inyecta de regreso.
            #    Lo sincronizado queda commiteado ANTES de tocar la IA.
            with session_scope() as session:
                from aiuda_core.observabilidad import abrir_run, contar_sync

                tenant = session.get(Tenant, tenant_id)
                # Traer la cartera es trabajo, y era el más invisible: entraban 147
                # facturas de Odoo y nadie se lo decía al dueño.
                with abrir_run(session, tenant, disparo="sincronizacion") as run:
                    reporte = sync_fuentes(
                        session, tenant, today=today,
                        fuente_prefs=fuentes_preferidas(session, tenant),
                    )
                    contar_sync(run, reporte)
                    wb = _process_writebacks(session, tenant)
                    # Lo que regresó a TU sistema (un pago asentado en Odoo, un cliente
                    # creado allá). Es la otra mitad del trabajo con integraciones y
                    # tampoco se veía. `getattr` porque contar no puede romper la corrida
                    # si un ejecutor no devuelve reporte.
                    if getattr(wb, "processed", 0):
                        run.contar(inyectados=wb.processed)
                    if getattr(wb, "failed", 0):
                        run.contar(fallidos=wb.failed)
                        run.motivo("inyeccion_fallida", "No se pudo regresar a tu sistema")
            # 2) Con la cartera al día, la redacción — salvo tope de IA agotado o
            #    cuenta no activa: corte honesto, la corrida NO llama a la IA y
            #    queda aviso. Un tropiezo aquí ya no revierte la etapa 1.
            auto_aprobados: list[str] = []
            with session_scope() as session:
                from aiuda_core.observabilidad import abrir_run

                tenant = session.get(Tenant, tenant_id)
                # La corrida de la noche queda grabada. Es la que el dueño no vio pasar,
                # así que es justo la que más necesita poder revisar en la mañana.
                with abrir_run(session, tenant, disparo="corrida") as run:
                    engine = _build_engine(session, tenant, run=run)
                    verdict = ia_budget(session, tenant)
                    if verdict["agotado"] or verdict["bloqueada"]:
                        _aviso_tope(session, tenant, ia_budget_message(verdict))
                        report["ia_cortada"] += 1
                        # `cortado`, no `done`: terminó sin error pero sin hacer el
                        # trabajo. Antes esto se perdía en un contador del reporte.
                        run.cortar(ia_budget_message(verdict))
                        drafted = []
                    else:
                        try:
                            drafted = engine.run_reminders(today)
                            # Correos entrantes nuevos → el agente PROPONE la respuesta
                            # (pending_approval, canal correo). Maneja el tope adentro.
                            report["correo_propuestas"] += procesar_correo_pendientes(
                                session, tenant, engine
                            )
                        except BudgetExceeded as exc:
                            # El tope se agotó A MEDIA corrida: lo ya redactado y su uso
                            # quedan registrados (se atrapa dentro del scope, sin rollback).
                            _aviso_tope(session, tenant, str(exc))
                            report["ia_cortada"] += 1
                            run.cortar(str(exc))
                            drafted = []
                    run.contar(propuestos=len(drafted))
                    for r in drafted:
                        run.liga("reminder", r.id, rol="propuso")
                        if r.invoice_id:
                            run.liga("invoice", r.invoice_id, rol="leyo")
                        r.meta = {**(r.meta or {}), "run_id": run.id}
                report["drafted"] += len(drafted)
                auto_aprobados = [r.id for r in drafted if r.status == "approved"]
            # 3) Los auto-aprobados salen por el MISMO camino que todo envío
            #    (candado + marca de en-vuelo + sombra/horario/opt-out), cada uno
            #    en su transacción corta — ya commiteados por la etapa 2, así que
            #    un apagón a media lista no des-redacta nada.
            for reminder_id in auto_aprobados:
                send_reminder_blocking(tenant_id, reminder_id)
                with session_scope() as session:
                    enviado = session.get(Reminder, reminder_id)
                    if enviado is not None and enviado.status == "sent":
                        report["sent"] += 1
                    else:
                        report["send_skipped"] += 1
            # 4) El resumen, solo a la hora que el dueño configuró (o 8:00 por
            #    defecto), también en transacción corta propia. Si esta corrida
            #    salda horas que pasaron con la máquina dormida, basta con que su
            #    hora sea UNA de ellas: el resumen sale tarde, pero sale.
            with session_scope() as session:
                tenant = session.get(Tenant, tenant_id)
                engine = _build_engine(session, tenant)
                wa = resolve_whatsapp(session, tenant)
                if any(engine.summary_due(h) for h in horas):
                    resumen = engine.daily_summary(today)
                    with _pause_for(wa):
                        ok = _safe_send(
                            "resumen al dueño",
                            lambda: engine.send_whatsapp(tenant.owner_phone, resumen),
                        )
                    # El MISMO resumen sale al Slack del negocio si lo conectó
                    # (avisos_equipo); no-op silencioso si no. Cuenta como entregado
                    # si al menos un canal lo sacó.
                    from aiuda_core.connectors.slack import aviso_al_equipo

                    if aviso_al_equipo(session, tenant.id, resumen):
                        ok = True
                    if ok:
                        report["summaries"] += 1
            report["tenants"] += 1
        except Exception as exc:  # noqa: BLE001 — un tenant no debe tumbar la corrida
            log.warning("corrida diaria omitida para tenant %s: %s", tenant_id, exc)
    report["recovered"] = _sweep_pending_sends(current)
    report["aprobados_varados"] = _sweep_stranded_approved(current)
    log.info(
        "corrida diaria: %d tenant(s), %d redactados, %d enviados, %d sin canal, "
        "%d recuperados, %d aprobados varados re-disparados, %d con IA cortada por tope",
        report["tenants"], report["drafted"], report["sent"], report["send_skipped"],
        report["recovered"], report["aprobados_varados"], report["ia_cortada"],
    )
    return report


def _sweep_pending_sends(now: datetime, older_than_min: int = 10, cap: int = 50) -> int:
    """Barrido de recuperación: reintenta los salientes HUMANOS que quedaron en 'pending'
    (el proceso murió antes de obtener veredicto). Solo toca 'pending' con antigüedad >
    older_than_min; los 'failed' NO se reintentan (ya tuvieron veredicto: el dueño decide si
    reenvía). Cada pendiente sale por el canal DE SU hilo: WhatsApp por número, correo por
    SMTP enhebrado (jamás una respuesta de correo por WhatsApp con la clave del hilo).
    Cap por corrida para no inundar. Devuelve cuántos reintentó."""
    cutoff = now - timedelta(minutes=older_than_min)
    with session_scope() as session:
        rows = session.execute(
            select(Message, Conversation)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.direction == "out",
                Message.author == "human",
                Message.delivery == "pending",
                Message.created_at < cutoff,
            )
            .order_by(Message.created_at)
            .limit(cap)
        ).all()
        stuck = [
            (m.tenant_id, m.id, c.id, c.channel or "whatsapp", c.remote_phone, m.body)
            for m, c in rows
        ]
    for tenant_id, message_id, conv_id, channel, phone, body in stuck:
        log.info("barrido: reintento de saliente pendiente %s (%s)", message_id, channel)
        if channel == "correo":
            send_correo_reply_blocking(tenant_id, conv_id, message_id)
        else:
            send_human_message_blocking(tenant_id, phone, body, message_id)
    return len(stuck)


def _sweep_stranded_approved(now: datetime, older_than_min: int = 10, cap: int = 50) -> int:
    """Barrido de aprobados varados: re-dispara el envío de recordatorios 'approved' que
    no salieron (aprobados sin canal conectado, fuera de horario, o el proceso murió).
    Hace verdad la promesa de la UI: "se enviará cuando conectes el canal" — cada corrida
    horaria lo reintenta, y send_reminder_blocking degrada con gracia (sin canal → sigue
    aprobado con su aviso; sombra/fuera de horario → sigue aprobado; solo un intento REAL
    que truena marca 'failed' con motivo). Los 'failed' NO se tocan (ya tuvieron veredicto:
    el dueño decide si reintenta). Guard de antigüedad sobre updated_at para no chocar con
    el envío en background recién agendado por el approve. Devuelve cuántos re-disparó."""
    cutoff = now - timedelta(minutes=older_than_min)
    with session_scope() as session:
        rows = session.execute(
            select(Reminder.tenant_id, Reminder.id)
            .where(
                Reminder.status == "approved",
                Reminder.sent_at.is_(None),
                Reminder.updated_at < cutoff,
            )
            .order_by(Reminder.updated_at)
            .limit(cap)
        ).all()
        # En modo sombra los aprobados se retienen A PROPÓSITO: re-dispararlos solo
        # pausaría el sync de wacli por nada. Se saltan (salen al apagar la sombra).
        sombra: dict[str, bool] = {}
        stuck = []
        for tenant_id, reminder_id in rows:
            if tenant_id not in sombra:
                t = session.get(Tenant, tenant_id)
                sombra[tenant_id] = t is None or bool((t.config or {}).get("modo_sombra"))
            if not sombra[tenant_id]:
                stuck.append((tenant_id, reminder_id))
    for tenant_id, reminder_id in stuck:
        log.info("barrido: reintento de aprobado varado %s", reminder_id)
        send_reminder_blocking(tenant_id, reminder_id)
    return len(stuck)


# La cadencia horaria vive en aiuda_server.scheduler (hilo local, sin Redis):
# llama run_daily_blocking() una vez por hora de reloj y le pasa las horas que la
# máquina se durmió, para que ninguna se pierda.
