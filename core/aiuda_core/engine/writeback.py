"""Write-back: lo que aiuda registra se inyecta de regreso al sistema fuente.

Principio (VISION.md): aiuda no acumula verdad propia. Si una factura
vino de Odoo y el dueño confirma el pago en aiuda, ese pago debe quedar
registrado en Odoo; si vino de Shopify, en el pedido de Shopify. La consola
muestra el estado de cada inyección (pendiente / inyectada / falló).

Patrón outbox: el evento se encola en la MISMA transacción que lo origina; un
job del worker lo procesa con reintentos (backoff creciente) y persiste la
EVIDENCIA de cada inyección — qué se escribió, qué respondió la fuente y
cuándo — en `payload["evidencia"]` (el JSON existente de la cola; sin
migración). `payload["reintento_en"]` guarda hasta cuándo espera el backoff.

Ejecutores por conector: cada target sabe escribir ciertas acciones con un
método HOMÓNIMO a la acción (`registrar_pago`, `actualizar_cliente`) que
devuelve la evidencia. Si el conector no está configurado, o aún no sabe esa
acción, la entrada ESPERA en `pending` (no falla): honestidad sobre lo que
todavía no se puede escribir. Enchufar Woo/otro = un ejecutor nuevo aquí.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from aiuda_core.engine.presence import add_presence, odoo_record_url
from aiuda_core.models import (
    Appointment,
    Customer,
    Invoice,
    OutboxEntry,
    Product,
    Tenant,
    utcnow,
)

MAX_ATTEMPTS = 5

# Minutos de espera tras cada fallo (indexado por intentos ya hechos); el último
# valor se repite. El worker corre cada hora: esto acota reprocesos del trigger
# manual y de corridas cercanas, no promete precisión de segundos.
BACKOFF_MINUTES = (1, 5, 15, 60)

# Sistemas a los que sabemos escribir de vuelta (crece con cada ejecutor)
WRITABLE_TARGETS = {"odoo", "shopify"}


def queue_payment_writeback(session: Session, tenant: Tenant, invoice: Invoice) -> OutboxEntry | None:
    """Encola la inyección de un pago confirmado hacia el sistema de origen."""
    if invoice.source not in WRITABLE_TARGETS:
        return None
    customer = session.get(Customer, invoice.customer_id)
    entry = OutboxEntry(
        tenant_id=tenant.id,
        target=invoice.source,
        action="registrar_pago",
        payload={
            "invoice_id": invoice.id,
            "folio": invoice.folio,
            "amount": float(invoice.amount),
            "customer": customer.name if customer else "",
            "paid_source": invoice.paid_source or "manual",
            "paid_at": invoice.paid_at.date().isoformat() if invoice.paid_at else None,
        },
    )
    session.add(entry)
    session.flush()
    return entry


def queue_customer_writeback(
    session: Session, tenant: Tenant, customer: Customer, changes: dict
) -> list[OutboxEntry]:
    """Encola la actualización de un cliente hacia los sistemas de origen donde
    vive (los que sabemos escribir). aiuda no es la fuente de verdad del maestro
    de clientes: el cambio se inyecta de vuelta a Odoo / la tienda. Si la
    presencia no trae referencia, el ejecutor lo da de alta y repara la liga."""
    if not changes:
        return []
    targets = set((customer.presence or {}).keys()) & WRITABLE_TARGETS
    entries = []
    for target in targets:
        ref = (customer.presence or {}).get(target, {}).get("ref")
        entry = OutboxEntry(
            tenant_id=tenant.id,
            target=target,
            action="actualizar_cliente",
            payload={"customer_id": customer.id, "ref": ref, "changes": changes},
        )
        session.add(entry)
        entries.append(entry)
    session.flush()
    return entries


# --------------------------------------------------------------------------- #
# Inyección de ALTAS: lo nacido en aiuda se empuja al sistema maestro           #
# --------------------------------------------------------------------------- #
# aiuda no es el sistema maestro: captura rápido y el registro viaja al maestro
# que el dueño ELIGE. A diferencia del write-back clásico (destino derivado de
# source/presence porque el registro YA vive allá), un registro aiuda-born es
# huérfano: el destino es EXPLÍCITO (check al crear o botón en la ficha). Nada
# se empuja solo.

# Qué destinos saben RECIBIR el alta de cada entidad. "custom" = una conexión a
# la medida del dueño cuya receta declare endpoint de escritura (write_path).
CREATION_TARGETS: dict[str, tuple[str, ...]] = {
    "cliente": ("odoo", "custom"),
    "producto": ("odoo", "custom"),
    "factura": ("odoo", "custom"),
    "cita": ("googlecalendar", "custom"),
}

_CREATION_ACTIONS = {
    "cliente": "crear_cliente",
    "producto": "crear_producto",
    "factura": "crear_factura",
    "cita": "crear_cita",
}

# acción -> (modelo, llave del id en el payload). También define qué acciones son
# ALTAS: un alta fallida NO se reintenta sola (un timeout ambiguo pudo crear el
# registro allá; reintentar duplicaría) — el reintento es decisión del dueño.
_ALTA_MODELOS = {
    "crear_cliente": (Customer, "customer_id"),
    "crear_producto": (Product, "product_id"),
    "crear_factura": (Invoice, "invoice_id"),
    "crear_cita": (Appointment, "appointment_id"),
}


def _entidad_de(registro) -> str:
    return {
        "Customer": "cliente",
        "Product": "producto",
        "Invoice": "factura",
        "Appointment": "cita",
    }[type(registro).__name__]


def _payload_alta(session: Session, entidad: str, registro, target: str) -> dict:
    if entidad == "cliente":
        return {
            "customer_id": registro.id,
            "name": registro.name,
            "email": registro.email,
            "phone": registro.phone,
        }
    if entidad == "producto":
        return {
            "product_id": registro.id,
            "name": registro.name,
            "sku": registro.sku,
            "price": float(registro.price) if registro.price is not None else None,
            "unit": registro.unit,
        }
    if entidad == "factura":
        customer = session.get(Customer, registro.customer_id)
        return {
            "invoice_id": registro.id,
            "folio": registro.folio,
            "amount": float(registro.amount),
            "currency": registro.currency,
            "issued_date": registro.issued_date.isoformat(),
            "due_date": registro.due_date.isoformat(),
            "concepto": (registro.meta or {}).get("concepto", ""),
            "cliente": {
                "name": customer.name if customer else "",
                "phone": customer.phone if customer else None,
                "email": customer.email if customer else None,
                # Si el cliente ya vive en el destino, la factura se cuelga de él.
                "ref": ((customer.presence or {}).get(target) or {}).get("ref")
                if customer
                else None,
            },
        }
    return {  # cita
        "appointment_id": registro.id,
        "title": registro.title,
        "starts_at": registro.starts_at.isoformat() if registro.starts_at else None,
        "notes": registro.notes,
        "customer_name": registro.customer_name,
    }


def _ya_inyectado(registro, pkey: str) -> bool:
    if isinstance(registro, Appointment):
        return pkey in ((registro.meta or {}).get("inyectada_en") or {})
    return pkey in (getattr(registro, "presence", None) or {})


def queue_creation_writeback(
    session: Session, tenant: Tenant, *, registro, target: str, conexion: dict | None = None
) -> OutboxEntry:
    """Encola el ALTA de un registro aiuda-born hacia el destino ELEGIDO por el
    dueño. `conexion` = {"id", "pkey"} cuando target == "custom" (a cuál de sus
    conexiones a la medida va; pkey = el nombre que le puso, para la presencia).
    Si el registro ya vive en ese destino, no se re-encola (ValueError legible)."""
    entidad = _entidad_de(registro)
    if target not in CREATION_TARGETS.get(entidad, ()):
        raise ValueError(f"'{target}' no recibe altas de {entidad}")
    if target == "custom" and not (conexion or {}).get("id"):
        raise ValueError("Inyectar a una conexión a la medida requiere elegir cuál")
    if entidad == "cita" and registro.starts_at is None:
        raise ValueError("La cita necesita fecha y hora para ir al calendario")
    pkey = ((conexion or {}).get("pkey") or "a la medida") if target == "custom" else target
    if _ya_inyectado(registro, pkey):
        raise ValueError(f"Este registro ya vive en {pkey}")
    payload = _payload_alta(session, entidad, registro, target)
    if target == "custom":
        payload["conexion"] = {"id": conexion["id"], "pkey": pkey}
    entry = OutboxEntry(
        tenant_id=tenant.id,
        target=target,
        action=_CREATION_ACTIONS[entidad],
        payload=payload,
    )
    session.add(entry)
    session.flush()
    return entry


def _nota_pago(payload: dict) -> str:
    nota = (
        f"aiuda: pago de {payload['folio']} por "
        f"${payload['amount']:,.2f} confirmado "
        f"({payload['paid_source']})."
    )
    # El id del outbox viaja en el memo: si un doble asiento llegara a colarse,
    # se ve a simple vista en Odoo cuál corrida lo escribió (detectabilidad).
    if payload.get("outbox_id"):
        nota += f" [outbox {payload['outbox_id']}]"
    return nota


class _Executor:
    """Base de ejecutores. `REQUIERE` mapea acción -> método del conector que la
    implementa; si el conector no lo tiene, la acción no se soporta y la entrada
    espera (estado honesto, no falla)."""

    REQUIERE: dict[str, str] = {}

    def __init__(self, client):
        self.client = client

    def soporta(self, action: str) -> bool:
        metodo = self.REQUIERE.get(action)
        return metodo is not None and callable(getattr(self.client, metodo, None))


class OdooWriteback(_Executor):
    """Ejecutor real de Odoo (XML-RPC): asienta el pago contra la factura
    (wizard account.payment.register) y escribe el maestro de clientes
    (res.partner). Cada acción devuelve su evidencia (request + respuesta)."""

    REQUIERE = {
        "registrar_pago": "register_invoice_payment",
        "actualizar_cliente": "upsert_partner",
        "crear_cliente": "upsert_partner",
        "crear_producto": "crear_producto",
        "crear_factura": "crear_factura_borrador",
    }

    def _url(self, record_id, model: str) -> str | None:
        return odoo_record_url(getattr(self.client, "url", ""), record_id, model)

    def crear_cliente(self, payload: dict) -> dict:
        datos = {"name": payload["name"], "email": payload.get("email"), "phone": payload.get("phone")}
        resp = dict(self.client.upsert_partner(None, datos))
        pid = resp["partner_id"]
        return {
            "escrito": datos,
            "respuesta": {
                "creado": True,
                "ref": str(pid),
                "url": self._url(pid, "res.partner"),
                "en_odoo": resp.get("en_odoo"),
            },
        }

    def crear_producto(self, payload: dict) -> dict:
        resp = self.client.crear_producto(
            payload["name"], sku=payload.get("sku"), price=payload.get("price"),
            unit=payload.get("unit"),
        )
        tid = resp["template_id"]
        return {
            "escrito": {k: payload.get(k) for k in ("name", "sku", "price")},
            "respuesta": {
                "creado": True,
                "ref": str(tid),
                "url": self._url(tid, "product.template"),
                "nota": "Unidad e impuestos quedaron con los defaults de Odoo.",
            },
        }

    def crear_factura(self, payload: dict) -> dict:
        resp = self.client.crear_factura_borrador(
            payload["folio"],
            cliente=payload.get("cliente") or {},
            amount=payload["amount"],
            issued_date=payload["issued_date"],
            due_date=payload["due_date"],
            concepto=payload.get("concepto", ""),
        )
        mid = resp["move_id"]
        return {
            "escrito": {k: payload.get(k) for k in ("folio", "amount", "issued_date", "due_date")},
            "respuesta": {
                "creado": True,
                "ref": str(mid),
                "url": self._url(mid, "account.move"),
                "borrador": True,
                "partner_creado": resp.get("partner_creado", False),
                "nota": "Borrador en Odoo: revisa impuestos y publica allá.",
            },
        }

    def registrar_pago(self, payload: dict) -> dict:
        memo = _nota_pago(payload)
        respuesta = self.client.register_invoice_payment(
            payload["folio"],
            amount=payload.get("amount"),
            memo=memo,
            payment_date=payload.get("paid_at"),
        )
        return {
            "escrito": {"folio": payload["folio"], "monto": payload.get("amount"), "memo": memo},
            "respuesta": respuesta,
        }

    def actualizar_cliente(self, payload: dict) -> dict:
        changes = payload.get("changes", {})
        respuesta = dict(self.client.upsert_partner(payload.get("ref"), changes))
        if respuesta.get("creado") and respuesta.get("partner_id") and not respuesta.get("url"):
            respuesta["url"] = odoo_record_url(
                getattr(self.client, "url", ""), respuesta["partner_id"], "res.partner"
            )
        return {
            "escrito": {"ref": payload.get("ref"), "cambios": changes},
            "respuesta": respuesta,
        }


class ShopifyWriteback(_Executor):
    """Shopify hoy solo sabe dejar la nota de pago en el pedido. Actualizar el
    cliente no está en REQUIERE: esa entrada espera su ejecutor (no falla)."""

    REQUIERE = {"registrar_pago": "mark_note"}

    def registrar_pago(self, payload: dict) -> dict:
        nota = _nota_pago(payload)
        pedido = payload["folio"].lstrip("#")  # el folio es el name del pedido (#1042)
        self.client.mark_note(pedido, nota)
        return {
            "escrito": {"pedido": pedido, "nota": nota},
            "respuesta": {"modo": "nota", "pedido": pedido},
        }


class GCalWriteback(_Executor):
    """Google Calendar recibe citas aiuda-born (create_event ya existía en el
    conector; esto lo cablea a la tubería). Duración default: 1 hora."""

    REQUIERE = {"crear_cita": "create_event"}

    def crear_cita(self, payload: dict) -> dict:
        start = datetime.fromisoformat(payload["starts_at"])
        ev = self.client.create_event(
            payload["title"], start, start + timedelta(hours=1),
            description=payload.get("notes") or "",
        )
        return {
            "escrito": {"title": payload["title"], "starts_at": payload["starts_at"]},
            "respuesta": {"creado": True, "ref": str(ev.id), "url": ev.html_link or None},
        }


class CustomApiWriteback(_Executor):
    """Inyección a una conexión a la medida del dueño (SU API). El 'client' es el
    tenant: la receta y el secreto viven en su config, y cada entrada dice a cuál
    conexión va (payload['conexion']). Solo funciona si la receta declara
    write_path; si no, el error lo dice tal cual."""

    ACCIONES = ("crear_cliente", "crear_producto", "crear_factura", "crear_cita")

    def __init__(self, tenant: Tenant):
        self.tenant = tenant

    def soporta(self, action: str) -> bool:
        return action in self.ACCIONES

    def _conexion(self, payload: dict) -> dict:
        cid = (payload.get("conexion") or {}).get("id")
        for src in (self.tenant.config or {}).get("custom_sources") or []:
            if src.get("id") == cid:
                return src
        raise ValueError("La conexión a la medida ya no existe (¿se borró?)")

    @staticmethod
    def _row(action: str, payload: dict) -> dict:
        """El registro con los MISMOS nombres de campo que la receta usa para leer
        (CAP_FIELDS): el mapping de la receta, invertido, arma el body."""
        if action == "crear_cliente":
            return {"name": payload["name"], "phone": payload.get("phone"), "email": payload.get("email")}
        if action == "crear_producto":
            return {"name": payload["name"], "sku": payload.get("sku"), "price": payload.get("price")}
        if action == "crear_factura":
            cliente = payload.get("cliente") or {}
            return {
                "customer": cliente.get("name"),
                "phone": cliente.get("phone"),
                "folio": payload["folio"],
                "amount": payload["amount"],
                "due_date": payload["due_date"],
            }
        return {  # crear_cita
            "title": payload["title"],
            "starts_at": payload.get("starts_at"),
            "customer": payload.get("customer_name"),
        }

    def _crear(self, action: str, payload: dict) -> dict:
        from aiuda_core.connectors import custom_api
        from aiuda_core.engine.sync import _custom_secret

        src = self._conexion(payload)
        secreto, err = _custom_secret(src)
        if err:
            raise ValueError(err)
        row = self._row(action, payload)
        data, err = custom_api.escribir_registro(
            base_url=src.get("base_url") or "",
            write_path=src.get("write_path") or "",
            row=row,
            mapping=src.get("mapping") or {},
            auth_type=src.get("auth_type") or "",
            auth_header=src.get("auth_header") or "",
            auth_value=secreto,
            token_url=src.get("token_url") or "",
            client_id=src.get("client_id") or "",
            timeout=src.get("timeout") or 15,
            write_id_path=src.get("write_id_path") or "",
        )
        if err:
            raise ValueError(err)
        return {
            "escrito": data.get("enviado") or row,
            "respuesta": {"creado": True, "ref": data.get("ref"), "url": None},
        }

    def crear_cliente(self, payload: dict) -> dict:
        return self._crear("crear_cliente", payload)

    def crear_producto(self, payload: dict) -> dict:
        return self._crear("crear_producto", payload)

    def crear_factura(self, payload: dict) -> dict:
        return self._crear("crear_factura", payload)

    def crear_cita(self, payload: dict) -> dict:
        return self._crear("crear_cita", payload)


def _executors(
    odoo_client, shopify_client, gcal_client=None, tenant: Tenant | None = None
) -> dict[str, _Executor]:
    executors: dict[str, _Executor] = {}
    if odoo_client is not None:
        executors["odoo"] = OdooWriteback(odoo_client)
    if shopify_client is not None:
        executors["shopify"] = ShopifyWriteback(shopify_client)
    if gcal_client is not None:
        executors["googlecalendar"] = GCalWriteback(gcal_client)
    if tenant is not None:
        executors["custom"] = CustomApiWriteback(tenant)
    return executors


def _reintento_pendiente(entry: OutboxEntry, now: datetime) -> bool:
    """True mientras el backoff del último fallo no venza."""
    marca = (entry.payload or {}).get("reintento_en")
    if not marca:
        return False
    try:
        return datetime.fromisoformat(marca) > now
    except ValueError:
        return False


def _sin_reintento(payload: dict) -> dict:
    return {k: v for k, v in (payload or {}).items() if k != "reintento_en"}


def _liga_alta(session: Session, entry: OutboxEntry, respuesta: dict) -> None:
    """Si el write-back dio de ALTA el registro en la fuente (no había liga), la
    presencia del cliente se actualiza con la referencia nueva: la ficha ya puede
    saltar a Odoo y el próximo write-back va por id."""
    if not respuesta.get("creado") or not respuesta.get("partner_id"):
        return
    customer = session.get(Customer, (entry.payload or {}).get("customer_id"))
    if customer is None:
        return
    add_presence(customer, entry.target, str(respuesta["partner_id"]), url=respuesta.get("url"))


def _liga_creacion(session: Session, entry: OutboxEntry, respuesta: dict) -> None:
    """Tras un alta inyectada, el registro aiuda-born queda LIGADO a su copia en
    el maestro: la presencia guarda ref+url (la ficha salta allá, y el write-back
    futuro va por id). Las citas no tienen columna presence: la liga vive en
    meta['inyectada_en'] con la misma forma."""
    if not respuesta.get("creado"):
        return
    modelo, id_key = _ALTA_MODELOS[entry.action]
    registro = session.get(modelo, (entry.payload or {}).get(id_key))
    if registro is None:
        return
    pkey = entry.target
    if entry.target == "custom":
        pkey = ((entry.payload or {}).get("conexion") or {}).get("pkey") or "a la medida"
    ref, url = respuesta.get("ref"), respuesta.get("url")
    if modelo is Appointment:
        ligas = dict((registro.meta or {}).get("inyectada_en") or {})
        ligas[pkey] = {"ref": ref, "url": url}
        registro.meta = {**(registro.meta or {}), "inyectada_en": ligas}
        return
    if ref:
        add_presence(registro, pkey, str(ref), url=url)


def reset_for_retry(entry: OutboxEntry) -> None:
    """Deja una entrada fallida lista para reintentarse YA: vuelve a `pending`
    con el presupuesto de intentos completo y sin backoff. `last_error` se
    conserva como rastro hasta que un intento logre inyectar."""
    entry.status = "pending"
    entry.attempts = 0
    entry.payload = _sin_reintento(entry.payload)


def _claim(session: Session, entry: OutboxEntry) -> bool:
    """Reclama el siguiente intento de la entrada de forma ATÓMICA (compare-and-swap
    sobre `attempts`): si otra corrida ya tomó este intento (o la entrada dejó de
    estar pending), rowcount es 0 y NO se ejecuta — el asiento de un pago jamás debe
    salir dos veces. Cinturón además del FOR UPDATE: cubre motores sin row lock y
    el reintento manual solapado con el barrido."""
    vistos = entry.attempts
    claimed = session.execute(
        update(OutboxEntry)
        .where(
            OutboxEntry.id == entry.id,
            OutboxEntry.status == "pending",
            OutboxEntry.attempts == vistos,
        )
        .values(attempts=vistos + 1)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        session.expire(entry)  # el objeto en memoria quedó atrás de la BD
        return False
    entry.attempts = vistos + 1  # refleja en el objeto lo que ya quedó en la BD
    return True


@dataclass
class WritebackResult:
    processed: int = 0
    failed: int = 0


def process_outbox(
    session: Session,
    tenant: Tenant,
    odoo_client=None,
    shopify_client=None,
    gcal_client=None,
    now: datetime | None = None,
) -> WritebackResult:
    """Procesa pendientes con los ejecutores configurados. Sin conector (o sin
    ejecutor para la acción), la entrada espera (no falla). Cada éxito persiste
    evidencia en el payload; cada fallo agenda su backoff — EXCEPTO las altas
    (crear_*): un alta fallida queda `failed` de inmediato, porque un timeout
    ambiguo pudo haber creado el registro allá y reintentar solo duplicaría; el
    reintento es decisión consciente del dueño (botón). `now` es inyectable."""
    now = now or utcnow()
    result = WritebackResult()
    executors = _executors(odoo_client, shopify_client, gcal_client, tenant)
    entries = session.scalars(
        select(OutboxEntry)
        .where(
            OutboxEntry.tenant_id == tenant.id,
            OutboxEntry.status == "pending",
            OutboxEntry.attempts < MAX_ATTEMPTS,
        )
        .order_by(OutboxEntry.created_at)
        # Dinero: una corrida solapada SALTA las filas que esta ya tiene en vez de
        # esperarlas y re-asentarlas. (Postgres; SQLite lo ignora sin ruido.) El
        # candado dura hasta el commit por-entrada de abajo; después de ese commit
        # el CAS de _claim es el que garantiza un solo ejecutor por intento.
        .with_for_update(skip_locked=True)
    ).all()

    for entry in entries:
        executor = executors.get(entry.target)
        if executor is None:
            continue  # el conector no está configurado todavía: la entrada espera
        if not executor.soporta(entry.action):
            continue  # el conector aún no sabe escribir esta acción: espera su ejecutor
        if _reintento_pendiente(entry, now):
            continue  # backoff del último fallo aún vigente: todavía no toca
        if not _claim(session, entry):
            continue  # otra corrida reclamó este intento primero: no se re-ejecuta
        # DINERO: el intento reclamado se commitea ANTES de tocar la fuente. Si el
        # proceso muere a media inyección, el intento ya contó contra MAX_ATTEMPTS
        # en vez de repetirse sin memoria.
        session.commit()
        try:
            evidencia = getattr(executor, entry.action)(
                {**entry.payload, "outbox_id": entry.id}
            )
            entry.status = "done"
            entry.done_at = now
            entry.last_error = None
            # Columna JSON: siempre reasignar (no trackea mutación in-place)
            entry.payload = {
                **_sin_reintento(entry.payload),
                "evidencia": {**evidencia, "en": now.isoformat()},
            }
            if entry.action == "actualizar_cliente":
                _liga_alta(session, entry, evidencia.get("respuesta") or {})
            elif entry.action in _ALTA_MODELOS:
                _liga_creacion(session, entry, evidencia.get("respuesta") or {})
            result.processed += 1
        except Exception as exc:
            entry.last_error = str(exc)[:500]
            if entry.action in _ALTA_MODELOS or entry.attempts >= MAX_ATTEMPTS:
                # Las altas nunca se reintentan solas (ver docstring); lo demás
                # agota su presupuesto de intentos primero.
                entry.status = "failed"
                entry.payload = _sin_reintento(entry.payload)
            else:
                espera = BACKOFF_MINUTES[min(entry.attempts - 1, len(BACKOFF_MINUTES) - 1)]
                entry.payload = {
                    **entry.payload,
                    "reintento_en": (now + timedelta(minutes=espera)).isoformat(),
                }
            result.failed += 1
        # El veredicto de CADA entrada queda durable en cuanto la fuente respondió.
        # Antes solo se flusheaba y el commit lo daba la transacción del caller (la
        # corrida del tenant, que envuelve también sync y LLM): un error posterior
        # hacía rollback, el 'done' volvía a 'pending' y la siguiente corrida
        # asentaba el MISMO pago otra vez en la contabilidad del cliente.
        session.commit()
    return result
