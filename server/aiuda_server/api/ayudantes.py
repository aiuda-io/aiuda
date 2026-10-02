"""Ayudantes del dueño (capability-first) + catálogo de aiuditas.

El dueño crea su propio ayudante, lo nombra, le da apariencia y le agrega aiuditas
del catálogo, cada una con su config. La fuente de verdad de la config vive aquí
(por-tenant), no en localStorage: el motor la lee en runtime.

La config que llega del cliente NUNCA se confía: pasa por `validar_config` (solo
perillas conocidas, tipadas y acotadas; lo desconocido se descarta).

Correr y carrera: `POST /{id}/correr` ejecuta el ayudante sobre el motor genérico
(hoy: cobranza) y deja PROPUESTAS en la bandeja, atribuidas a él (meta.ayudante_id).
Sus `acciones` y su `nivel` se derivan de esas filas reales en cada lectura — el
plan de carrera nunca es un contador cosmético.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_server.api.integrations import fuente_default, fuente_valida, fuentes_de_capacidad
from aiuda_server.api.text import plain_text
from aiuda_core.aiuditas import (
    aiudita_por_id,
    catalog_payload,
    config_default,
    validar_config,
)
from aiuda_core.carrera import nivel_por_acciones
from aiuda_core.models import Ayudante, Reminder, Tenant

router = APIRouter()


# --- Catálogo ---------------------------------------------------------------

@router.get("/v1/aiuditas/catalog")
def get_catalog() -> dict:
    """El catálogo de aiuditas con sus perillas. Una sola fuente para el frontend.

    Cada aiudita que lee datos trae sus `fuentes` posibles (de dónde puede jalar),
    derivadas de su capacidad: ahí es donde el dueño define la fuente, lo que
    diferencia a aiuda de un ERP (en un ERP la fuente es fija)."""
    payload = catalog_payload()
    for a in payload["aiuditas"]:
        cap = a.get("capacidad")
        if cap:
            a["fuentes"] = fuentes_de_capacidad(cap)
    return payload


def _con_fuente_default(aiudita_id: str, cfg: dict) -> dict:
    """Si la aiudita lee de una capacidad, garantiza una `_fuente` válida: respeta
    la que eligió el dueño y, si falta o no es válida, cae a la fuente viva por
    defecto. Así la config siempre dice de dónde lee, sin fingir."""
    spec = aiudita_por_id(aiudita_id)
    if spec is None or not spec.capacidad:
        return cfg
    actual = cfg.get("_fuente")
    if not (isinstance(actual, str) and fuente_valida(spec.capacidad, actual)):
        defecto = fuente_default(spec.capacidad)
        if defecto:
            cfg["_fuente"] = defecto
    return cfg


# --- Serialización ----------------------------------------------------------

def _acciones(db, tenant: Tenant, ayudante_id: str) -> dict:
    """Trabajo REAL atribuido al ayudante, derivado de las filas en cada lectura
    (no un contador guardado): propuestas suyas en la bandeja por estado. Las
    rechazadas no dan carrera; borrar el trabajo baja el nivel."""
    rows = db.execute(
        select(Reminder.status, func.count(Reminder.id))
        .where(
            Reminder.tenant_id == tenant.id,
            Reminder.meta["ayudante_id"].as_string() == ayudante_id,
        )
        .group_by(Reminder.status)
    ).all()
    por_estado = dict(rows)
    pendientes = int(por_estado.get("pending_approval", 0))
    enviadas = int(por_estado.get("sent", 0))
    total = pendientes + int(por_estado.get("approved", 0)) + enviadas
    return {"pendientes": pendientes, "enviadas": enviadas, "total": total}


def _serialize(db, tenant: Tenant, a: Ayudante) -> dict:
    acciones = _acciones(db, tenant, a.id)
    return {
        "id": a.id,
        "name": a.name,
        "appearance": a.appearance or {},
        # Instrucciones libres del dueño (persona/tono). Se inyectan bajo las reglas de fábrica.
        "instructions": a.instructions or "",
        # { aiudita_id: config }. La presencia de la llave = activa.
        "aiuditas": a.aiuditas or {},
        # Plan de carrera: acciones reales (derivadas) y el nivel que suman.
        "acciones": acciones,
        "nivel": nivel_por_acciones(acciones["total"]),
        "createdAt": a.created_at.isoformat() if a.created_at else None,
    }


def _get_owned(db, tenant: Tenant, ayudante_id: str) -> Ayudante:
    a = db.get(Ayudante, ayudante_id)
    if a is None or a.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Ayudante no encontrado")
    return a


# --- CRUD de ayudantes ------------------------------------------------------

class CrearAyudante(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    appearance: dict = Field(default_factory=dict)
    # Ids de aiuditas a precargar (ej. al usar una plantilla). Cada una entra con
    # su config por defecto; las desconocidas se ignoran.
    aiuditas: list[str] = Field(default_factory=list)


class EditarAyudante(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    appearance: dict | None = None
    # Texto libre; None = no tocar, "" = limpiar. Tope generoso: es una persona, no un ensayo.
    instructions: str | None = Field(default=None, max_length=4000)


class ConfigAiudita(BaseModel):
    # Valores de las perillas (+ "reglas" si aplica). Se valida contra el esquema.
    config: dict = Field(default_factory=dict)


@router.get("/v1/ayudantes")
def listar(db=Depends(get_db), tenant: Tenant = Depends(get_tenant)) -> list[dict]:
    rows = db.scalars(
        select(Ayudante).where(Ayudante.tenant_id == tenant.id).order_by(Ayudante.created_at)
    ).all()
    return [_serialize(db, tenant, a) for a in rows]


@router.post("/v1/ayudantes", status_code=201)
def crear(
    body: CrearAyudante, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    aiuditas: dict = {}
    for aid in body.aiuditas:
        spec = aiudita_por_id(aid)
        if spec is not None:
            aiuditas[aid] = _con_fuente_default(aid, config_default(spec))
    a = Ayudante(
        tenant_id=tenant.id,
        name=body.name.strip(),
        appearance=body.appearance or {},
        aiuditas=aiuditas,
    )
    db.add(a)
    db.flush()
    return _serialize(db, tenant, a)


@router.get("/v1/ayudantes/{ayudante_id}")
def detalle(
    ayudante_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    return _serialize(db, tenant, _get_owned(db, tenant, ayudante_id))


@router.get("/v1/ayudantes/{ayudante_id}/prompt")
def prompt_preview(
    ayudante_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    """Los system prompts REALES de este ayudante, ensamblados en el backend (fuente
    única de verdad, no una copia en el front).

    Son DOS, porque el interlocutor cambia y con él lo que el ayudante puede decir:

    - ``chat``: cuando el DUEÑO le pregunta desde la consola. Acceso a lo suyo.
    - ``corrida``: cuando redacta para un CLIENTE en la corrida. Es el que gobierna
      lo que sale del negocio, y trae las correcciones del dueño reinyectadas.

    Este endpoint devolvía solo el de chat mientras su docstring decía "el prompt REAL
    con que corre". Enseñar el de chat como si fuera el de cobranza es justo el tipo de
    fachada que aquí no va: el dueño revisa el prompt para saber qué le dice a sus
    clientes."""
    from aiuda_core.agents.cleo.prompt import build_system_prompt
    from aiuda_core.aiuditas.chat import chat_system_prompt
    from aiuda_core.learning import recent_corrections

    a = _get_owned(db, tenant, ayudante_id)
    active = {aid: cfg for aid, cfg in (a.aiuditas or {}).items() if aiudita_por_id(aid)}
    chat = chat_system_prompt(a.name, tenant.name, active, instructions=a.instructions)

    config = tenant.config or {}
    corrida = build_system_prompt(
        business_name=tenant.name,
        business_context=config.get("business_context", ""),
        user_rules=list(((config.get("agent_config") or {}).get("mariana") or {}).get(
            "user_rules"
        ) or []) or None,
        correcciones=recent_corrections(db, tenant, agent="mariana") or None,
        ayudante_name=a.name,
        persona=(a.instructions or "").strip() or None,
    )
    # `system` se conserva por compatibilidad con quien ya consuma el endpoint.
    return {"system": chat, "chat": chat, "corrida": corrida}


@router.put("/v1/ayudantes/{ayudante_id}")
def editar(
    ayudante_id: str,
    body: EditarAyudante,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    a = _get_owned(db, tenant, ayudante_id)
    if body.name is not None:
        a.name = body.name.strip()
    if body.appearance is not None:
        a.appearance = body.appearance
    if body.instructions is not None:
        a.instructions = body.instructions.strip() or None
    db.flush()
    return _serialize(db, tenant, a)


@router.delete("/v1/ayudantes/{ayudante_id}", status_code=204)
def eliminar(
    ayudante_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> None:
    a = _get_owned(db, tenant, ayudante_id)
    db.delete(a)
    db.flush()


# --- Aiuditas de un ayudante (activar/configurar/quitar) --------------------

@router.put("/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}")
def set_aiudita(
    ayudante_id: str,
    aiudita_id: str,
    body: ConfigAiudita,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    """Activa la aiudita (si no estaba) y guarda su config validada. Idempotente."""
    a = _get_owned(db, tenant, ayudante_id)
    spec = aiudita_por_id(aiudita_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Aiudita desconocida")
    # SQLAlchemy no detecta mutaciones in-place de un JSON: reasignar el dict.
    current = dict(a.aiuditas or {})
    current[aiudita_id] = _con_fuente_default(aiudita_id, validar_config(spec, body.config))
    a.aiuditas = current
    db.flush()
    return _serialize(db, tenant, a)


@router.delete("/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}", status_code=200)
def quitar_aiudita(
    ayudante_id: str,
    aiudita_id: str,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    a = _get_owned(db, tenant, ayudante_id)
    current = dict(a.aiuditas or {})
    current.pop(aiudita_id, None)
    a.aiuditas = current
    db.flush()
    return _serialize(db, tenant, a)


# --- Correr al ayudante (motor genérico, HITL) ------------------------------

# Aiuditas que corren SOLAS en una corrida (batch) hoy — con ejecutor real detrás.
# Las demás activas trabajan bajo demanda (chat de consulta, cotizar desde Ventas,
# conciliación en su bandeja) y se reportan como `sin_corrida`, sin fingir.
AIUDITAS_DE_CORRIDA: tuple[str, ...] = ("cobranza.redactar_recordatorio",)


@router.post("/v1/ayudantes/{ayudante_id}/correr")
def correr(
    ayudante_id: str, db=Depends(get_db), tenant: Tenant = Depends(get_tenant)
) -> dict:
    """Corre el ayudante AHORA sobre el motor genérico, con SUS perillas, reglas e
    instrucciones. Produce PROPUESTAS (pending_approval) en la bandeja del Centro,
    atribuidas a él — nada sale a un cliente sin tu aprobación. Si su config de
    autonomía dejó algo auto-aprobado, lo envía la corrida diaria dentro de ventana.

    MVP: redacta síncrono en el request (igual que /invoices/{id}/remind); con
    volumen real se encola al worker sin cambiar el contrato."""
    a = _get_owned(db, tenant, ayudante_id)
    activos = set(a.aiuditas or {})
    corribles = [aid for aid in AIUDITAS_DE_CORRIDA if aid in activos]
    sin_corrida = sorted(activos - set(corribles))
    if not corribles:
        return {
            "corrio": [],
            "sin_corrida": sin_corrida,
            "propuestas": 0,
            "detalle": (
                f"{a.name} no tiene aiuditas que corran solas todavía. Las de consulta "
                "responden en su chat; cotizar vive en Ventas y conciliar en Conciliación."
            ),
        }

    from aiuda_core.engine.provider import resolve_credential

    if resolve_credential(session=db, tenant_id=tenant.id) is None:
        raise HTTPException(
            status_code=409,
            detail="Conecta tu proveedor de IA para correr a este ayudante.",
        )

    from datetime import datetime

    from aiuda_core.engine.engine import MX_TZ, CleoEngine
    from aiuda_core.observabilidad import abrir_run
    from aiuda_server.metering import tenant_runner

    # Todo lo que pase aquí queda grabado: qué leyó, qué propuso, cuánto costó y por qué
    # no hizo el resto. Sin esto el dueño solo ve un número y tiene que confiar.
    with abrir_run(db, tenant, ayudante=a, aiudita=corribles[0], disparo="manual") as run:
        engine = CleoEngine(db, tenant, ayudante_id=a.id, runner=tenant_runner(db, tenant, run=run))
        try:
            drafted = engine.run_reminders(datetime.now(MX_TZ).date())
        except Exception as exc:
            import logging
            logging.getLogger("aiuda.api").exception("correr falló")
            raise HTTPException(status_code=502, detail="No pude correr al ayudante ahora.") from exc
        run.contar(propuestos=len(drafted))
        for r in drafted:
            run.liga("reminder", r.id, rol="propuso")
            if r.invoice_id:
                run.liga("invoice", r.invoice_id, rol="leyo")
            # El run del que salió, para poder abrir "cómo lo hizo" desde la tarjeta.
            r.meta = {**(r.meta or {}), "run_id": run.id}
    db.flush()
    return {
        "corrio": corribles,
        "sin_corrida": sin_corrida,
        "propuestas": len(drafted),
        "pendientes": sum(1 for r in drafted if r.status == "pending_approval"),
        "detalle": (
            "Sin facturas accionables ahora: nada que proponer."
            if not drafted
            else f"{len(drafted)} propuesta{'s' if len(drafted) != 1 else ''} en el Centro, esperando tu aprobación."
        ),
    }


# --- Chatear con tu ayudante (capability-first) -----------------------------

class ChatTurn(BaseModel):
    role: str  # "user" | "agent"
    body: str


class ChatBody(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


@router.post("/v1/ayudantes/{ayudante_id}/chat")
def chat(
    ayudante_id: str,
    body: ChatBody,
    db=Depends(get_db),
    tenant: Tenant = Depends(get_tenant),
) -> dict:
    """Hablar con TU ayudante. Sus herramientas y su persona se arman desde las aiuditas
    que le activaste; en el chat solo consulta (las escrituras viven en los flujos con
    aprobación). Soberanía humana: no manda nada a clientes desde aquí."""
    a = _get_owned(db, tenant, ayudante_id)
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")

    # Imports tardíos: el chat trae los ejecutores/proveedor solo cuando se usa.
    from aiuda_server.metering import BudgetExceeded, tenant_runner
    from aiuda_core.aiuditas.chat import AyudanteChatExecutor, chat_system_prompt, chat_tools
    from aiuda_core.engine.provider import resolve_credential

    credential = resolve_credential(session=db, tenant_id=tenant.id)
    if credential is None:
        return {
            "reply": f"Soy {a.name}. Para que pueda responderte, conecta tu proveedor de IA "
            "en Proveedor de IA. Mientras, tu config queda guardada."
        }

    active = a.aiuditas or {}
    system = chat_system_prompt(a.name, tenant.name, active, instructions=a.instructions)
    turns = "\n".join(
        f"{'Dueño' if t.role == 'user' else a.name}: {t.body}" for t in body.history[-8:]
    )
    user = (f"{turns}\n" if turns else "") + f"Dueño: {body.message.strip()}\n{a.name}:"

    from aiuda_core.observabilidad import abrir_run

    tools = chat_tools(active.keys())
    # El chat también queda grabado: qué le preguntaste, qué consultó para contestar y
    # qué te dijo. Es donde el dueño más se pregunta "¿de dónde sacó eso?".
    with abrir_run(db, tenant, ayudante=a, disparo="chat") as run:
        # Runner con metering (UsageEvent por llamada) y tope de gasto enganchados.
        runner = tenant_runner(db, tenant, run=run)
        try:
            if tools:
                executor = AyudanteChatExecutor(db, tenant, active.keys())
                reply = runner.run_tool_loop(
                    system=system,
                    user_message=user,
                    tools=tools,
                    execute_tool=executor,
                    role="redaccion",
                    task="ayudante_chat",
                    max_iterations=6,
                )
            else:
                reply = runner.complete(
                    system=system, user=user, role="redaccion", task="ayudante_chat", max_tokens=400
                )
        except BudgetExceeded as exc:
            # Corte honesto: el tope del mes se alcanzó; no se llamó a la IA.
            run.cortar(str(exc))
            raise HTTPException(status_code=402, detail=str(exc))
        except Exception:
            raise HTTPException(status_code=502, detail="El ayudante no está disponible ahora.")
        run.contar(respuestas=1)
    db.flush()
    return {"reply": plain_text(reply) or "…"}
