"""API local de aiuda.

Regla de la capa: recibir, validar, persistir, responder; el trabajo pesado (LLM)
se procesa INLINE con BackgroundTasks en este mismo proceso, tras responder (cada
tarea abre su propia sesión). La corrida horaria la dispara el scheduler local
(aiuda_server.scheduler). Ver ARCHITECTURE.md.
"""

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from aiuda_core.carrera import nivel_por_acciones
from aiuda_core.cartera.aging import aging_summary, classify
from aiuda_core.config import settings
from aiuda_core.connectors.evolution import parse_webhook
from aiuda_core.connectors.channel import (
    CHANNELS,
    LIVE_CHANNELS,
    live_channels,
    resolve_correo,
    resolve_whatsapp,
)
from aiuda_core.engine import approval
from aiuda_core.learning import learning_summary, record_feedback
from aiuda_core.phones import normalize_mx
from aiuda_core.identity import (
    find_conversation_by_phone,
    resolve_customer_by_email,
    resolve_customer_by_phone,
)
from aiuda_core.models import (
    Appointment,
    Conversation,
    Customer,
    Invoice,
    Message,
    Payment,
    PaymentPromise,
    Product,
    Reminder,
    Tenant,
    UsageEvent,
)

MX_TZ = ZoneInfo("America/Mexico_City")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arranque local: el esquema se materializa idempotente (create_all solo crea
    # lo que falte) — no hay migraciones que correr a mano. El trabajo (mensajes
    # entrantes, envíos) corre INLINE con BackgroundTasks en este mismo proceso,
    # y la corrida horaria la dispara el scheduler local (un hilo, sin Redis).
    from aiuda_core.db import create_all
    from aiuda_server import scheduler

    create_all()
    _purgar_secretos_en_claro()
    if settings.scheduler_enabled:
        scheduler.start()
    _reabrir_red_local(app)
    yield
    scheduler.stop()
    from aiuda_server import red_local

    red_local.escucha.apagar(app)


def _purgar_secretos_en_claro() -> None:
    """Limpia credenciales que quedaron sin cifrar en tenant.config.

    Residuo de un bug sistémico: una llave del catálogo sin entrada en PROVIDERS caía a
    la vía legada y guardaba su secreto en texto plano. Corre en cada arranque porque es
    idempotente y barato, y porque quien actualice desde una versión afectada no va a
    correr un comando de mano. No aborta el arranque si falla: la consola tiene que
    abrir aunque la limpieza no pueda.
    """
    try:
        from aiuda_core.connectors.credentials import purgar_secretos_en_claro
        from aiuda_core.db import get_sessionmaker
        from aiuda_core.optout import migrar_optouts_del_config

        with get_sessionmaker()() as db:
            borrados = purgar_secretos_en_claro(db)
            movidas = migrar_optouts_del_config(db)
            if borrados or movidas:
                db.commit()
            if borrados:
                log.warning(
                    "Se borraron %d credenciales que estaban en texto plano en la config. "
                    "Vuelve a capturarlas desde Integraciones: ahora se guardan cifradas.",
                    borrados,
                )
            if movidas:
                log.info("Se pasaron %d bajas de clientes del config a su tabla.", movidas)
    except Exception:
        log.exception("no se pudo purgar secretos en claro")


def _reabrir_red_local(app: FastAPI) -> None:
    """Si el dueño ya había dejado prendida la red local, se prende sola.

    Es una decisión suya, no una preferencia de la sesión: cerrar la app y volver
    a abrirla no debería dejar a su teléfono afuera sin avisarle.
    """
    app.state.puerto_red_local = None
    try:
        from aiuda_core.db import get_sessionmaker
        from aiuda_server import red_local
        from aiuda_server.api.deps import get_workspace
        from aiuda_server.api.dispositivos import CLAVE_CONFIG

        db = get_sessionmaker()()
        try:
            quiere = bool((get_workspace(db).config or {}).get(CLAVE_CONFIG))
        finally:
            db.close()
        if quiere and red_local.direccion_lan() is not None:
            red_local.escucha.prender(app)
            log.info("red local prendida: tus aparatos pueden llegarle a esta computadora")
    except Exception:  # noqa: BLE001 — sin red local aiuda sirve igual en su computadora
        log.warning("no se pudo prender la red local", exc_info=True)


# Logging estructurado simple: una línea por evento, con timestamp y nivel.
# En desarrollo, stdout basta para diagnosticar sin Sentry.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("aiuda.api")

# Observabilidad opcional: si hay SENTRY_DSN y sentry-sdk instalado, captura errores
# en prod. Seam a prueba de ausencia: sin el paquete o el DSN, no-op (solo stdout).
if settings.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.0,
        )
        log.info("Sentry activado")
    except ImportError:
        log.warning("SENTRY_DSN definido pero sentry-sdk no está instalado; sin captura.")

app = FastAPI(title="aiuda API", version="0.1.0", lifespan=lifespan)

from aiuda_server.api.onboarding import router as onboarding_router  # noqa: E402
from aiuda_server.api.setup import router as setup_router  # noqa: E402
from aiuda_server import audit  # noqa: E402
from aiuda_server.api.audit import router as audit_router  # noqa: E402
from aiuda_server.api.ayudantes import router as ayudantes_router  # noqa: E402
from aiuda_server.api.banco import router as banco_router  # noqa: E402
from aiuda_server.api.cobro import router as cobro_router  # noqa: E402
from aiuda_server.api.cua import router as cua_router  # noqa: E402
from aiuda_server.api.custom_connectors import router as custom_router  # noqa: E402
from aiuda_server.api.deps import (  # noqa: E402  (re-export para tests)
    Principal,
    get_db,
    get_principal,
    get_tenant,
    require_role,
    solo_el_dueno,
)
from aiuda_server.api.dispositivos import router as dispositivos_router  # noqa: E402
from aiuda_server.api.export import router as export_router  # noqa: E402
from aiuda_server.api.integrations import router as integrations_router  # noqa: E402
from aiuda_server.api.prospeccion import router as prospeccion_router  # noqa: E402
from aiuda_server.api.provider import router as provider_router  # noqa: E402
from aiuda_server.api.reconciliation import router as reconciliation_router  # noqa: E402
from aiuda_server.api.sat import router as sat_router  # noqa: E402
from aiuda_server.api.search import router as search_router  # noqa: E402
from aiuda_server.api.tags import router as tags_router  # noqa: E402
from aiuda_server.api.twilio_voz import router as twilio_voz_router  # noqa: E402
from aiuda_server.api.whatsapp import router as whatsapp_router  # noqa: E402
from aiuda_server.api.writeback import router as writeback_router  # noqa: E402

app.include_router(audit_router)
app.include_router(onboarding_router)
app.include_router(setup_router)
app.include_router(ayudantes_router)
app.include_router(banco_router)
app.include_router(cobro_router)
app.include_router(cua_router)
app.include_router(dispositivos_router)
app.include_router(custom_router)
app.include_router(export_router)
app.include_router(integrations_router)
app.include_router(prospeccion_router)
app.include_router(provider_router)
app.include_router(reconciliation_router)
app.include_router(sat_router)
app.include_router(search_router)
app.include_router(tags_router)
app.include_router(twilio_voz_router)
app.include_router(whatsapp_router)
app.include_router(writeback_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,  # desde CORS_ORIGINS; la consola va same-origin
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Request-id + tiempo de respuesta en cada request. Nada de PII en el log."""
    rid = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-Id"] = rid
    log.info(
        "rid=%s %s %s -> %s %.0fms",
        rid, request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


SESSION_COOKIE_LOCAL = "aiuda_local"


# Lo único que se contesta sin llave. `/health` porque es cómo se sabe si aiuda
# está vivo, y el emparejamiento porque el teléfono todavía no tiene ninguna: lo
# que lo protege es el código del QR, que dura cinco minutos y sirve una vez.
_SIN_LLAVE = frozenset({"/health", "/v1/emparejar"})


# Emparejar se contesta sin llave porque el teléfono todavía no tiene ninguna. Eso
# lo vuelve el único punto que cualquiera en el WiFi puede tocar, así que se le
# ponen dos frenos: cuerpo chico y pocos intentos. El código en sí no se puede
# adivinar (72 bits), pero sin esto se puede tumbar la herramienta del negocio.
_MAX_CUERPO_EMPAREJAR = 2048
_INTENTOS_POR_MINUTO = 10
_intentos: dict[str, list[float]] = {}
_candado_intentos = threading.Lock()


def _emparejamiento_razonable(request: Request):
    """None si la petición es razonable; la respuesta de rechazo si no."""
    if request.url.path != "/v1/emparejar":
        return None
    largo = request.headers.get("content-length")
    if largo and largo.isdigit() and int(largo) > _MAX_CUERPO_EMPAREJAR:
        return JSONResponse({"detail": "Esa petición es demasiado grande."}, status_code=413)
    quien = request.client.host if request.client else "?"
    ahora = time.monotonic()
    with _candado_intentos:
        recientes = [t for t in _intentos.get(quien, []) if ahora - t < 60]
        if len(recientes) >= _INTENTOS_POR_MINUTO:
            _intentos[quien] = recientes
            return JSONResponse(
                {"detail": "Demasiados intentos. Espera un minuto."}, status_code=429
            )
        recientes.append(ahora)
        _intentos[quien] = recientes
        if len(_intentos) > 500:  # no crecer sin fin con IPs que ya no vuelven
            _intentos.clear()
            _intentos[quien] = recientes
    return None


def _puede_entrar(aparato, request: Request) -> bool:
    """Qué puede hacer ESTE aparato, no solo si existe.

    El dueño entra a todo. Un invitado solo toca lo DECLARADO en
    ``permisos.INVITADO``: leer el negocio y el trabajo del día (aprobar,
    rechazar, conciliar; el monto lo revisa el endpoint que sabe cuánto es).
    Cerrado por default: un endpoint nuevo no le abre nada a un invitado hasta
    que alguien lo declare a propósito — antes la regla era al revés (cualquier
    POST pasaba) y por ahí un invitado le escribía a los clientes."""
    if aparato.papel == "dueno":
        return True
    from aiuda_server.api import permisos

    return permisos.invitado_puede(app, request)


def _aparato_de(request: Request):
    """El aparato detrás de esta petición, o None si viene de la consola local."""
    crudo = request.headers.get("authorization", "")
    if not crudo.lower().startswith("bearer "):
        return None
    presentado = crudo[7:].strip()
    if not presentado:
        return None
    from sqlalchemy import select

    from aiuda_core.db import get_sessionmaker
    from aiuda_core.models import Dispositivo
    from aiuda_server.api.dispositivos import huella_token

    db = get_sessionmaker()()
    try:
        aparato = db.scalars(
            select(Dispositivo).where(Dispositivo.token_hash == huella_token(presentado))
        ).first()
        if aparato is None or not aparato.activo:
            return None
        # Se desprende de la sesión para poder leerlo después de cerrarla.
        db.expunge(aparato)
        return aparato
    finally:
        db.close()


@app.middleware("http")
async def local_session_guard(request: Request, call_next):
    """Guardia estilo Jupyter: con AIUDA_SESSION_TOKEN puesto (lo genera `aiuda
    start` por arranque), toda petición debe traer la cookie local o el ?token=
    del link que abrió el navegador (que aquí se canjea por cookie). El bind en
    127.0.0.1 aísla de la red; esto aísla de otros procesos/pestañas locales."""
    # Lo que entra por la puerta de la red va aparte y es más estricto: solo pasa
    # con el token de un aparato emparejado. `--no-token` afloja la consola, que
    # es esta computadora hablando consigo misma; jamás la puerta de la calle.
    if request.scope.get("aiuda_puerta") == "red":
        if request.url.path in _SIN_LLAVE:
            respuesta = _emparejamiento_razonable(request)
            return respuesta if respuesta is not None else await call_next(request)
        aparato = _aparato_de(request)
        if aparato is None:
            return JSONResponse(
                {"detail": "Este aparato no está emparejado con esta computadora."},
                status_code=401,
            )
        if not _puede_entrar(aparato, request):
            return JSONResponse(
                {"detail": "Tu aparato no tiene permiso para esto. Pídeselo al dueño."},
                status_code=403,
            )
        request.scope["aiuda_aparato"] = aparato
        return await call_next(request)

    token = settings.session_token
    if not token or request.url.path in _SIN_LLAVE:
        return await call_next(request)
    import hmac as _hmac

    cookie = request.cookies.get(SESSION_COOKIE_LOCAL, "")
    if cookie and _hmac.compare_digest(cookie, token):
        return await call_next(request)
    # Un aparato emparejado trae su propio token. No sirve el de la sesión de la
    # consola: ese cambia en cada arranque y el teléfono del dueño no lo conoce.
    aparato = _aparato_de(request)
    if aparato is not None:
        if not _puede_entrar(aparato, request):
            return JSONResponse(
                {"detail": "Tu aparato no tiene permiso para esto. Pídeselo al dueño."},
                status_code=403,
            )
        request.scope["aiuda_aparato"] = aparato
        return await call_next(request)
    supplied = request.query_params.get("token", "")
    if supplied and _hmac.compare_digest(supplied, token):
        response = await call_next(request)
        response.set_cookie(
            SESSION_COOKIE_LOCAL, token, httponly=True, samesite="lax", path="/"
        )
        return response
    # A una persona se le explica; a un programa se le responde JSON. Quién es
    # quién se decide por la RUTA, no por el encabezado Accept: la ventana de la
    # app no siempre lo manda como uno esperaría, y el dueño terminaba viendo un
    # JSON crudo en su pantalla (pasó de verdad).
    de_programa = request.url.path.startswith("/v1/") or "application/json" in request.headers.get(
        "accept", ""
    )
    if not de_programa:
        return HTMLResponse(_PAGINA_SIN_ACCESO, status_code=401)
    return JSONResponse(
        {"detail": "Falta el token de sesión local. Abre la consola con `aiuda start`."},
        status_code=401,
    )


# Página amable para cuando alguien (o algo) llega sin el token de la sesión:
# la consola no se abre "a secas", y decirlo en JSON no le sirve a nadie.
_PAGINA_SIN_ACCESO = """<!doctype html>
<html lang="es-MX"><head><meta charset="utf-8">
<title>Abre aiuda desde su app</title>
<style>
 :root { color-scheme: light }
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:#fbfcfd;color:#16232b;
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;padding:2rem}
 main{max-width:31rem;text-align:center}
 h1{font-size:1.3rem;margin:0 0 .5rem}
 p{margin:0 0 1rem;color:#46606e}
 code{background:#eef2f5;padding:.15rem .4rem;border-radius:4px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em}
</style></head><body><main>
<h1>Esta ventana no tiene la llave de tu sesión</h1>
<p>Tus datos están a salvo. Por seguridad la consola solo se abre desde aiuda.
Cierra aiuda por completo y vuelve a abrirlo: entrarás directo.</p>
<p>Si ya la tenías abierta en otra ventana, ahí sigue funcionando.</p>
</main></body></html>"""


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Errores no controlados: se registran completos en el servidor, pero al
    cliente solo le llega un mensaje limpio (sin stack traces ni internals)."""
    log.exception("error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocurrió un error interno. Inténtalo de nuevo."},
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "aiuda-api"}


@app.post("/v1/daily/run", status_code=202)
async def daily_run(background: BackgroundTasks):
    """Dispara la corrida de cobranza AHORA (el scheduler local ya la corre cada
    hora; esto es el "no quiero esperar"). Encola y responde de inmediato; el
    trabajo corre en segundo plano y degrada con gracia si no hay canal de envío
    (redacta y deja en Aprobaciones)."""
    from aiuda_server.worker.main import run_daily_blocking

    background.add_task(run_daily_blocking)
    log.info("corrida manual aceptada, corre en segundo plano")
    return {"status": "encolado", "ts": datetime.now(MX_TZ).isoformat()}


def _tenant_de_instancia(db, instance: str) -> Tenant | None:
    """El tenant dueño de una instancia de canal (Tenant.evolution_instance, única)."""
    return db.scalar(select(Tenant).where(Tenant.evolution_instance == instance))


def _tenant_con_whatsapp(db) -> Tenant:
    """Routing legado SIN instancia en el payload (poller viejo, self-host de un solo
    número): exactamente UN tenant con WhatsApp conectado recibe los entrantes; si no
    hay ninguno conectado pero solo existe un tenant, es él. Con más de un candidato
    NO se adivina: entregar la conversación de un cliente al negocio equivocado es
    fuga cross-tenant, así que se rechaza y se pide poller con instancia."""
    tenants = db.scalars(select(Tenant).order_by(Tenant.created_at)).all()
    conectados = [
        t for t in tenants if ((t.config or {}).get("integrations") or {}).get("whatsapp")
    ]
    if len(conectados) == 1:
        return conectados[0]
    if not conectados and len(tenants) == 1:
        return tenants[0]
    if not tenants:
        raise HTTPException(status_code=404, detail="Sin tenant configurado")
    raise HTTPException(
        status_code=409,
        detail=(
            "Routing ambiguo: hay varios negocios con WhatsApp. El poller debe mandar "
            "'instance' (WACLI_INSTANCE) para entregar al negocio correcto."
        ),
    )


@app.post("/v1/webhooks/wacli")
async def wacli_webhook(
    request: Request,
    background: BackgroundTasks,
    token: str = Query(default=""),
    db=Depends(get_db),
):
    """Mensajes entrantes de WhatsApp vía wacli.

    Contrato: {"phone": "5215...", "message": "texto", "id": "opcional",
    "instance": "opcional"}. El daemon de entrada (scripts/wacli_inbound.py) postea
    aquí cada mensaje recibido; con `instance` el mensaje entra al workspace dueño
    de esa instancia. Sin ella se resuelve el único número disponible y se rechaza
    si sería ambiguo.
    """
    if not settings.evolution_webhook_token or token != settings.evolution_webhook_token:
        raise HTTPException(status_code=401, detail="Token de webhook inválido")
    payload = await request.json()
    # Normalizar el teléfono al formato canónico (dígitos país+número) para que la
    # conversación no se duplique por variaciones de formato y el dueño se reconozca.
    phone = normalize_mx(str(payload.get("phone") or "").strip())
    body = str(payload.get("message") or "").strip()
    if not phone or not body:
        return {"status": "ignored"}

    # Routing por instancia: cada mensaje entra a la bandeja del tenant DUEÑO del
    # número que lo recibió, nunca "al que esté conectado" por accidente.
    instance = str(payload.get("instance") or "").strip()
    if instance:
        tenant = _tenant_de_instancia(db, instance)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Instancia sin tenant asignado")
    else:
        tenant = _tenant_con_whatsapp(db)

    # Misma ingesta que el sondeo in-process (aiuda_server.inbound): conversación
    # + dedupe por wa_message_id; el agente procesa tras responder el webhook.
    from aiuda_server.inbound import ingresar_entrante
    from aiuda_server.worker.main import process_incoming_message_blocking

    wa_id = str(payload.get("id") or "") or None
    message = ingresar_entrante(db, tenant, phone=phone, body=body, wa_id=wa_id)
    if message is None:
        return {"status": "duplicate"}
    background.add_task(process_incoming_message_blocking, tenant.id, message.id)
    return {"status": "accepted", "message_id": message.id}


@app.post("/v1/sync")
def sync_now(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Sincroniza las fuentes conectadas respetando "de dónde lee" cada capacidad:
    si el dueño eligió una fuente para su cartera/catálogo/etc., las demás no la pisan."""
    from aiuda_server.api.integrations import fuentes_preferidas
    from aiuda_core.engine.sync import sync_fuentes

    r = sync_fuentes(db, tenant, fuente_prefs=fuentes_preferidas(db, tenant))
    return {
        "pedidos_importados": r.pedidos_importados,
        "pagos_confirmados": r.pagos_confirmados,
        "correos_importados": r.correos_importados,
        "fuentes": r.fuentes,
        # Fuentes que no respondieron o leyeron parcial: se dice, no se esconde.
        "avisos": r.avisos,
    }


@app.post("/v1/webhooks/evolution")
async def evolution_webhook(
    request: Request,
    background: BackgroundTasks,
    token: str = Query(default=""),
    db=Depends(get_db),
):
    if not settings.evolution_webhook_token or token != settings.evolution_webhook_token:
        raise HTTPException(status_code=401, detail="Token de webhook inválido")

    payload = await request.json()
    incoming = parse_webhook(payload)
    if incoming is None or incoming.from_me:
        return {"status": "ignored"}

    tenant = db.scalar(select(Tenant).where(Tenant.evolution_instance == incoming.instance))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Instancia sin tenant asignado")

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id,
            Conversation.remote_phone == incoming.remote_phone,
        )
    )
    if conversation is None:
        conversation = Conversation(tenant_id=tenant.id, remote_phone=incoming.remote_phone)
        db.add(conversation)
        db.flush()

    # Idempotencia: WhatsApp reintenta si no respondemos <5s
    if incoming.wa_message_id:
        duplicate = db.scalar(
            select(Message).where(
                Message.tenant_id == tenant.id,
                Message.wa_message_id == incoming.wa_message_id,
            )
        )
        if duplicate is not None:
            return {"status": "duplicate"}

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
    return {"status": "accepted", "message_id": message.id}


def _available_channels(
    cust: Customer | None,
    recipient_phone: str | None,
    live: set[str] | None = None,
    recipient_email: str | None = None,
) -> list[dict]:
    """Canales por los que se puede enviar este recordatorio: el conector debe
    estar vivo PARA ESTE tenant y el cliente debe tener el dato de contacto
    (teléfono o correo). `live` viene de live_channels(db, tenant) — correo solo
    está vivo si el negocio conectó su cuenta; sin él cae al set estático (compat).
    `recipient_email` cubre trabajos sin factura/cliente ligado (p.ej. la
    respuesta a un hilo de correo trae su destinatario en meta.correo.para).
    Los no disponibles salen 'por conectar' en la UI (connected=False)."""
    has = {
        "phone": bool((cust.phone if cust else None) or recipient_phone),
        "email": bool((cust.email if cust else None) or recipient_email),
    }
    vivos = live if live is not None else LIVE_CHANNELS
    return [
        {
            "key": key,
            "label": meta["label"],
            "connected": (key in vivos) and has.get(meta["recipient_field"], False),
        }
        for key, meta in CHANNELS.items()
    ]


@app.get("/v1/reminders")
def list_reminders(
    status: str = Query(default="pending_approval"),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    rows = db.execute(
        select(Reminder, Invoice, Customer)
        .outerjoin(Invoice, Reminder.invoice_id == Invoice.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(Reminder.tenant_id == tenant.id, Reminder.status == status)
        .order_by(Reminder.created_at.desc())
    ).all()
    vivos = live_channels(db, tenant)  # correo vivo solo si ESTE negocio lo conectó
    return [
        {
            "id": r.id,
            "agent": r.agent,
            "invoice_id": r.invoice_id,
            "title": r.title,
            "folio": inv.folio if inv else None,
            "customer": cust.name if cust else None,
            "customer_id": cust.id if cust else None,
            "customer_phone": cust.phone if cust else r.recipient_phone,
            "customer_email": cust.email if cust else None,
            "amount": float(inv.amount) if inv else None,
            "currency": inv.currency if inv else "MXN",
            "due_date": inv.due_date.isoformat() if inv else None,
            "bucket": r.bucket,
            "tone": r.tone,
            "message": r.message,
            "status": r.status,
            "channel": r.channel or "whatsapp",
            "channels": _available_channels(
                cust, r.recipient_phone, live=vivos,
                recipient_email=((r.meta or {}).get("correo") or {}).get("para"),
            ),
            "correo": (r.meta or {}).get("correo") or None,
            "procedencia": _procedencia_de(r, inv),
            # Qué ayudante del dueño produjo la propuesta (si uno gobierna la
            # aiudita): trazabilidad para quien aprueba, y alimenta su carrera.
            "propuesto_por": (r.meta or {}).get("ayudante_name"),
            "created_at": r.created_at.isoformat(),
            # "Enviados" deriva de aquí: sólo lo que salió de verdad tiene sent_at.
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            # Si el envío se intentó y tronó: el motivo visible (canal caído, sin contacto).
            "motivo_fallo": (r.meta or {}).get("motivo_fallo"),
            # Si se aprobó sin canal conectado: aviso honesto ("se enviará cuando conectes…").
            "pendiente": (r.meta or {}).get("pendiente_canal"),
        }
        for r, inv, cust in rows
    ]


def _procedencia_de(r: Reminder, inv: Invoice | None) -> dict | None:
    """De dónde salió el dato que sustenta este trabajo: si está ligado a una
    factura, su procedencia real (fuente + presencia); si es una cotización u otro,
    la que el agente guardó en meta. Es trazabilidad para quien aprueba."""
    if inv is not None:
        return {
            "que": "Factura de tu cartera",
            "source": inv.source,
            "presence": inv.presence or {},
        }
    return ((r.meta or {}).get("procedencia")) or None


def _get_reminder(db, tenant: Tenant, reminder_id: str) -> Reminder:
    reminder = db.scalar(
        select(Reminder).where(Reminder.tenant_id == tenant.id, Reminder.id == reminder_id)
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    return reminder


class ApproveBody(BaseModel):
    # Texto editado por el humano antes de enviar. Si difiere del borrador, se captura
    # como corrección (señal de aprendizaje). Vacío/igual = se aprueba tal cual.
    message: str | None = None


@app.post("/v1/reminders/{reminder_id}/approve")
async def approve_reminder(
    reminder_id: str,
    request: Request,
    background: BackgroundTasks,
    channel: str = Query(default="whatsapp"),
    body: ApproveBody | None = None,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    reminder = _get_reminder(db, tenant, reminder_id)
    # El canal elegido debe estar disponible; si no, se queda el canal propio del
    # trabajo (una respuesta de correo NUNCA debe caer a WhatsApp por accidente:
    # si su canal no está completo, el envío falla honesto con motivo visible).
    cust = None
    inv = None
    if reminder.invoice_id:
        inv = db.get(Invoice, reminder.invoice_id)
        cust = db.get(Customer, inv.customer_id) if inv else None

    # El tope del aparato, aplicado donde de verdad importa. Antes vivía solo en
    # el modelo y en la pantalla: un invitado podía aprobar cualquier monto.
    monto = float(inv.amount) if inv is not None else None
    if not principal.puede_aprobar(monto):
        raise HTTPException(
            403,
            "Esto pasa del monto que puedes aprobar desde tu aparato. Déjalo para el dueño."
            if monto is not None
            else "Tu aparato no aprueba envíos. Déjalo para el dueño.",
        )
    connected = {
        c["key"]
        for c in _available_channels(
            cust, reminder.recipient_phone, live=live_channels(db, tenant),
            recipient_email=((reminder.meta or {}).get("correo") or {}).get("para"),
        )
        if c["connected"]
    }
    reminder.channel = channel if channel in connected else (reminder.channel or "whatsapp")
    # ¿El humano editó el borrador? Se envía su versión y se guarda la corrección.
    draft_original = reminder.message
    editado = (body.message or "").strip() if body else ""
    if editado and editado != draft_original.strip():
        reminder.message = editado
        decision = "edited"
    else:
        decision = "approved"
    try:
        approval.advance(reminder, "approved")
    except approval.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.flush()
    record_feedback(
        db, tenant, reminder,
        decision=decision, draft_original=draft_original, final_text=reminder.message,
    )
    audit.record(
        db,
        tenant_id=tenant.id,
        action="reminder.approve",
        entity_type="reminder",
        entity_id=reminder.id,
        principal=principal,
        after={"channel": reminder.channel, "status": reminder.status},
        ip=request.client.host if request.client else None,
    )
    # Commit AQUÍ, antes de agendar el envío: el background task corre en su propia sesión
    # y DEBE ver "approved". Si solo se flushea, el envío lee el estado viejo y falla con
    # InvalidTransition; peor, esa excepción propagaba y hacía rollback del approved, dejando
    # el recordatorio atorado en pending_approval (nunca salía ni desaparecía). Commitear lo
    # hace durable y visible pase lo que pase con el envío.
    db.commit()
    from aiuda_server.worker.main import pendiente_canal_msg, send_reminder_blocking

    background.add_task(send_reminder_blocking, tenant.id, reminder.id)
    # La respuesta refleja el estado FINAL honesto. ¿El canal elegido está REALMENTE
    # conectado para este negocio? No basta con que el cliente tenga teléfono: WhatsApp
    # figura como "vivo" siempre, pero sin emparejar no envía. La señal de verdad es el
    # resolver del canal. Sin canal: el recordatorio queda APROBADO y saldrá cuando el
    # dueño lo conecte (el envío en segundo plano lo deja aprobado con su aviso, NO
    # 'failed'). Con canal listo: va encolado y el veredicto llega en segundo plano.
    if reminder.channel == "correo":
        canal_listo = resolve_correo(db, tenant) is not None
    else:
        canal_listo = resolve_whatsapp(db, tenant) is not None
    return {
        "id": reminder.id,
        "status": reminder.status,
        "channel": reminder.channel,
        "delivery": "encolado" if canal_listo else "pendiente_canal",
        "aviso": None if canal_listo else pendiente_canal_msg(reminder.channel),
    }


@app.post("/v1/reminders/{reminder_id}/send")
async def send_reminder_now(
    reminder_id: str,
    request: Request,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Re-dispara el envío de un recordatorio YA aprobado que no salió (quedó retenido
    por modo prueba, fuera de horario, o el envío en segundo plano no completó).

    No cambia de estado: 'approved' es justamente el estado de entrada de
    send_reminder_blocking, que respeta sombra/horario/canal. Rescata aprobados
    varados sin re-aprobar (approved→approved no es transición válida). El envío real
    ocurre en el background y sigue respetando el modo prueba: si la sombra está
    encendida, se retiene igual (no sale nada)."""
    reminder = _get_reminder(db, tenant, reminder_id)
    if reminder.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Solo se puede enviar un recordatorio aprobado que aún no salió.",
        )
    audit.record(
        db,
        tenant_id=tenant.id,
        action="reminder.send",
        entity_type="reminder",
        entity_id=reminder.id,
        principal=principal,
        after={"channel": reminder.channel, "status": reminder.status},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    from aiuda_server.worker.main import send_reminder_blocking

    background.add_task(send_reminder_blocking, tenant.id, reminder.id)
    return {"id": reminder.id, "status": reminder.status, "channel": reminder.channel}


@app.post("/v1/reminders/{reminder_id}/reject")
def reject_reminder(
    reminder_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    reminder = _get_reminder(db, tenant, reminder_id)
    try:
        approval.advance(reminder, "rejected")
    except approval.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    record_feedback(
        db, tenant, reminder,
        decision="rejected", draft_original=reminder.message, final_text=None,
    )
    audit.record(
        db,
        tenant_id=tenant.id,
        action="reminder.reject",
        entity_type="reminder",
        entity_id=reminder.id,
        principal=principal,
        after={"status": reminder.status},
    )
    return {"id": reminder.id, "status": reminder.status}


@app.get("/v1/learning/summary")
def learning_summary_endpoint(
    agent: str = Query(default="mariana"),
    ayudante_id: str | None = Query(default=None),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Qué está aprendiendo el ayudante: tasa de aprobación sin editar y últimas
    correcciones. Con ``ayudante_id`` son las de ESE ayudante (atribución real por
    Reminder.meta); sin él, las del slug de runtime."""
    return learning_summary(db, tenant, agent=agent, ayudante_id=ayudante_id)


@app.get("/v1/cartera")
def cartera(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Resumen para el dashboard: aging + métrica estrella ($ recuperado del mes)."""
    today = datetime.now(MX_TZ).date()
    open_invoices = db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.status == "open")
    ).all()
    summary = aging_summary(open_invoices, today)

    # $ recuperado este mes = facturas pagadas este mes que recibieron ≥1 recordatorio enviado
    paid_this_month = db.execute(
        select(Invoice).where(
            Invoice.tenant_id == tenant.id,
            Invoice.status == "paid",
            Invoice.paid_at.isnot(None),
        )
    ).scalars()
    recovered = 0.0
    for inv in paid_this_month:
        if inv.paid_at.year != today.year or inv.paid_at.month != today.month:
            continue
        sent = db.scalar(
            select(Reminder).where(
                Reminder.tenant_id == tenant.id,
                Reminder.invoice_id == inv.id,
                Reminder.status == "sent",
            )
        )
        if sent is not None:
            recovered += float(inv.amount)

    pending_count = db.scalars(
        select(Reminder).where(
            Reminder.tenant_id == tenant.id, Reminder.status == "pending_approval"
        )
    ).all()
    promises = db.scalars(
        select(PaymentPromise).where(
            PaymentPromise.tenant_id == tenant.id, PaymentPromise.fulfilled.is_(False)
        )
    ).all()
    by_source: dict[str, int] = {}
    reported = 0
    for inv in open_invoices:
        by_source[inv.source] = by_source.get(inv.source, 0) + 1
        if inv.payment_reported:
            reported += 1
    return {
        "business_name": tenant.name,
        "today": today.isoformat(),
        "recovered_this_month": recovered,
        "open_total": sum(float(i.amount) for i in open_invoices),
        "open_count": len(open_invoices),
        "pending_approvals": len(pending_count),
        "active_promises": len(promises),
        "payment_reports": reported,
        "by_source": by_source,
        "aging": [
            {"bucket": str(b), "count": line.count, "total": line.total}
            for b, line in summary.items()
        ],
    }


# ---------- Agentes: la plataforma es modular; cada tenant activa los suyos ----------

KNOWN_AGENTS = ["mariana", "carlos", "lupita", "valeria", "diego", "roberto", "memo", "sofia"]


def _active_agents(tenant: Tenant) -> list[str]:
    return (tenant.config or {}).get("active_agents", ["mariana"])


def _update_config(db, tenant: Tenant, **changes) -> None:
    # Las columnas JSON no trackean mutación in-place: reasignar siempre.
    tenant.config = {**(tenant.config or {}), **changes}
    db.add(tenant)


@app.get("/v1/agents")
def list_agents(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Estado del equipo. `actions` acumula el trabajo del agente: con el tiempo
    sube de nivel — la antigüedad se nota (ver pitch: plan de carrera del agente)."""
    active = _active_agents(tenant)
    out = []
    for slug in KNOWN_AGENTS:
        is_active = slug in active
        pending = sent = actions = 0
        if is_active:
            pending = int(
                db.scalar(
                    select(func.count(Reminder.id)).where(
                        Reminder.tenant_id == tenant.id,
                        Reminder.agent == slug,
                        Reminder.status == "pending_approval",
                    )
                )
                or 0
            )
            sent = int(
                db.scalar(
                    select(func.count(Reminder.id)).where(
                        Reminder.tenant_id == tenant.id,
                        Reminder.agent == slug,
                        Reminder.status == "sent",
                    )
                )
                or 0
            )
            actions = pending + sent
            if slug == "mariana":
                actions += int(
                    db.scalar(
                        select(func.count(Message.id)).where(
                            Message.tenant_id == tenant.id,
                            Message.direction == "out",
                            Message.author == "agent",
                        )
                    )
                    or 0
                )
                actions += int(
                    db.scalar(
                        select(func.count(PaymentPromise.id)).where(
                            PaymentPromise.tenant_id == tenant.id
                        )
                    )
                    or 0
                )
        out.append(
            {
                "slug": slug,
                "active": is_active,
                "actions": actions,
                "pending": pending,
                "sent": sent,
                # Plan de carrera: el nivel se deriva de las acciones reales de arriba
                # (conteos de filas), en el backend — una sola escala para todos.
                "nivel": nivel_por_acciones(actions),
            }
        )
    return out


@app.post("/v1/agents/{slug}/activate")
def activate_agent(slug: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    if slug not in KNOWN_AGENTS:
        raise HTTPException(status_code=404, detail="Agente desconocido")
    active = _active_agents(tenant)
    if slug not in active:
        _update_config(db, tenant, active_agents=[*active, slug])
    return {"slug": slug, "active": True}


@app.post("/v1/agents/{slug}/deactivate")
def deactivate_agent(slug: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    if slug == "mariana":
        raise HTTPException(status_code=409, detail="Cobranza es tu agente base en el piloto")
    active = [a for a in _active_agents(tenant) if a != slug]
    _update_config(db, tenant, active_agents=active)
    return {"slug": slug, "active": False}


# Saneo de salida (cero emojis, sin markdown). Vive en api/text.py para que el chat
# de ayudantes lo reuse sin import circular con main.
from aiuda_server.api.text import plain_text as _plain_text  # noqa: E402


class AgentChatTurn(BaseModel):
    role: str  # "user" | "agent"
    body: str


class AgentChatBody(BaseModel):
    message: str
    history: list[AgentChatTurn] = []


@app.post("/v1/agents/{slug}/chat")
def agent_chat(
    slug: str,
    body: AgentChatBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Hablar con un agente (aiudante). El dueño le pregunta o le da contexto;
    el agente responde con su persona. Soberanía humana: el agente no envía nada
    a clientes desde aquí, solo conversa y propone."""
    from aiuda_server.api.integrations import AGENT_META

    if slug not in AGENT_META:
        raise HTTPException(status_code=404, detail="Agente desconocido.")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")

    from aiuda_core.engine.provider import resolve_credential

    name, role = AGENT_META[slug]
    credential = resolve_credential(session=db, tenant_id=tenant.id)
    if credential is None:
        return {
            "reply": f"Soy tu asistente de {role}. Para que pueda responderte, "
            "conecta tu proveedor de IA en /proveedor. Mientras, sigo registrando todo."
        }

    # Chat por rol/plantilla: usa el MISMO motor capability-first que el chat de un
    # ayudante (un solo sistema de chat). El rol se mapea a las aiuditas de chat de su
    # perfil; las reglas del dueño viven en config a nivel tenant (agent_config[slug]).
    from aiuda_core.aiuditas.chat import (
        AyudanteChatExecutor,
        PERSONA_PERFIL,
        chat_aiuditas_de_perfil,
        chat_system_prompt,
        chat_tools,
    )
    from aiuda_server.metering import BudgetExceeded, tenant_runner

    perfil = PERSONA_PERFIL.get(slug)
    aiudita_ids = chat_aiuditas_de_perfil(perfil) if perfil else []
    active = {aid: {} for aid in aiudita_ids}
    system = chat_system_prompt(name, tenant.name, active)
    user_rules = ((tenant.config or {}).get("agent_config") or {}).get(slug, {}).get("user_rules") or []
    if user_rules:
        system += "\n\nReglas que te puso el dueño (respétalas siempre):\n" + "\n".join(
            f"- {r}" for r in user_rules
        )
    turns = "\n".join(
        f"{'Dueño' if t.role == 'user' else name}: {t.body}" for t in body.history[-8:]
    )
    user = (f"{turns}\n" if turns else "") + f"Dueño: {body.message.strip()}\n{name}:"

    # Runner con metering (UsageEvent por llamada) y tope de gasto enganchados.
    runner = tenant_runner(db, tenant)
    tools = chat_tools(aiudita_ids)
    try:
        if tools:
            reply = runner.run_tool_loop(
                system=system,
                user_message=user,
                tools=tools,
                execute_tool=AyudanteChatExecutor(db, tenant, aiudita_ids),
                role="redaccion",
                task="agent_chat",
                max_iterations=6,
            )
        else:
            reply = runner.complete(
                system=system, user=user, role="redaccion", task="agent_chat", max_tokens=400
            )
    except BudgetExceeded as exc:
        # Corte honesto: el tope del mes se alcanzó; no se llamó a la IA.
        raise HTTPException(status_code=402, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="El asistente no está disponible ahora.")
    db.flush()
    return {"reply": _plain_text(reply) or "…"}


class AgentConfigBody(BaseModel):
    user_rules: list[str] | None = None
    auto_send_buckets: list[str] | None = None
    business_context: str | None = None


@app.get("/v1/agents/{slug}/config")
def get_agent_config(slug: str, tenant: Tenant = Depends(get_tenant)):
    config = tenant.config or {}
    agent_config = (config.get("agent_config") or {}).get(slug, {})
    return {
        "slug": slug,
        "user_rules": agent_config.get("user_rules", []),
        "auto_send_buckets": config.get("auto_send_buckets", []),
        "business_context": config.get("business_context", ""),
    }


@app.put("/v1/agents/{slug}/config")
def put_agent_config(
    slug: str,
    body: AgentConfigBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """La configuración que ves es la que el agente usa: las reglas del usuario se
    inyectan al system prompt (encima de los safeguards de fábrica, nunca en lugar de)."""
    config = dict(tenant.config or {})
    agent_config = dict(config.get("agent_config") or {})
    mine = dict(agent_config.get(slug) or {})
    if body.user_rules is not None:
        mine["user_rules"] = [r.strip() for r in body.user_rules if r.strip()][:12]
    agent_config[slug] = mine
    changes: dict = {"agent_config": agent_config}
    if body.auto_send_buckets is not None:
        changes["auto_send_buckets"] = [b for b in body.auto_send_buckets if b != "critica"]
    if body.business_context is not None:
        changes["business_context"] = body.business_context.strip()
    _update_config(db, tenant, **changes)
    return get_agent_config(slug, tenant)


class ShadowBody(BaseModel):
    activo: bool


@app.get("/v1/settings/modo-sombra")
def get_shadow_mode(tenant: Tenant = Depends(get_tenant)):
    """Modo sombra: el negocio redacta y aprueba pero NO envía a clientes reales."""
    return {"modo_sombra": bool((tenant.config or {}).get("modo_sombra"))}


@app.put("/v1/settings/modo-sombra")
def put_shadow_mode(
    body: ShadowBody,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    """Activa/desactiva el modo sombra. Con él encendido nada sale por WhatsApp: lo
    redactado queda en Aprobaciones para revisar (semana de validación con datos reales)."""
    _update_config(db, tenant, modo_sombra=body.activo)
    audit.record(
        db,
        tenant_id=tenant.id,
        action="settings.modo_sombra",
        entity_type="tenant",
        entity_id=tenant.id,
        principal=principal,
        after={"modo_sombra": body.activo},
        ip=request.client.host if request.client else None,
    )
    return {"modo_sombra": body.activo}


class VentanaEnvioBody(BaseModel):
    ventana: str  # "HH:MM-HH:MM" o "" (sin restricción)


@app.get("/v1/settings/ventana-envio")
def get_ventana_envio(tenant: Tenant = Depends(get_tenant)):
    """No-molestar del negocio: franja (hora de México) en la que SÍ se envía. Fuera
    de ella los envíos automatizados esperan a la siguiente corrida dentro de horario."""
    return {"ventana": (tenant.config or {}).get("ventana_envio", "")}


@app.put("/v1/settings/ventana-envio")
def put_ventana_envio(
    body: VentanaEnvioBody,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    """Fija la ventana global de envío ('09:00-20:00'; vacío = sin restricción). La
    perilla de la aiudita de cobranza, si el dueño la configuró, sigue mandando."""
    from aiuda_core.engine.engine import _parse_window

    raw = (body.ventana or "").strip()
    if raw and _parse_window(raw) is None:
        raise HTTPException(
            status_code=422,
            detail="Formato inválido. Usa HH:MM-HH:MM (ej. 09:00-20:00) o deja vacío.",
        )
    _update_config(db, tenant, ventana_envio=raw)
    audit.record(
        db,
        tenant_id=tenant.id,
        action="settings.ventana_envio",
        entity_type="tenant",
        entity_id=tenant.id,
        principal=principal,
        after={"ventana_envio": raw},
        ip=request.client.host if request.client else None,
    )
    return {"ventana": raw}


# ---------- Import inteligente: nos adaptamos a tu Excel ----------


@app.post("/v1/import")
async def smart_import_endpoint(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Importador universal: detecta si el archivo trae facturas, clientes,
    productos, citas o prospectos, y lo carga a su lugar."""
    from aiuda_server.metering import BudgetExceeded, tenant_runner
    from aiuda_core.connectors.smart_import import smart_import

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo mayor a 5 MB")

    runner = tenant_runner(db, tenant)
    try:
        report = smart_import(db, tenant.id, content, file.filename or "archivo.csv", runner=runner)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="No pude leer el archivo (¿es CSV o XLSX?)")
    return {
        "filename": file.filename,
        "entity": report.entity,
        "entity_label": report.entity_label,
        "mapping": report.mapping,
        "created": report.created,
        "skipped": report.skipped,
        "errors": report.errors[:5],
    }


@app.post("/v1/import/analyze")
async def import_analyze(
    file: UploadFile = File(...),
    entity: str | None = Form(None),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Paso 1 del uploader: propone tipo + mapeo sin importar nada. Devuelve las
    columnas del usuario, una muestra, el mapeo propuesto y los tipos válidos."""
    from aiuda_server.metering import BudgetExceeded, tenant_runner
    from aiuda_core.connectors.smart_import import ENTITY_FIELDS, ENTITY_LABEL, analyze

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo mayor a 5 MB")

    runner = tenant_runner(db, tenant)
    try:
        result = analyze(content, file.filename or "archivo.csv", runner=runner, entity=entity or None)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="No pude leer el archivo (¿es CSV o XLSX?)")
    result["filename"] = file.filename
    result["types"] = [{"key": k, "label": ENTITY_LABEL[k]} for k in ENTITY_FIELDS]
    return result


@app.post("/v1/import/commit")
async def import_commit(
    file: UploadFile = File(...),
    entity: str = Form(...),
    mapping: str = Form("{}"),
    extras: str = Form("[]"),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Paso 2 del uploader: importa con el mapeo que confirmó el usuario."""
    import json as _json

    from aiuda_core.connectors.smart_import import commit

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo mayor a 5 MB")
    try:
        mapping_obj = _json.loads(mapping)
        extras_obj = _json.loads(extras)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Mapeo inválido.")
    report = commit(
        db, tenant.id, content, file.filename or "archivo.csv", entity, mapping_obj, extras_obj
    )
    return {
        "filename": file.filename,
        "entity": report.entity,
        "entity_label": report.entity_label,
        "created": report.created,
        "skipped": report.skipped,
        "errors": report.errors[:5],
    }


# ---------- Conversaciones: el humano entra cuando quiere ----------


class TakeoverBody(BaseModel):
    takeover: bool


@app.post("/v1/conversations/{conversation_id}/takeover")
def conversation_takeover(
    conversation_id: str,
    body: TakeoverBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    conv = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.id == conversation_id
        )
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    conv.human_takeover = body.takeover
    return {"id": conv.id, "human_takeover": conv.human_takeover}


class HumanMessageBody(BaseModel):
    body: str


def _correo_hilo_info(tenant: Tenant, conv: Conversation) -> dict | None:
    """Metadatos del hilo si la conversación es de correo (remitente, nombre, asunto);
    None para WhatsApp/SMS. Viven en Tenant.config['correo_hilos'] (sin migración)."""
    if conv.channel != "correo":
        return None
    from aiuda_core.engine.correo import hilo_meta

    meta = hilo_meta(tenant, conv.id)
    return {
        "de": meta.get("de", ""),
        "nombre": meta.get("nombre", ""),
        "asunto": meta.get("asunto", ""),
    }


def _customer_de_conversacion(db, tenant: Tenant, conv: Conversation) -> Customer | None:
    """El cliente del hilo, según el canal: por teléfono (match_key) en WhatsApp,
    por el remitente (email) en correo."""
    if conv.channel == "correo":
        correo = (_correo_hilo_info(tenant, conv) or {}).get("de", "")
        return resolve_customer_by_email(db, tenant.id, correo)
    return resolve_customer_by_phone(db, tenant.id, conv.remote_phone)


@app.post("/v1/conversations/{conversation_id}/messages")
def send_human_message(
    conversation_id: str,
    payload: HumanMessageBody,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(solo_el_dueno),
):
    """Mensaje del humano en el hilo. Se guarda y responde al instante; el envío
    (WhatsApp, o SMTP con Re:/threading si el hilo es de correo) corre en segundo
    plano. Siempre queda en el historial."""
    conv = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.id == conversation_id
        )
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")
    message = Message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        direction="out",
        author="human",
        body=payload.body.strip(),
        delivery="pending",  # el background lo marca sent/failed; el barrido rescata pendientes
    )
    db.add(message)
    db.flush()
    # Bitácora: un mensaje saliente a un cliente es acción soberana (quién habló
    # en nombre del negocio, a qué hilo). El cuerpo no se guarda: ya vive en el hilo.
    audit.record(
        db,
        tenant_id=tenant.id,
        action="message.send",
        entity_type="conversation",
        entity_id=conv.id,
        principal=principal,
        after={"message_id": message.id, "channel": conv.channel},
    )
    from aiuda_server.worker.main import send_correo_reply_blocking, send_human_message_blocking

    if conv.channel == "correo":
        # Commit explícito ANTES de agendar: la tarea re-lee el mensaje en su propia
        # sesión y las BackgroundTasks corren antes del commit del teardown de get_db
        # (FastAPI 0.136) — sin esto, leería el estado viejo.
        db.commit()
        background.add_task(send_correo_reply_blocking, tenant.id, conv.id, message.id)
    else:
        background.add_task(
            send_human_message_blocking, tenant.id, conv.remote_phone, message.body, message.id
        )
    return {"id": message.id, "author": "human", "body": message.body, "queued": True}


@app.post("/v1/conversations/{conversation_id}/messages/{message_id}/resend")
def resend_message(
    conversation_id: str,
    message_id: str,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(solo_el_dueno),
):
    """Reintenta un saliente tuyo que quedó sin enviarse (delivery=failed/pending). Lo vuelve
    a poner en 'pending' y reencola el envío; el mismo mensaje, no uno nuevo."""
    message = db.scalar(
        select(Message).where(
            Message.tenant_id == tenant.id,
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    if message.direction != "out" or message.author != "human":
        raise HTTPException(status_code=400, detail="Solo puedes reintentar tus propios mensajes.")
    conv = db.get(Conversation, conversation_id)
    message.delivery = "pending"
    db.add(message)
    db.flush()
    from aiuda_server.worker.main import send_correo_reply_blocking, send_human_message_blocking

    if conv.channel == "correo":
        db.commit()  # la tarea re-lee el mensaje; ver send_human_message
        background.add_task(send_correo_reply_blocking, tenant.id, conv.id, message.id)
    else:
        background.add_task(
            send_human_message_blocking, tenant.id, conv.remote_phone, message.body, message.id
        )
    return {"id": message.id, "delivery": "pending"}


@app.get("/v1/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    conv = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id, Conversation.id == conversation_id
        )
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    customer = _customer_de_conversacion(db, tenant, conv)
    messages = db.scalars(
        select(Message)
        .where(Message.tenant_id == tenant.id, Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    ).all()
    return {
        "id": conv.id,
        "remote_phone": conv.remote_phone,
        "channel": conv.channel or "whatsapp",
        "correo": _correo_hilo_info(tenant, conv),  # remitente/nombre/asunto del hilo
        "customer": customer.name if customer else None,
        "customer_id": customer.id if customer else None,
        "human_takeover": conv.human_takeover,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "author": m.author,
                "body": m.body,
                "delivery": m.delivery,  # sent | failed | pending | null (entrante/sin rastreo)
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@app.post("/v1/invoices/{invoice_id}/pay")
def register_payment(
    invoice_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.id == invoice_id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    if invoice.status == "paid":
        raise HTTPException(status_code=409, detail="La factura ya está pagada")
    # Dar una factura por pagada es cerrar dinero y devolverlo a la fuente: pesa
    # igual que aprobar un envío, así que el tope del aparato manda igual. Faltaba
    # aquí: un invitado con tope de 5 mil podía cerrar una de 95 mil.
    if not principal.puede_aprobar(float(invoice.amount)):
        raise HTTPException(
            403,
            "Esta factura pasa del monto que puedes dar por pagado desde tu aparato. "
            "Déjala para el dueño.",
        )
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)  # UTC como todo lo demás
    invoice.paid_source = "manual"  # confirmado por el negocio; "banco" cuando esté Belvo
    invoice.payment_reported = False
    # Write-back: el pago se inyecta de regreso al sistema de origen
    from aiuda_core.engine.writeback import queue_payment_writeback

    queue_payment_writeback(db, tenant, invoice)
    return {"id": invoice.id, "status": invoice.status, "paid_source": invoice.paid_source}


@app.post("/v1/invoices/{invoice_id}/remind")
def draft_reminder_now(
    invoice_id: str,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Pide a Mariana redactar un recordatorio para esta factura ahora.

    MVP: redacta síncrono en el request. Si algún día hace falta encolarlo,
    el contrato no cambia (ver ARCHITECTURE.md).
    """
    from aiuda_core.engine.engine import CleoEngine

    invoice = db.scalar(
        select(Invoice).where(
            Invoice.tenant_id == tenant.id, Invoice.id == invoice_id, Invoice.status == "open"
        )
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Factura abierta no encontrada")
    active = db.scalar(
        select(Reminder).where(
            Reminder.tenant_id == tenant.id,
            Reminder.invoice_id == invoice.id,
            Reminder.status.in_(["draft", "pending_approval", "approved"]),
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="Ya hay un recordatorio activo")
    customer = db.scalar(select(Customer).where(Customer.id == invoice.customer_id))
    today = datetime.now(MX_TZ).date()
    engine = CleoEngine(db, tenant)
    # Tope de gasto de IA: mismo corte que la corrida diaria (ver aiuda_server.metering).
    from aiuda_server.metering import BudgetExceeded, budget_check

    engine.runner.budget_check = budget_check(db, tenant)
    try:
        reminder = engine.draft_reminder(invoice, customer, today)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No pude redactar: {exc}")
    # Si el auto-envío del tenant lo dejó ya aprobado, hay que encolar el envío: si no,
    # la corrida diaria lo ve "activo" y lo salta, y queda approved para siempre sin salir.
    if reminder.status == "approved":
        db.flush()
        from aiuda_server.worker.main import send_reminder_blocking

        background.add_task(send_reminder_blocking, tenant.id, reminder.id)
    return {"id": reminder.id, "status": reminder.status, "message": reminder.message}


@app.post("/v1/promises/{promise_id}/fulfill")
def fulfill_promise(
    promise_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    promise = db.scalar(
        select(PaymentPromise).where(
            PaymentPromise.tenant_id == tenant.id, PaymentPromise.id == promise_id
        )
    )
    if promise is None:
        raise HTTPException(status_code=404, detail="Promesa no encontrada")
    promise.fulfilled = True
    promise.fulfilled_at = datetime.now(timezone.utc)  # UTC como todo lo demás
    return {"id": promise.id, "fulfilled": True}


@app.get("/v1/promises")
def list_promises(
    status: str = Query(default="active"),  # active | fulfilled
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    today = datetime.now(MX_TZ).date()
    query = (
        select(PaymentPromise, Invoice, Customer)
        .join(Invoice, PaymentPromise.invoice_id == Invoice.id)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            PaymentPromise.tenant_id == tenant.id,
            PaymentPromise.fulfilled.is_(status == "fulfilled"),
        )
        .order_by(PaymentPromise.promised_date.desc() if status == "fulfilled" else PaymentPromise.promised_date)
    )
    return [
        {
            "id": p.id,
            "invoice_id": inv.id,
            "folio": inv.folio,
            "customer": cust.name,
            "customer_id": cust.id,
            "amount": float(inv.amount),
            "promised_date": p.promised_date.isoformat(),
            "note": p.note,
            "days_left": (p.promised_date - today).days,
            "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
        }
        for p, inv, cust in db.execute(query).all()
    ]


@app.get("/v1/customers")
def list_customers(
    kind: str | None = Query(default=None),  # cliente | prospecto | None (todos)
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    query = select(Customer).where(Customer.tenant_id == tenant.id)
    if kind in ("cliente", "prospecto"):
        query = query.where(Customer.kind == kind)
    customers = db.scalars(query.order_by(Customer.name)).all()
    from aiuda_core.optout import claves_dadas_de_baja, contact_key

    # En una consulta, no una por cliente: esta lista ya arrastra un N+1 por el conteo
    # de facturas y no hay por qué agregarle otro.
    bajas = claves_dadas_de_baja(db, tenant)

    out = []
    for cust in customers:
        open_rows = db.execute(
            select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.tenant_id == tenant.id,
                Invoice.customer_id == cust.id,
                Invoice.status == "open",
            )
        ).one()
        out.append(
            {
                "id": cust.id,
                "name": cust.name,
                "phone": cust.phone,
                "open_invoices": int(open_rows[0]),
                "open_total": float(open_rows[1]),
                "tags": cust.tags or [],
                "kind": cust.kind or "cliente",
                # Quién pidió que no lo contacten. Sin esto, la lista no tiene
                # forma de saberlo y una app puede ofrecer escribirle a alguien
                # que ya dijo que no. La ficha sí lo mandaba; la lista no.
                "opt_out": bool(cust.phone) and contact_key(cust.phone) in bajas,
                "meta": cust.meta or {},
            }
        )
    return out


@app.get("/v1/products")
def list_products(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Catálogo del negocio. Lo alimenta el importador (y después tienda/ERP)."""
    rows = db.scalars(
        select(Product).where(Product.tenant_id == tenant.id).order_by(Product.name)
    ).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "price": float(p.price) if p.price is not None else None,
            "stock": float(p.stock) if p.stock is not None else None,
            "unit": p.unit,
            "source": p.source,
            "meta": p.meta or {},
            "presence": p.presence or {},
        }
        for p in rows
    ]


class QuoteItemBody(BaseModel):
    product_id: str
    cantidad: float = 1


class QuoteCreateBody(BaseModel):
    customer_id: str
    items: list[QuoteItemBody]
    descuento_pct: float = 0


@app.post("/v1/quotes", status_code=201)
def create_quote(
    body: QuoteCreateBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Genera una cotización (Ventas) con precios reales del catálogo, respetando las
    perillas del ayudante (vigencia, IVA, tope de descuento, reglas). Queda en la
    bandeja de Aprobaciones; aprobarla y enviarla reusa el flujo de recordatorios."""
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if not body.items:
        raise HTTPException(status_code=400, detail="Agrega al menos un producto")

    from aiuda_server.metering import tenant_runner
    from aiuda_core.agents.carlos.engine import CarlosEngine, QuoteError
    from aiuda_core.engine.llm import BudgetExceeded

    # Mismo contrato que el resto de los caminos de IA: el runner lleva tope
    # enganchado — construirlo a mano se salta el corte.
    engine = CarlosEngine(db, tenant, runner=tenant_runner(db, tenant))
    try:
        reminder = engine.draft_quote(
            customer,
            [it.model_dump() for it in body.items],
            descuento_pct=body.descuento_pct,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except QuoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.flush()
    return {
        "id": reminder.id,
        "title": reminder.title,
        "message": _plain_text(reminder.message),
        "status": reminder.status,
    }


@app.get("/v1/appointments")
def list_appointments(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Agenda del negocio. La atiende Valeria. La alimenta el importador (y
    después Google Calendar)."""
    rows = db.scalars(
        select(Appointment)
        .where(Appointment.tenant_id == tenant.id)
        .order_by(Appointment.starts_at.is_(None), Appointment.starts_at)
    ).all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "customer_name": a.customer_name,
            "customer_phone": a.customer_phone,
            "starts_at": a.starts_at.isoformat() if a.starts_at else None,
            "notes": a.notes,
            # Procedencia: la cita también sabe de dónde vino (excel, googlecalendar,
            # una conexión a la medida). Appointment no tiene presence; source basta.
            "source": a.source,
            "meta": a.meta or {},
        }
        for a in rows
    ]


def _conversation_messages(db, tenant: Tenant, conv: Conversation | None) -> list:
    if conv is None:
        return []
    msgs = db.scalars(
        select(Message)
        .where(Message.tenant_id == tenant.id, Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    ).all()
    return [
        {
            "id": m.id,
            "direction": m.direction,
            "author": m.author,
            "body": m.body,
            "delivery": m.delivery,  # sent | failed | pending | null (entrante/sin rastreo)
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


@app.get("/v1/customers/{customer_id}")
def customer_detail(
    customer_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Detalle del cliente: sus datos, sus facturas y el hilo de conversación
    (para escribirle desde aquí mismo)."""
    today = datetime.now(MX_TZ).date()
    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.tenant_id == tenant.id, Invoice.customer_id == cust.id)
        .order_by(Invoice.due_date)
    ).all()
    conv = find_conversation_by_phone(db, tenant.id, cust.phone)
    open_total = sum(float(i.amount) for i in invoices if i.status == "open")

    # El 360: todo lo que cuelga del cliente, no solo sus facturas. Colgado de sus facturas
    # (recordatorios, promesas, pagos conciliados) y de su nombre (citas).
    inv_ids = [i.id for i in invoices]
    folio_by_id = {i.id: i.folio for i in invoices}
    reminders = (
        db.scalars(
            select(Reminder)
            .where(Reminder.tenant_id == tenant.id, Reminder.invoice_id.in_(inv_ids))
            .order_by(Reminder.created_at.desc())
            .limit(12)
        ).all()
        if inv_ids
        else []
    )
    promises = (
        db.scalars(
            select(PaymentPromise)
            .where(PaymentPromise.tenant_id == tenant.id, PaymentPromise.invoice_id.in_(inv_ids))
            .order_by(PaymentPromise.promised_date.desc())
        ).all()
        if inv_ids
        else []
    )
    payments = (
        db.scalars(
            select(Payment)
            .where(Payment.tenant_id == tenant.id, Payment.invoice_id.in_(inv_ids))
            .order_by(Payment.paid_at.desc())
        ).all()
        if inv_ids
        else []
    )
    citas = db.scalars(
        select(Appointment)
        .where(Appointment.tenant_id == tenant.id, Appointment.customer_name == cust.name)
        .order_by(Appointment.starts_at.desc())
    ).all()

    from aiuda_core.optout import opted_out

    return {
        "id": cust.id,
        "name": cust.name,
        "phone": cust.phone,
        "email": cust.email,
        "kind": cust.kind or "cliente",
        "presence": cust.presence or {},
        "tags": cust.tags or [],
        "meta": cust.meta or {},
        # El cliente pidió no recibir mensajes (BAJA/STOP): {"at", "via"} o None.
        # Bloquea los envíos automatizados; el dueño puede reactivarlo desde aquí.
        "opt_out": opted_out(db, tenant, cust.phone),
        "open_total": open_total,
        "open_count": sum(1 for i in invoices if i.status == "open"),
        "reminders": [
            {
                "id": r.id,
                "folio": folio_by_id.get(r.invoice_id),
                "status": r.status,
                "channel": r.channel or "whatsapp",
                "bucket": r.bucket,
                "created_at": r.created_at.isoformat(),
            }
            for r in reminders
        ],
        "promises": [
            {
                "id": p.id,
                "folio": folio_by_id.get(p.invoice_id),
                "promised_date": p.promised_date.isoformat(),
                "fulfilled": p.fulfilled,
            }
            for p in promises
        ],
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "paid_at": p.paid_at.isoformat(),
                "source": p.source,
                "folio": folio_by_id.get(p.invoice_id),
                "status": p.status,
            }
            for p in payments
        ],
        "citas": [
            {
                "id": a.id,
                "title": a.title,
                "starts_at": a.starts_at.isoformat() if a.starts_at else None,
            }
            for a in citas
        ],
        "conversation_id": conv.id if conv else None,
        "human_takeover": conv.human_takeover if conv else False,
        "messages": _conversation_messages(db, tenant, conv),
        "invoices": [
            {
                "id": i.id,
                "folio": i.folio,
                "amount": float(i.amount),
                "status": i.status,
                "bucket": str(classify(i.due_date, today)),
                "days_overdue": (today - i.due_date).days,
            }
            for i in invoices
        ],
    }


class CustomerEditBody(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    meta: dict[str, str] | None = None  # datos extra editables (RFC, zona, etc.)


@app.put("/v1/customers/{customer_id}")
def edit_customer(
    customer_id: str,
    body: CustomerEditBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Edita un cliente en aiuda y encola la actualización hacia sus sistemas de
    origen (Odoo / tienda). aiuda no es la fuente de verdad del maestro: el cambio
    se inyecta de vuelta, con trazabilidad (outbox)."""
    from aiuda_core.engine.writeback import queue_customer_writeback

    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    changes: dict = {}
    if body.name is not None and body.name.strip() and body.name.strip() != cust.name:
        changes["name"] = body.name.strip()
    if body.email is not None and (body.email.strip() or None) != cust.email:
        changes["email"] = body.email.strip() or None
    # phone None = no se tocó; "" = el dueño lo borró (queda sin teléfono); valor = set.
    if body.phone is not None:
        new_phone = body.phone.strip() or None
        if new_phone != cust.phone:
            if new_phone is not None:
                clash = db.scalar(
                    select(Customer).where(
                        Customer.tenant_id == tenant.id,
                        Customer.phone == new_phone,
                        Customer.id != cust.id,
                    )
                )
                if clash is not None:
                    raise HTTPException(status_code=409, detail="Otro cliente ya usa ese WhatsApp.")
            changes["phone"] = new_phone

    # Datos extra (meta): se guardan en aiuda pero NO van al write-back — son
    # atributos propios, no del maestro de Odoo/tienda. Reemplazo total (lo que
    # el form manda es la verdad); valores vacíos se descartan.
    meta_changed = False
    if body.meta is not None:
        clean_meta = {k: v.strip() for k, v in body.meta.items() if v and v.strip()}
        if clean_meta != (cust.meta or {}):
            cust.meta = clean_meta
            meta_changed = True

    if not changes and not meta_changed:
        return {"id": cust.id, "name": cust.name, "phone": cust.phone, "email": cust.email, "writeback": []}

    # Si cambia el teléfono, re-vincula su conversación (el hilo se identifica por número).
    # Solo si había teléfono antes y hay uno nuevo: el hilo no puede quedar sin número.
    if "phone" in changes and changes["phone"] and cust.phone:
        convo = find_conversation_by_phone(db, tenant.id, cust.phone)
        if convo is not None:
            convo.remote_phone = normalize_mx(changes["phone"])
            db.add(convo)

    for field, value in changes.items():
        setattr(cust, field, value)
    db.add(cust)

    # Solo los campos del maestro (nombre/correo/teléfono) se inyectan de vuelta.
    entries = queue_customer_writeback(db, tenant, cust, changes) if changes else []
    db.flush()
    return {
        "id": cust.id,
        "name": cust.name,
        "phone": cust.phone,
        "email": cust.email,
        "meta": cust.meta or {},
        "writeback": [e.target for e in entries],
    }


class OptOutBody(BaseModel):
    activo: bool


@app.post("/v1/customers/{customer_id}/optout")
def set_customer_optout(
    customer_id: str,
    body: OptOutBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(solo_el_dueno),
):
    """Marca o quita la baja de mensajes del cliente desde su ficha. Quitarla es
    decisión del dueño (p.ej. el cliente se lo pidió de palabra); mientras esté
    activa, ningún envío automatizado le llega. Por eso mismo, un aparato
    invitado no toca este registro: quitar una baja reabre la cobranza."""
    from aiuda_core.optout import clear_opt_out, mark_opt_out, opted_out

    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    if not cust.phone:
        raise HTTPException(status_code=400, detail="El cliente no tiene teléfono.")
    antes = opted_out(db, tenant, cust.phone) is not None
    if body.activo:
        mark_opt_out(db, tenant, cust.phone, via="consola")
    else:
        clear_opt_out(db, tenant, cust.phone)
    db.flush()
    # Bitácora: la baja protege al cliente; quién la puso o la quitó debe poder
    # demostrarse igual que una aprobación.
    audit.record(
        db,
        tenant_id=tenant.id,
        action="customer.optout" if body.activo else "customer.optout_clear",
        entity_type="customer",
        entity_id=cust.id,
        principal=principal,
        before={"opt_out": antes},
        after={"opt_out": body.activo},
    )
    return {"opt_out": opted_out(db, tenant, cust.phone)}


class CustomerMessageBody(BaseModel):
    body: str


@app.post("/v1/customers/{customer_id}/messages")
def message_customer(
    customer_id: str,
    payload: CustomerMessageBody,
    background: BackgroundTasks,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(solo_el_dueno),
):
    """Escribe al cliente desde su ficha. Crea la conversación si no existe.

    El mensaje se guarda y se responde de INMEDIATO; el envío por WhatsApp (lento,
    porque `wacli send` levanta conexión) se hace en segundo plano para que la consola
    no se quede esperando ~10s. El mensaje queda en el hilo pase lo que pase con el envío.
    """
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")
    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    conv = find_conversation_by_phone(db, tenant.id, cust.phone)
    if conv is None:
        # Normalizado al crear: el hilo saliente y el entrante (webhook) son la MISMA
        # conversación, no dos filas que nunca se cruzan.
        conv = Conversation(
            tenant_id=tenant.id, remote_phone=normalize_mx(cust.phone), channel="whatsapp"
        )
        db.add(conv)
        db.flush()

    message = Message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        direction="out",
        author="human",
        body=payload.body.strip(),
        delivery="pending",  # el background lo marca sent/failed; el barrido rescata pendientes
    )
    db.add(message)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="message.send",
        entity_type="customer",
        entity_id=cust.id,
        principal=principal,
        after={"message_id": message.id, "conversation_id": conv.id},
    )
    from aiuda_server.worker.main import send_human_message_blocking

    background.add_task(
        send_human_message_blocking, tenant.id, cust.phone, message.body, message.id
    )
    return {
        "id": message.id,
        "direction": "out",
        "author": "human",
        "body": message.body,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "conversation_id": conv.id,
        "queued": True,
    }


# Tamaño máximo de adjunto (WhatsApp tope ~16 MB para documentos/imágenes comunes).
_MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024


@app.post("/v1/customers/{customer_id}/attachments")
def attach_to_customer(
    customer_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    caption: str = Form(""),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(solo_el_dueno),
):
    """Adjunta un archivo (PDF, imagen) y lo manda al cliente por WhatsApp. Guarda el
    archivo en un temporal y registra el mensaje al INSTANTE; el envío (lento) corre en
    segundo plano, que también borra el temporal. Queda en el hilo aunque el envío falle."""
    import os
    import tempfile

    cust = db.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.id == customer_id)
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    if not cust.phone:
        raise HTTPException(status_code=400, detail="El cliente no tiene teléfono para enviarle.")

    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Archivo vacío.")
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera 16 MB.")
    safe_name = os.path.basename(file.filename or "archivo")

    conv = find_conversation_by_phone(db, tenant.id, cust.phone)
    if conv is None:
        conv = Conversation(
            tenant_id=tenant.id, remote_phone=normalize_mx(cust.phone), channel="whatsapp"
        )
        db.add(conv)
        db.flush()

    body = caption.strip() or f"[archivo] {safe_name}"
    message = Message(
        tenant_id=tenant.id, conversation_id=conv.id, direction="out", author="human", body=body
    )
    db.add(message)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="message.send",
        entity_type="customer",
        entity_id=cust.id,
        principal=principal,
        after={"message_id": message.id, "archivo": safe_name},
    )

    # El temporal se escribe ahora (necesitamos los bytes del request) y lo borra la
    # tarea en segundo plano tras enviar.
    tmp_dir = tempfile.mkdtemp(prefix="aiuda-att-")
    tmp_path = os.path.join(tmp_dir, safe_name)
    with open(tmp_path, "wb") as fh:
        fh.write(raw)
    from aiuda_server.worker.main import send_human_file_blocking

    background.add_task(
        send_human_file_blocking, tenant.id, cust.phone, tmp_path, caption.strip(), safe_name
    )
    return {
        "id": message.id,
        "direction": "out",
        "author": "human",
        "body": message.body,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "conversation_id": conv.id,
        "queued": True,
    }


# Llave en tenant.config con los ids de conversación que el dueño descartó de la bandeja
# (ruido, spam, número equivocado). Sin tabla nueva ni migración: es una decisión del dueño.
CONV_DESCARTADAS_KEY = "conversaciones_descartadas"


def _conversaciones_descartadas(tenant: Tenant) -> set[str]:
    return set((tenant.config or {}).get(CONV_DESCARTADAS_KEY) or [])


@app.get("/v1/conversations")
def list_conversations(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """La bandeja unificada: lista sobre Conversation (lo que llena el webhook, la única
    verdad de entrantes) y clasifica cada hilo cruzándolo con el directorio por match_key:
    identificado (cruza a un cliente), por_identificar (no cruza) o descartado (el dueño
    lo sacó). Antes esto vivía en dos mundos separados que nunca se cruzaban."""
    descartadas = _conversaciones_descartadas(tenant)
    conversations = db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == tenant.id)
        .order_by(Conversation.created_at.desc())
    ).all()
    out = []
    for conv in conversations:
        last = db.scalar(
            select(Message)
            .where(Message.tenant_id == tenant.id, Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
        )
        count = db.scalar(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id, Message.conversation_id == conv.id
            )
        )
        customer = _customer_de_conversacion(db, tenant, conv)
        if conv.id in descartadas:
            status = "descartado"
        elif customer is not None:
            status = "identificado"
        else:
            status = "por_identificar"
        out.append(
            {
                "id": conv.id,
                "remote_phone": conv.remote_phone,
                "channel": conv.channel or "whatsapp",
                # Hilos de correo: quién y de qué va (la UI muestra esto, no la clave).
                "correo": _correo_hilo_info(tenant, conv),
                "customer": customer.name if customer else None,
                "customer_id": customer.id if customer else None,
                "last_message": last.body if last else None,
                "last_direction": last.direction if last else None,
                "last_at": last.created_at.isoformat() if last else None,
                "messages": int(count or 0),
                "status": status,
                "human_takeover": conv.human_takeover,
            }
        )
    return out


def _get_conversation_or_404(conversation_id: str, tenant: Tenant, db) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return conv


@app.post("/v1/conversations/{conversation_id}/dismiss")
def dismiss_conversation(
    conversation_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Saca la conversación de la bandeja por identificar (ruido, número equivocado)."""
    _get_conversation_or_404(conversation_id, tenant, db)
    descartadas = _conversaciones_descartadas(tenant)
    descartadas.add(conversation_id)
    tenant.config = {**(tenant.config or {}), CONV_DESCARTADAS_KEY: sorted(descartadas)}
    db.commit()
    return {"status": "descartado"}


@app.post("/v1/conversations/{conversation_id}/undismiss")
def undismiss_conversation(
    conversation_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)
):
    """Deshace el descarte: vuelve a la bandeja (identificado o por identificar según cruce)."""
    conv = _get_conversation_or_404(conversation_id, tenant, db)
    descartadas = _conversaciones_descartadas(tenant)
    descartadas.discard(conversation_id)
    tenant.config = {**(tenant.config or {}), CONV_DESCARTADAS_KEY: sorted(descartadas)}
    db.commit()
    customer = resolve_customer_by_phone(db, tenant.id, conv.remote_phone)
    return {"status": "identificado" if customer else "por_identificar"}


class RegistrarClienteBody(BaseModel):
    name: str | None = None
    link_customer_id: str | None = None  # ligar a un cliente que ya existe, en vez de crear


@app.post("/v1/conversations/{conversation_id}/registrar-cliente")
def register_customer_from_conversation(
    conversation_id: str,
    body: RegistrarClienteBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Sacar una conversación de "por identificar": ligarla a un cliente que ya tienes, o
    darlo de alta CON NOMBRE. De ahí en adelante cruza sola (identity por match_key en
    WhatsApp; por el email del remitente en hilos de correo).

    Nunca se crea un "cliente" que sea solo un número: antes, sin nombre, se volcaba el
    teléfono como nombre y ensuciaba la lista de Clientes con hilos sin identificar. Ahora
    exige nombre o un cliente al cual ligar."""
    conv = _get_conversation_or_404(conversation_id, tenant, db)
    existing = _customer_de_conversacion(db, tenant, conv)
    if existing is not None:
        return {"id": existing.id, "name": existing.name, "created": False}
    es_correo = (conv.channel or "whatsapp") == "correo"
    remitente = (_correo_hilo_info(tenant, conv) or {}).get("de", "") if es_correo else ""
    if es_correo and not remitente:
        raise HTTPException(status_code=422, detail="Este hilo de correo no tiene remitente.")
    phone = normalize_mx(conv.remote_phone) or conv.remote_phone
    # Ligar a un cliente existente: el contacto de ESTE canal pasa a ser el suyo
    # (WhatsApp = su número; correo = el remitente). De ahí cruza solo.
    if body.link_customer_id:
        cust = db.get(Customer, body.link_customer_id)
        if cust is None or cust.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Cliente no encontrado.")
        if es_correo:
            cust.email = remitente
        else:
            cust.phone = phone
        db.commit()
        return {"id": cust.id, "name": cust.name, "created": False, "linked": True}
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(
            status_code=422,
            detail="Dale un nombre al cliente o lígalo a uno que ya tengas.",
        )
    cust = Customer(
        tenant_id=tenant.id, name=name,
        phone=None if es_correo else phone,
        email=remitente or None,
        kind="cliente",
    )
    db.add(cust)
    db.commit()
    return {"id": cust.id, "name": cust.name, "created": True}


@app.get("/v1/usage")
def usage_summary(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """No es un recibo de tokens: es la historia de lo que el agente hizo por ti,
    y abajo lo (poco) que costó. Todo DEL MES en curso (antes decía 'mes' pero
    sumaba el histórico completo: mentía)."""
    from aiuda_server.costs import cost_usd, month_start

    now = datetime.now(MX_TZ)
    inicio = month_start()
    rows = db.execute(
        select(
            UsageEvent.model,
            func.sum(UsageEvent.input_tokens),
            func.sum(UsageEvent.output_tokens),
        )
        .where(UsageEvent.tenant_id == tenant.id, UsageEvent.created_at >= inicio)
        .group_by(UsageEvent.model)
    ).all()
    by_model = []
    total = 0.0
    for model, input_tokens, output_tokens in rows:
        cost = cost_usd(model, int(input_tokens or 0), int(output_tokens or 0))
        total += cost
        by_model.append(
            {
                "model": model,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cost_usd": round(cost, 4),
            }
        )

    def count(model, *where) -> int:
        return int(
            db.scalar(
                select(func.count(model.id)).where(model.created_at >= inicio, *where)
            )
            or 0
        )

    activity = {
        "recordatorios_redactados": count(Reminder, Reminder.tenant_id == tenant.id),
        "recordatorios_enviados": count(
            Reminder, Reminder.tenant_id == tenant.id, Reminder.status == "sent"
        ),
        "conversaciones_atendidas": count(Conversation, Conversation.tenant_id == tenant.id),
        "mensajes_respondidos": count(
            Message,
            Message.tenant_id == tenant.id,
            Message.direction == "out",
            Message.author == "agent",
        ),
        "promesas_registradas": count(PaymentPromise, PaymentPromise.tenant_id == tenant.id),
    }
    return {
        "month": now.strftime("%Y-%m"),
        "total_cost_usd": round(total, 4),
        "by_model": by_model,
        "activity": activity,
    }


@app.get("/v1/invoices")
def list_invoices(
    status: str = Query(default="open"),
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    today = datetime.now(MX_TZ).date()
    rows = db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.tenant_id == tenant.id, Invoice.status == status)
        .order_by(Invoice.due_date)
    ).all()
    return [
        {
            "id": inv.id,
            "folio": inv.folio,
            "customer": cust.name,
            "customer_phone": cust.phone,
            "amount": float(inv.amount),
            "currency": inv.currency,
            "issued_date": inv.issued_date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "days_overdue": (today - inv.due_date).days,
            "bucket": str(classify(inv.due_date, today)),
            "status": inv.status,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "source": inv.source,
            "presence": inv.presence or {},
            "verified": inv.verified,
            "payment_reported": inv.payment_reported,
            "paid_source": inv.paid_source,
        }
        for inv, cust in rows
    ]


@app.get("/v1/invoices/{invoice_id}")
def invoice_detail(
    invoice_id: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Detalle de una factura: sus datos, presencia multi-sistema y la
    actividad del equipo (recordatorios redactados, promesas registradas)."""
    today = datetime.now(MX_TZ).date()
    row = db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.tenant_id == tenant.id, Invoice.id == invoice_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    inv, cust = row

    reminders = db.scalars(
        select(Reminder)
        .where(Reminder.tenant_id == tenant.id, Reminder.invoice_id == inv.id)
        .order_by(Reminder.created_at.desc())
    ).all()
    promises = db.scalars(
        select(PaymentPromise)
        .where(PaymentPromise.tenant_id == tenant.id, PaymentPromise.invoice_id == inv.id)
        .order_by(PaymentPromise.promised_date.desc())
    ).all()
    convo = find_conversation_by_phone(db, tenant.id, cust.phone)

    return {
        "id": inv.id,
        "folio": inv.folio,
        "customer": cust.name,
        "customer_id": cust.id,
        "customer_phone": cust.phone,
        "amount": float(inv.amount),
        "currency": inv.currency,
        "issued_date": inv.issued_date.isoformat(),
        "due_date": inv.due_date.isoformat(),
        "days_overdue": (today - inv.due_date).days,
        "bucket": str(classify(inv.due_date, today)),
        "status": inv.status,
        "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        "source": inv.source,
        "presence": inv.presence or {},
        "verified": inv.verified,
        "payment_reported": inv.payment_reported,
        "paid_source": inv.paid_source,
        # Comprobante fiscal: datos parseados + si hay archivos para ver/descargar.
        "cfdi": inv.cfdi or {},
        "has_xml": inv.cfdi_xml is not None,
        "has_pdf": inv.cfdi_pdf is not None,
        "conversation_id": convo.id if convo else None,
        "reminders": [
            {
                "id": r.id,
                "agent": r.agent,
                # El ayudante que el DUEÑO creó. `agent` es el slug del runtime, y
                # enseñárselo es enseñarle un trabajador que él nunca contrató.
                "propuesto_por": (r.meta or {}).get("ayudante_name"),
                "tone": r.tone,
                "bucket": r.bucket,
                "status": r.status,
                "message": r.message,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reminders
        ],
        "promises": [
            {
                "id": p.id,
                "promised_date": p.promised_date.isoformat(),
                "note": p.note,
                "fulfilled": p.fulfilled,
                "fulfilled_at": p.fulfilled_at.isoformat() if p.fulfilled_at else None,
            }
            for p in promises
        ],
    }


def _invoice_or_404(invoice_id: str, tenant: Tenant, db) -> Invoice:
    inv = db.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.id == invoice_id)
    )
    if inv is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    return inv


@app.get("/v1/invoices/{invoice_id}/cfdi.xml")
def invoice_cfdi_xml(invoice_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Sirve el XML del CFDI para ver/descargar."""
    inv = _invoice_or_404(invoice_id, tenant, db)
    if not inv.cfdi_xml:
        raise HTTPException(status_code=404, detail="Esta factura no tiene XML del CFDI.")
    return Response(
        content=inv.cfdi_xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'inline; filename="{inv.folio}.xml"'},
    )


@app.get("/v1/invoices/{invoice_id}/cfdi.pdf")
def invoice_cfdi_pdf(invoice_id: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Sirve el PDF del CFDI para ver/descargar."""
    inv = _invoice_or_404(invoice_id, tenant, db)
    if not inv.cfdi_pdf:
        raise HTTPException(status_code=404, detail="Esta factura no tiene PDF del CFDI.")
    return Response(
        content=inv.cfdi_pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{inv.folio}.pdf"'},
    )


# La conciliación (Diego) vive en su propio router: aiuda_server/api/reconciliation.py


# --------------------------------------------------------------------------- #
# Altas directas + inyección a sistemas maestros                               #
# --------------------------------------------------------------------------- #
# aiuda NO es el sistema maestro: es capaz de INYECTAR a los maestros. Aquí se
# captura rápido (source="aiuda", procedencia honesta) y, si el dueño lo pide
# (check al crear o botón en la ficha), el registro viaja al destino elegido
# vía el outbox (engine/writeback.queue_creation_writeback). Nada se empuja solo.

_CAP_DE_ENTIDAD = {  # qué capacidad debe leer una conexión a la medida para RECIBIR el alta
    "cliente": "directorio_clientes",
    "producto": "catalogo_productos",
    "factura": "cuentas_por_cobrar",
    "cita": "agenda",
}


def _destinos_de_alta(db, tenant: Tenant) -> dict[str, list[dict]]:
    """Destinos que hoy pueden RECIBIR altas, por entidad: los conectores con
    credencial capturada y las conexiones a la medida con endpoint de escritura."""
    from aiuda_core.connectors.credentials import get_credential
    from aiuda_core.engine.writeback import CREATION_TARGETS

    odoo_ok = bool((get_credential(db, tenant.id, "odoo") or {}).get("url"))
    gcal_ok = bool((get_credential(db, tenant.id, "googlecalendar") or {}).get("token"))
    customs = [
        s
        for s in (tenant.config or {}).get("custom_sources") or []
        if (s.get("write_path") or "").strip()
    ]
    out: dict[str, list[dict]] = {}
    for entidad, targets in CREATION_TARGETS.items():
        destinos = []
        if "odoo" in targets and odoo_ok:
            destinos.append({"target": "odoo", "label": "Odoo"})
        if "googlecalendar" in targets and gcal_ok:
            destinos.append({"target": "googlecalendar", "label": "Google Calendar"})
        for s in customs:
            if s.get("cap") == _CAP_DE_ENTIDAD[entidad]:
                destinos.append(
                    {"target": "custom", "conexion_id": s.get("id"), "label": s.get("name") or "a la medida"}
                )
        out[entidad] = destinos
    return out


@app.get("/v1/inyectar/destinos")
def inyectar_destinos(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    return _destinos_de_alta(db, tenant)


def _encolar_inyeccion(
    db,
    tenant: Tenant,
    registro,
    target: str | None,
    conexion_id: str | None,
    background: BackgroundTasks,
) -> dict | None:
    """Encola el alta hacia el destino elegido y agenda el drenado. Errores de
    dominio (destino inválido, ya vive allá, cita sin hora) salen como 409/422
    legibles. Commit ANTES de agendar: el background corre en su propia sesión."""
    if not target:
        return None
    from aiuda_core.engine.writeback import queue_creation_writeback

    conexion = None
    if target == "custom":
        src = next(
            (
                s
                for s in (tenant.config or {}).get("custom_sources") or []
                if s.get("id") == conexion_id
            ),
            None,
        )
        if src is None:
            raise HTTPException(status_code=404, detail="Esa conexión a la medida no existe.")
        if not (src.get("write_path") or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Esa conexión no declara endpoint de escritura; agrégalo en la receta.",
            )
        from aiuda_core.engine.sync import _custom_presence_key

        conexion = {"id": src.get("id"), "pkey": _custom_presence_key(src)}
    try:
        entry = queue_creation_writeback(
            db, tenant, registro=registro, target=target, conexion=conexion
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()  # durable antes del background (las BackgroundTasks corren pre-teardown)
    from aiuda_server.worker.main import process_writebacks_blocking

    background.add_task(process_writebacks_blocking, tenant.id)
    return {"outbox_id": entry.id, "target": target, "status": "encolada"}


class CustomerCreateBody(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    kind: str = "cliente"  # cliente | prospecto
    inyectar_a: str | None = None
    conexion_id: str | None = None


@app.post("/v1/customers", status_code=201)
def create_customer(
    body: CustomerCreateBody,
    background: BackgroundTasks,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Alta directa de cliente/prospecto en aiuda (registro nativo: presence vacío).
    Con `inyectar_a`, el alta viaja también al maestro elegido."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El cliente necesita nombre.")
    if body.kind not in ("cliente", "prospecto"):
        raise HTTPException(status_code=422, detail="kind debe ser cliente o prospecto.")
    phone = normalize_mx(body.phone) or (body.phone or "").strip() or None
    if phone is not None:
        choque = db.scalar(
            select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == phone)
        )
        if choque is not None:
            raise HTTPException(
                status_code=409, detail=f"Ese teléfono ya es de {choque.name}."
            )
    customer = Customer(
        tenant_id=tenant.id,
        name=name,
        phone=phone,
        email=(body.email or "").strip() or None,
        kind=body.kind,
    )
    db.add(customer)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, action="customer.create", entity_type="customer",
        entity_id=customer.id, principal=principal,
        after={"name": name, "kind": body.kind, "inyectar_a": body.inyectar_a},
        ip=request.client.host if request.client else None,
    )
    inyeccion = _encolar_inyeccion(
        db, tenant, customer, body.inyectar_a, body.conexion_id, background
    )
    return {
        "id": customer.id, "name": customer.name, "phone": customer.phone,
        "email": customer.email, "kind": customer.kind, "inyeccion": inyeccion,
    }


class ProductCreateBody(BaseModel):
    name: str
    sku: str | None = None
    price: float | None = None
    stock: float | None = None
    unit: str | None = None
    inyectar_a: str | None = None
    conexion_id: str | None = None


@app.post("/v1/products", status_code=201)
def create_product(
    body: ProductCreateBody,
    background: BackgroundTasks,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Alta directa de producto (source="aiuda"). Dedupe honesto por SKU."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El producto necesita nombre.")
    if body.price is not None and body.price < 0:
        raise HTTPException(status_code=422, detail="El precio no puede ser negativo.")
    sku = (body.sku or "").strip() or None
    if sku is not None:
        choque = db.scalar(
            select(Product).where(Product.tenant_id == tenant.id, Product.sku == sku)
        )
        if choque is not None:
            raise HTTPException(status_code=409, detail=f"Ese SKU ya es de {choque.name}.")
    product = Product(
        tenant_id=tenant.id, name=name, sku=sku, price=body.price, stock=body.stock,
        unit=(body.unit or "").strip() or None, source="aiuda",
    )
    db.add(product)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, action="product.create", entity_type="product",
        entity_id=product.id, principal=principal,
        after={"name": name, "sku": sku, "inyectar_a": body.inyectar_a},
        ip=request.client.host if request.client else None,
    )
    inyeccion = _encolar_inyeccion(
        db, tenant, product, body.inyectar_a, body.conexion_id, background
    )
    return {
        "id": product.id, "name": product.name, "sku": product.sku,
        "price": float(product.price) if product.price is not None else None,
        "inyeccion": inyeccion,
    }


class AppointmentCreateBody(BaseModel):
    title: str
    starts_at: datetime | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    notes: str | None = None
    inyectar_a: str | None = None
    conexion_id: str | None = None


@app.post("/v1/appointments", status_code=201)
def create_appointment(
    body: AppointmentCreateBody,
    background: BackgroundTasks,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Alta directa de cita (source="aiuda"; hora de pared, sin zona)."""
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="La cita necesita título.")
    starts = body.starts_at.replace(tzinfo=None) if body.starts_at else None
    appt = Appointment(
        tenant_id=tenant.id, title=title, starts_at=starts,
        customer_name=(body.customer_name or "").strip() or None,
        customer_phone=normalize_mx(body.customer_phone)
        or (body.customer_phone or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        source="aiuda",
    )
    db.add(appt)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, action="appointment.create", entity_type="appointment",
        entity_id=appt.id, principal=principal,
        after={"title": title, "inyectar_a": body.inyectar_a},
        ip=request.client.host if request.client else None,
    )
    inyeccion = _encolar_inyeccion(
        db, tenant, appt, body.inyectar_a, body.conexion_id, background
    )
    return {
        "id": appt.id, "title": appt.title,
        "starts_at": appt.starts_at.isoformat() if appt.starts_at else None,
        "inyeccion": inyeccion,
    }


class InvoiceCreateBody(BaseModel):
    customer_id: str
    folio: str
    amount: float
    issued_date: date | None = None
    due_date: date
    currency: str = "MXN"
    concepto: str | None = None
    inyectar_a: str | None = None
    conexion_id: str | None = None


@app.post("/v1/invoices", status_code=201)
def create_invoice(
    body: InvoiceCreateBody,
    background: BackgroundTasks,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Alta directa de factura en aiuda (source="aiuda"). Inyectada a Odoo llega
    como BORRADOR: el dueño revisa impuestos y publica/timbra allá."""
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    folio = (body.folio or "").strip()
    if not folio:
        raise HTTPException(status_code=422, detail="La factura necesita folio.")
    if body.amount is None or body.amount <= 0:
        raise HTTPException(status_code=422, detail="El monto debe ser mayor a cero.")
    choque = db.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == folio)
    )
    if choque is not None:
        raise HTTPException(status_code=409, detail=f"El folio {folio} ya existe.")
    issued = body.issued_date or datetime.now(MX_TZ).date()
    if body.due_date < issued:
        raise HTTPException(
            status_code=422, detail="El vencimiento no puede ser antes de la emisión."
        )
    meta = {"concepto": body.concepto.strip()} if (body.concepto or "").strip() else {}
    invoice = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio=folio, amount=body.amount,
        currency=(body.currency or "MXN").upper(), issued_date=issued,
        due_date=body.due_date, source="aiuda", meta=meta,
    )
    db.add(invoice)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, action="invoice.create", entity_type="invoice",
        entity_id=invoice.id, principal=principal,
        after={"folio": folio, "amount": body.amount, "inyectar_a": body.inyectar_a},
        ip=request.client.host if request.client else None,
    )
    inyeccion = _encolar_inyeccion(
        db, tenant, invoice, body.inyectar_a, body.conexion_id, background
    )
    return {
        "id": invoice.id, "folio": invoice.folio, "amount": float(invoice.amount),
        "customer": customer.name, "status": invoice.status, "inyeccion": inyeccion,
    }


class PaymentCreateBody(BaseModel):
    amount: float
    paid_at: date | None = None
    reference: str | None = None
    counterparty: str | None = None
    invoice_id: str | None = None  # pista para Diego; conciliar sigue siendo HITL


@app.post("/v1/payments", status_code=201)
def create_payment(
    body: PaymentCreateBody,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Pago registrado A MANO (source="manual"): entra a la bandeja de conciliación
    como cualquier depósito detectado — Diego propone, tú confirmas y la factura se
    cierra por el flujo normal (con write-back). Distinto de POST /v1/invoices/{id}/pay,
    que cierra directo sin rastro de pago."""
    if body.amount is None or body.amount <= 0:
        raise HTTPException(status_code=422, detail="El monto debe ser mayor a cero.")
    hint = None
    if body.invoice_id:
        hint = db.get(Invoice, body.invoice_id)
        if hint is None or hint.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")
    payment = Payment(
        tenant_id=tenant.id,
        amount=body.amount,
        paid_at=body.paid_at or datetime.now(MX_TZ).date(),
        source="manual",
        reference=(body.reference or "").strip() or None,
        counterparty=(body.counterparty or "").strip() or None,
        meta={"invoice_hint": body.invoice_id} if body.invoice_id else {},
    )
    db.add(payment)
    db.flush()
    audit.record(
        db, tenant_id=tenant.id, action="payment.manual", entity_type="payment",
        entity_id=payment.id, principal=principal,
        after={"amount": body.amount, "paid_at": payment.paid_at.isoformat()},
        ip=request.client.host if request.client else None,
    )
    return {
        "id": payment.id, "amount": float(payment.amount),
        "paid_at": payment.paid_at.isoformat(), "status": payment.status,
    }


class InyectarBody(BaseModel):
    entidad: str  # cliente | producto | factura | cita
    id: str
    target: str
    conexion_id: str | None = None


@app.post("/v1/inyectar")
def inyectar_registro(
    body: InyectarBody,
    background: BackgroundTasks,
    request: Request,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Empuja un registro que vive en aiuda hacia el maestro elegido (botón
    "Inyectar a..." de la ficha). El estado queda visible en el write-back."""
    modelos = {
        "cliente": Customer, "producto": Product, "factura": Invoice, "cita": Appointment,
    }
    modelo = modelos.get(body.entidad)
    if modelo is None:
        raise HTTPException(status_code=404, detail="Entidad desconocida.")
    registro = db.get(modelo, body.id)
    if registro is None or registro.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    audit.record(
        db, tenant_id=tenant.id, action="inyeccion.solicitada", entity_type=body.entidad,
        entity_id=body.id, principal=principal,
        after={"target": body.target, "conexion_id": body.conexion_id},
        ip=request.client.host if request.client else None,
    )
    inyeccion = _encolar_inyeccion(
        db, tenant, registro, body.target, body.conexion_id, background
    )
    return inyeccion


# La consola exportada se sirve desde este mismo proceso (catch-all al final:
# toda ruta /v1 registrada arriba gana). Ver aiuda_server/console.py.
from aiuda_server.console import mount_console  # noqa: E402

mount_console(app)
