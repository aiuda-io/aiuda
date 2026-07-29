"""Conector Odoo (XML-RPC): lectura de cartera/catálogo/clientes/compras y
write-back real (pago y cliente).

Lectura: `fetch_open_invoices` (cuentas_por_cobrar), `fetch_partners`
(directorio_clientes), `fetch_products` (catalogo_productos),
`fetch_purchase_orders` (compras).

Escritura (write-back, ejecutada por engine/writeback.py):

    acción               modelo Odoo               método
    -------------------  ------------------------  -------------------------
    registrar_pago       account.payment.register  register_invoice_payment()
    alta/act. cliente    res.partner               upsert_partner()
    constancia (nota)    account.move (chatter)    add_invoice_note()

El transporte `_execute(model, method, ...)` es genérico: crecer NO toca la
plomería, se agrega un método tipado y se declara en SOURCE_CAPS
(cloud/.../api/integrations.py). Mientras un método no exista, la capacidad va
como live=False ("próximamente"): no se promete en la UI lo que el conector
aún no hace.
"""

import http.client
import logging
import time
import xmlrpc.client
from dataclasses import dataclass
from datetime import date

from aiuda_core.folios import FOLIO_PROVISIONAL_PREFIX, es_provisional, folio_provisional

log = logging.getLogger("aiuda.odoo")

# Odoo por XML-RPC no acepta timeout directo: un servidor lento colgaba el hilo
# del worker indefinidamente (ocupando un slot hasta el job_timeout de 5 min). Un
# Transport con timeout lo corta. Se elige Safe (https) o normal (http) por el URL.
_ODOO_TIMEOUT = 30

# Lecturas por lotes: search_read con limit/offset (+ orden estable por id) en vez
# de traer la tabla entera en un solo roundtrip. Sin límite, una cartera grande se
# cargaba completa a memoria del worker (o reventaba el timeout). El tope corta la
# lectura: queda parcial y se dice en el log — no se truena ni se inventa. Ambos
# son parámetros del constructor por si un negocio necesita otro tamaño.
_ODOO_PAGE_SIZE = 200
_ODOO_MAX_RECORDS = 5000

# Reintentos SOLO de lecturas idempotentes ante errores transitorios (red/timeout/
# 5xx del transporte). Un write (create/write/message_post/action_create_payments)
# NUNCA se reintenta: un timeout es ambiguo — la petición pudo haber llegado a
# Odoo — y repetirla duplicaría el efecto (p.ej. asentar un pago dos veces).
_ODOO_REINTENTOS = 2  # además del intento original: 3 intentos en total
_ODOO_BACKOFF_S: tuple[float, ...] = (1.0, 3.0)  # espera antes del 1er y 2o reintento
_METODOS_REINTENTABLES = {"search_read", "read", "search", "search_count", "fields_get"}


def _es_error_transitorio(exc: Exception) -> bool:
    """¿Vale la pena reintentar? Solo red/timeout/5xx del transporte. Un Fault de
    Odoo (credenciales, permisos, datos) o un 4xx HTTP no se reintentan: repetir
    la misma llamada no los arregla."""
    if isinstance(exc, xmlrpc.client.Fault):
        return False  # error de aplicación de Odoo (auth, permisos, datos)
    if isinstance(exc, xmlrpc.client.ProtocolError):
        return 500 <= exc.errcode < 600
    if isinstance(exc, PermissionError):
        return False  # credenciales malas (subclase de OSError: se excluye ANTES)
    return isinstance(exc, (OSError, http.client.HTTPException))


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = _ODOO_TIMEOUT
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = _ODOO_TIMEOUT
        return conn


def _proxy(url: str) -> xmlrpc.client.ServerProxy:
    transport = _TimeoutSafeTransport() if url.lower().startswith("https") else _TimeoutTransport()
    return xmlrpc.client.ServerProxy(url, transport=transport)


def _as_date(value) -> date | None:
    """Odoo manda False en fechas vacías (p.ej. un borrador aún sin fecha de emisión);
    si viene, es 'YYYY-MM-DD'. Devuelve date o None, nunca lanza."""
    return date.fromisoformat(value) if isinstance(value, str) and value else None


@dataclass
class OdooInvoice:
    move_id: int
    folio: str
    customer_name: str
    customer_phone: str
    amount: float
    currency: str
    issued_date: date
    due_date: date
    partner_id: int = 0  # res.partner de Odoo: liga el CLIENTE a su registro fuente


@dataclass
class OdooProduct:
    product_id: int
    name: str
    sku: str
    price: float
    stock: float
    unit: str


@dataclass
class OdooPartner:
    partner_id: int
    name: str
    phone: str
    email: str


@dataclass
class OdooPurchaseOrder:
    order_id: int
    folio: str
    supplier: str
    total: float
    currency: str
    status: str
    ordered_at: str  # ISO 'YYYY-MM-DD' o ''


class OdooConnector:
    def __init__(
        self,
        url: str,
        db: str,
        username: str,
        api_key: str,
        page_size: int = _ODOO_PAGE_SIZE,
        max_records: int = _ODOO_MAX_RECORDS,
    ):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.api_key = api_key
        self.page_size = page_size
        self.max_records = max_records
        self._uid: int | None = None
        self._fields_cache: dict[str, set[str]] = {}
        # Un solo proxy al endpoint object, reusado: xmlrpc hace keep-alive del socket
        # entre llamadas si no se recrea. Recrearlo por llamada forzaba un handshake TLS
        # nuevo cada vez (un sync = ~10 handshakes -> timeouts en Odoo remoto).
        self._models: xmlrpc.client.ServerProxy | None = None

    def _authenticate(self) -> int:
        if self._uid is None:
            common = _proxy(f"{self.url}/xmlrpc/2/common")
            uid = common.authenticate(self.db, self.username, self.api_key, {})
            if not uid:
                raise PermissionError("Autenticación con Odoo falló — revisa credenciales")
            self._uid = uid
        return self._uid

    def _execute(self, model: str, method: str, *args, **kwargs):
        """Un roundtrip XML-RPC. Las lecturas (_METODOS_REINTENTABLES) reintentan
        con backoff corto ante errores transitorios y cada reintento queda en el
        log; los writes van a un solo intento (ver _es_error_transitorio)."""
        intentos = 1 + (_ODOO_REINTENTOS if method in _METODOS_REINTENTABLES else 0)
        for intento in range(1, intentos + 1):
            try:
                uid = self._authenticate()
                if self._models is None:
                    self._models = _proxy(f"{self.url}/xmlrpc/2/object")
                return self._models.execute_kw(
                    self.db, uid, self.api_key, model, method, list(args), kwargs
                )
            except Exception as exc:
                if intento >= intentos or not _es_error_transitorio(exc):
                    raise
                self._models = None  # el socket pudo quedar muerto: reconexión limpia
                espera = _ODOO_BACKOFF_S[min(intento - 1, len(_ODOO_BACKOFF_S) - 1)]
                log.warning(
                    "Odoo %s.%s: error transitorio (%s); reintento %s/%s en %.0fs.",
                    model,
                    method,
                    exc,
                    intento,
                    _ODOO_REINTENTOS,
                    espera,
                )
                time.sleep(espera)

    def _search_read_paginado(self, model: str, domain: list, fields: list[str]) -> list[dict]:
        """search_read por lotes (limit/offset) con orden estable por id: sin orden
        fijo, Odoo pagina sobre su _order por defecto (name, fechas...) y entre
        páginas se pueden colar o perder registros. Corta en `max_records`: la
        lectura queda parcial y se avisa en el log, en vez de cargar una tabla
        enorme a memoria del worker."""
        records: list[dict] = []
        offset = 0
        while True:
            page = self._execute(
                model,
                "search_read",
                domain,
                fields=fields,
                limit=self.page_size,
                offset=offset,
                order="id",
            )
            records.extend(page)
            if len(page) < self.page_size:
                return records
            if len(records) >= self.max_records:
                log.warning(
                    "Odoo %s: lectura topada en %s registros (puede haber más; el tope "
                    "max_records del conector corta para no cargar todo a memoria).",
                    model,
                    self.max_records,
                )
                return records[: self.max_records]
            offset += self.page_size

    def _existing_fields(self, model: str, wanted: list[str]) -> list[str]:
        """De `wanted`, los campos que EXISTEN en `model`. El esquema de Odoo cambia
        entre versiones (p.ej. Odoo 19 quitó `mobile` de res.partner); pedir un campo
        inexistente tumba el search_read entero. Se filtra contra fields_get, cacheado
        por modelo para no repetir la llamada. Si algo falla, se devuelve `wanted` tal
        cual (no peor que hoy)."""
        if model not in self._fields_cache:
            try:
                got = self._execute(model, "fields_get", [], attributes=["type"])
                self._fields_cache[model] = set(got or {})
            except Exception:
                self._fields_cache[model] = set(wanted)
        return [f for f in wanted if f in self._fields_cache[model]]

    def test_connection(self) -> dict:
        """Prueba ligera para 'Probar conexión': versión del servidor + autenticación
        real + conteos honestos. No trae datos pesados.

        `partners` cuenta TODOS los contactos (señal de vida del servidor), pero lo
        que aiuda ingiere es menos: `clientes` cuenta customer_rank>0 (el mismo
        filtro de fetch_partners) e `invoices` la cartera con saldo pendiente (el
        mismo filtro de fetch_open_invoices). Antes el botón reportaba los 25
        contactos de Hanova como si fueran clientes cuando el sync lee 3: señal
        engañosa para el dueño."""
        common = _proxy(f"{self.url}/xmlrpc/2/common")
        version = (common.version() or {}).get("server_version", "?")
        self._authenticate()  # valida db/usuario/api_key; lanza si falla
        partners = self._execute("res.partner", "search_count", [])
        clientes = self._execute("res.partner", "search_count", [("customer_rank", ">", 0)])
        invoices = self._execute(
            "account.move",
            "search_count",
            [
                ("move_type", "=", "out_invoice"),
                ("state", "in", ["draft", "posted"]),
                ("amount_residual", ">", 0),
            ],
        )
        return {
            "version": version,
            "partners": partners,
            "clientes": clientes,
            "invoices": invoices,
        }

    # --- Write-back (escritura hacia Odoo) --------------------------------- #

    def _find_move_id(self, folio: str) -> int:
        """Resuelve la factura en Odoo: por id si el folio es provisional
        (`borrador-<id>`, nuestra convención para borradores sin número) o por
        `name` si es un folio real."""
        if es_provisional(folio):
            try:
                move_id = int(folio.removeprefix(FOLIO_PROVISIONAL_PREFIX))
            except ValueError:
                raise LookupError(f"Folio provisional ilegible: {folio}")
            ids = self._execute("account.move", "search", [("id", "=", move_id)], limit=1)
        else:
            ids = self._execute("account.move", "search", [("name", "=", folio)], limit=1)
        if not ids:
            raise LookupError(f"Factura {folio} no encontrada en Odoo")
        return int(ids[0])

    def add_invoice_note(self, folio: str, note: str) -> None:
        """Write-back mínimo: deja constancia en el chatter de la factura."""
        move_id = self._find_move_id(folio)
        self._execute("account.move", "message_post", [move_id], body=note)

    def register_invoice_payment(
        self,
        folio: str,
        amount: float | None = None,
        memo: str = "",
        payment_date: str | None = None,
    ) -> dict:
        """Write-back real de un pago: lo asienta contra la factura con el wizard
        estándar `account.payment.register` (lo mismo que el botón "Registrar
        pago" de Odoo) y Odoo lo concilia. Devuelve la evidencia: modo, ids y
        cómo quedó la factura en Odoo (payment_state, saldo).

        Casos honestos:
        - Factura sin publicar: Odoo no permite asentar pagos sobre borradores;
          queda constancia en el chatter (modo "nota") y se dice tal cual.
        - Ya saldada en Odoo: no se escribe nada (modo "ya_pagada") para no
          duplicar el cobro.
        - El monto se acota al saldo vigente en Odoo (si allá ya abonaron parte,
          registrar el total duplicaría).
        """
        move_id = self._find_move_id(folio)
        move = self._execute(
            "account.move",
            "read",
            [move_id],
            fields=["name", "state", "amount_residual", "payment_state"],
        )[0]
        residual = float(move.get("amount_residual") or 0)
        if move.get("state") != "posted":
            if memo:
                self._execute("account.move", "message_post", [move_id], body=memo)
            return {
                "modo": "nota",
                "move_id": move_id,
                "detalle": "La factura está sin publicar en Odoo; el pago no se puede asentar, quedó nota en el chatter.",
            }
        if residual <= 0:
            return {
                "modo": "ya_pagada",
                "move_id": move_id,
                "payment_state": move.get("payment_state") or "",
                "detalle": "Odoo ya tenía la factura saldada; no se escribió nada para no duplicar el cobro.",
            }
        monto = min(float(amount), residual) if amount else residual
        vals: dict = {"amount": monto}
        if memo:
            vals["communication"] = memo
        if payment_date:
            vals["payment_date"] = payment_date  # 'YYYY-MM-DD'
        ctx = {"active_model": "account.move", "active_ids": [move_id]}
        wizard_id = self._execute("account.payment.register", "create", vals, context=ctx)
        accion = self._execute(
            "account.payment.register", "action_create_payments", [wizard_id], context=ctx
        )
        payment_id = accion.get("res_id") if isinstance(accion, dict) else None
        despues = self._execute(
            "account.move", "read", [move_id], fields=["amount_residual", "payment_state"]
        )[0]
        return {
            "modo": "pago",
            "move_id": move_id,
            "payment_id": payment_id,
            "monto": monto,
            "payment_state": despues.get("payment_state") or "",
            "saldo_odoo": float(despues.get("amount_residual") or 0),
        }

    _PARTNER_WRITE_FIELDS = {"name", "email", "phone"}

    @staticmethod
    def _parse_partner_ref(ref) -> int | None:
        """La presencia guarda el res.partner como str(id); tolera formas como
        'res.partner/12'. None/ilegible = sin liga (procede el alta)."""
        if ref in (None, "", 0):
            return None
        try:
            return int(str(ref).rsplit("/", 1)[-1])
        except ValueError:
            return None

    def upsert_partner(self, ref, changes: dict) -> dict:
        """Write-back del maestro de clientes: actualiza el res.partner ligado o
        lo da de alta si no hay liga. Solo campos del maestro (name/email/phone);
        Odoo guarda los vacíos como False. Devuelve cómo quedó en Odoo."""
        vals = {
            k: (v if v not in (None, "") else False)
            for k, v in (changes or {}).items()
            if k in self._PARTNER_WRITE_FIELDS
        }
        if not vals:
            raise ValueError("Sin campos del maestro que escribir en Odoo")
        partner_id = self._parse_partner_ref(ref)
        creado = False
        if partner_id is None:
            if not vals.get("name"):
                raise ValueError("El alta de cliente en Odoo necesita al menos el nombre")
            # customer_rank>0 = cliente (así lo filtra fetch_partners y la vista de Odoo)
            partner_id = int(self._execute("res.partner", "create", {**vals, "customer_rank": 1}))
            creado = True
        else:
            self._execute("res.partner", "write", [partner_id], vals)
        en_odoo = self._execute(
            "res.partner",
            "read",
            [partner_id],
            fields=self._existing_fields("res.partner", ["name", "email", "phone"]),
        )[0]
        return {
            "partner_id": partner_id,
            "creado": creado,
            "en_odoo": {k: (v or "") for k, v in en_odoo.items() if k != "id"},
        }

    def crear_producto(self, name: str, sku=None, price=None, unit=None) -> dict:
        """Alta de un producto aiuda-born en el catálogo de Odoo (product.template).
        Campos mínimos del maestro; unidad/impuestos quedan con los defaults de
        Odoo (el dueño afina allá — Odoo sigue siendo el sistema maestro)."""
        if not (name or "").strip():
            raise ValueError("El alta de producto en Odoo necesita el nombre")
        vals: dict = {"name": name.strip()}
        if sku not in (None, ""):
            vals["default_code"] = str(sku)
        if price is not None:
            vals["list_price"] = float(price)
        template_id = int(self._execute("product.template", "create", vals))
        return {"template_id": template_id, "creado": True}

    def _partner_para_factura(self, cliente: dict) -> tuple[int, bool]:
        """Resuelve el res.partner de una factura aiuda-born: por la liga de
        presencia si existe, por nombre exacto si ya vive allá, o alta. Devuelve
        (partner_id, creado)."""
        pid = self._parse_partner_ref((cliente or {}).get("ref"))
        if pid is not None:
            return pid, False
        name = (cliente or {}).get("name", "").strip()
        if not name:
            raise ValueError("La factura necesita el nombre del cliente")
        hallados = self._execute("res.partner", "search", [("name", "=", name)], limit=1)
        if hallados:
            return int(hallados[0]), False
        resp = self.upsert_partner(
            None,
            {"name": name, "email": cliente.get("email"), "phone": cliente.get("phone")},
        )
        return int(resp["partner_id"]), True

    def crear_factura_borrador(
        self,
        folio: str,
        cliente: dict,
        amount,
        issued_date: str,
        due_date: str,
        concepto: str = "",
    ) -> dict:
        """Alta de una factura aiuda-born en Odoo como BORRADOR (account.move
        out_invoice con una línea por el total). El dueño revisa impuestos y
        publica/timbra EN Odoo — aiuda no timbra ni postea. La línea va sin
        impuestos a propósito: price_unit = el total capturado en aiuda; si el
        negocio maneja IVA lo ajusta al revisar (la narración lo recuerda)."""
        partner_id, partner_creado = self._partner_para_factura(cliente)
        vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id,
            "invoice_date": issued_date,
            "invoice_date_due": due_date,
            "ref": folio,
            "narration": (
                f"Creada desde aiuda (folio {folio}). Revisa impuestos y publica "
                "cuando la valides; aiuda no postea borradores."
            ),
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "name": (concepto or f"Servicios {folio}").strip(),
                        "quantity": 1,
                        "price_unit": float(amount),
                    },
                )
            ],
        }
        move_id = int(self._execute("account.move", "create", vals))
        return {
            "move_id": move_id,
            "creado": True,
            "borrador": True,
            "partner_id": partner_id,
            "partner_creado": partner_creado,
        }

    def fetch_partners(self) -> list[OdooPartner]:
        """Directorio de clientes (res.partner con customer_rank>0). Capacidad
        `directorio_clientes`. Odoo manda False en campos vacíos -> se normaliza."""
        records = self._search_read_paginado(
            "res.partner",
            [("customer_rank", ">", 0)],
            fields=self._existing_fields("res.partner", ["name", "mobile", "phone", "email"]),
        )
        partners = []
        for rec in records:
            raw_phone = rec.get("mobile") or rec.get("phone") or ""
            phone = raw_phone.replace(" ", "") if isinstance(raw_phone, str) else ""
            email = rec.get("email") if isinstance(rec.get("email"), str) else ""
            partners.append(
                OdooPartner(
                    partner_id=int(rec["id"]),
                    name=rec["name"],
                    phone=phone,
                    email=email,
                )
            )
        return partners

    def fetch_products(self) -> list[OdooProduct]:
        """Catálogo vendible: nombre, SKU, precio de lista y existencia. Capacidad
        `catalogo_productos` (la siguiente del conector tras cuentas_por_cobrar)."""
        records = self._search_read_paginado(
            "product.template",
            [("sale_ok", "=", True)],
            fields=self._existing_fields(
                "product.template",
                ["name", "default_code", "list_price", "qty_available", "uom_id"],
            ),
        )
        products = []
        for rec in records:
            products.append(
                OdooProduct(
                    product_id=int(rec["id"]),
                    name=rec["name"],
                    sku=(rec.get("default_code") or ""),  # Odoo manda False si vacío
                    price=float(rec.get("list_price") or 0),
                    stock=float(rec.get("qty_available") or 0),
                    unit=(rec["uom_id"][1] if rec.get("uom_id") else ""),
                )
            )
        return products

    def fetch_purchase_orders(self) -> list[OdooPurchaseOrder]:
        """Órdenes de compra (purchase.order). Capacidad `compras`: Roberto vigila cuáles
        no han confirmado. Odoo manda False en campos vacíos -> se normaliza."""
        records = self._search_read_paginado(
            "purchase.order",
            [],
            fields=self._existing_fields(
                "purchase.order",
                ["name", "partner_id", "amount_total", "currency_id", "state", "date_order"],
            ),
        )
        out = []
        for rec in records:
            fecha = rec.get("date_order")
            out.append(
                OdooPurchaseOrder(
                    order_id=int(rec["id"]),
                    folio=(rec.get("name") or ""),
                    supplier=(rec["partner_id"][1] if rec.get("partner_id") else ""),
                    total=float(rec.get("amount_total") or 0),
                    currency=(rec["currency_id"][1] if rec.get("currency_id") else ""),
                    status=(rec.get("state") or ""),
                    ordered_at=(fecha[:10] if isinstance(fecha, str) else ""),
                )
            )
        return out

    def fetch_open_invoices(self) -> list[OdooInvoice]:
        records = self._search_read_paginado(
            "account.move",
            # Se incluyen borradores además de publicadas: muchos negocios (Hanova entre
            # ellos) llevan su cartera en borrador y no "publican" en Odoo. Se excluyen las
            # canceladas. amount_residual>0 = lo que sigue sin pagarse.
            [
                ("move_type", "=", "out_invoice"),
                ("state", "in", ["draft", "posted"]),
                ("amount_residual", ">", 0),
            ],
            fields=[
                "name",
                "partner_id",
                "amount_residual",
                "currency_id",
                "invoice_date",
                "invoice_date_due",
            ],
        )
        # UN solo read de res.partner con todos los clientes de la cartera (antes
        # era un read POR factura: N+1 roundtrips XML-RPC que con cientos de
        # facturas ahogaban la corrida de sync). Ids deduplicados en orden.
        partner_ids = list(
            dict.fromkeys(int(rec["partner_id"][0]) for rec in records if rec.get("partner_id"))
        )
        partners: dict[int, dict] = {}
        if partner_ids:
            leidos = self._execute(
                "res.partner",
                "read",
                partner_ids,
                fields=self._existing_fields("res.partner", ["name", "mobile", "phone"]),
            )
            partners = {int(p["id"]): p for p in leidos}
        invoices = []
        for rec in records:
            pid = rec.get("partner_id")
            if not pid:
                continue  # sin cliente no hay a quién cobrar
            partner = partners.get(int(pid[0]))
            if partner is None:
                continue  # el read no lo trajo (p.ej. borrado entre lecturas)
            phone = (partner.get("mobile") or partner.get("phone") or "").replace(" ", "")
            # Un borrador puede no traer fecha de emisión ni folio todavía: la emisión cae al
            # vencimiento (y viceversa); sin ninguna fecha no se puede razonar antigüedad, se
            # omite. El folio sintético (por id) mantiene estable la deduplicación.
            issued = _as_date(rec.get("invoice_date")) or _as_date(rec.get("invoice_date_due"))
            due = _as_date(rec.get("invoice_date_due")) or issued
            if issued is None:
                continue
            folio = rec["name"] if isinstance(rec.get("name"), str) else folio_provisional(rec["id"])
            invoices.append(
                OdooInvoice(
                    move_id=int(rec["id"]),
                    folio=folio,
                    customer_name=partner["name"],
                    customer_phone=phone,
                    amount=rec["amount_residual"],
                    currency=rec["currency_id"][1] if rec.get("currency_id") else "MXN",
                    issued_date=issued,
                    due_date=due,
                    partner_id=int(pid[0]),
                )
            )
        return invoices

    def fetch_invoice_states(self, move_ids: list[int]) -> dict[int, dict]:
        """Lectura DIRIGIDA del estado real de facturas por id (account.move).

        La usa el sync para cerrar honesto: cuando una factura que aiuda tenía como
        abierta ya no aparece en `fetch_open_invoices` (salió del dominio
        amount_residual>0), no se adivina — se pregunta a Odoo cómo quedó. Devuelve
        `{move_id: {name, state, payment_state, amount_residual}}` SOLO de los ids
        que Odoo trajo; un id que Odoo ya no tenga (borrado) simplemente no aparece,
        y el sync lo deja como está. Mismos campos que lee el write-back de pago
        (`register_invoice_payment`). `read` es idempotente: reintenta transitorios."""
        if not move_ids:
            return {}
        leidos = self._execute(
            "account.move",
            "read",
            list(move_ids),
            fields=["name", "state", "payment_state", "amount_residual"],
        )
        return {int(r["id"]): r for r in (leidos or [])}
