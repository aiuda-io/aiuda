from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiuda_core.models.base import Base, TenantMixin, TimestampMixin, new_id


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    # Número de WhatsApp del dueño/admin (recibe aprobaciones y resumen diario)
    owner_phone: Mapped[str] = mapped_column(String(32))
    # Instancia de Evolution API asignada a este tenant
    evolution_instance: Mapped[str] = mapped_column(String(64), unique=True)
    # Flags: {"auto_send_buckets": ["vence_pronto"], ...}
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class Customer(Base, TenantMixin, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "phone"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    # Opcional: un cliente sin teléfono sigue siendo cliente (vive en el directorio,
    # tiene saldo), solo que aún no se le puede contactar por WhatsApp. El teléfono
    # se agrega después. La unicidad (tenant, phone) ignora los NULL: SQL trata cada
    # NULL como distinto, así que conviven muchos clientes sin teléfono.
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    presence: Mapped[dict] = mapped_column(JSON, default=dict)
    # Etiquetas del negocio (ids que apuntan a tenant.config["tags"]).
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # cliente | prospecto — un prospecto es un posible cliente (lo trabaja Sofía).
    kind: Mapped[str] = mapped_column(String(16), default="cliente", index=True)
    # Bolsa flexible: empresa, origen, señal de compra, etc. (sobre todo prospectos).
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Product(Base, TenantMixin, TimestampMixin):
    """Catálogo de productos del negocio. Lo alimentan Carlos (ventas) y Roberto
    (compras). Entra por importación de Excel o, después, desde la tienda/ERP."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    stock: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="excel")
    presence: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Appointment(Base, TenantMixin, TimestampMixin):
    """Citas y agenda del negocio. Las atiende Valeria (recepción). Entran por
    importación de Excel o, después, desde Google Calendar."""

    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Hora de pared (local del negocio); naive a propósito: lo que el usuario
    # escribe es lo que se muestra, sin reinterpretar zona horaria.
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="excel")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class PurchaseOrder(Base, TenantMixin, TimestampMixin):
    """Órdenes de compra del negocio. Las vigila Roberto (compras): detecta proveedores
    que no han confirmado. Entran desde Odoo (purchase.order) o, después, de otra fuente
    que liste OCs —misma capacidad, ninguna privilegiada."""

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "folio"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    folio: Mapped[str] = mapped_column(String(64))  # número de OC en la fuente
    supplier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="MXN")
    # Estado tal cual en la fuente (Odoo: draft, sent, purchase, done, cancel).
    status: Mapped[str] = mapped_column(String(24), default="")
    ordered_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="odoo")
    presence: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Invoice(Base, TenantMixin, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "folio"),
        CheckConstraint(
            "status in ('open','paid','cancelled')", name="ck_invoice_status"
        ),
        CheckConstraint(
            "verified in ('sin_verificar','verificada')", name="ck_invoice_verified"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    folio: Mapped[str] = mapped_column(String(64))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="MXN")
    issued_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | paid | cancelled
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Procedencia y verificación: cada dato existe por una razón rastreable.
    source: Mapped[str] = mapped_column(String(16), default="excel")  # excel | csv | odoo
    # Presencia multi-sistema: el mismo registro puede vivir en varios lugares.
    # {"odoo": {"ref": "F-102", "url": "https://..."}, "excel": {"ref": "F-102"}}
    presence: Mapped[dict] = mapped_column(JSON, default=dict)
    verified: Mapped[str] = mapped_column(String(16), default="sin_verificar")  # sin_verificar | verificada
    # El cliente DICE que pagó — pendiente de confirmar contra banco/registro. Un dicho no es un pago.
    payment_reported: Mapped[bool] = mapped_column(default=False)
    paid_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # manual | banco | odoo
    # Columnas extra del Excel del usuario que no son campo nuestro pero no se tiran.
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # Comprobante fiscal (CFDI). Llega de FacturAPI/Facturama/SAT. cfdi = datos
    # parseados (uuid, rfcs, total, iva...); cfdi_xml/cfdi_pdf = archivos para
    # ver/descargar. Vacío hasta que la factura se timbre o se adjunte.
    cfdi: Mapped[dict] = mapped_column(JSON, default=dict)
    cfdi_xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cfdi_pdf: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)


class CfdiBoveda(Base, TenantMixin, TimestampMixin):
    """La bóveda fiscal: cada CFDI del negocio, una sola vez (dedupe por UUID).

    Entra por el web service del SAT (Descarga Masiva con la e.firma) o subiendo
    XML/ZIP a mano. Un negocio puede tener hasta TRES empresas (RFCs): `direccion`
    dice de cuál lado quedó el negocio — la emitió una de sus empresas, la recibió,
    o las dos (intercompania: una empresa suya le facturó a otra; ese dinero se
    mueve dentro de la misma casa y NO cuenta como cartera). El XML completo se
    guarda aquí; la cartera (Invoice) solo nace de ingresos (I) emitidos a crédito
    (PPD), enlazados por `invoice_id`."""

    __tablename__ = "cfdi_boveda"
    __table_args__ = (UniqueConstraint("tenant_id", "uuid"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    uuid: Mapped[str] = mapped_column(String(36), index=True)
    # I ingreso | E egreso | P pago | N nómina | T traslado
    tipo: Mapped[str] = mapped_column(String(4), default="I")
    metodo_pago: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # PUE | PPD
    folio: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fecha: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # tal cual el CFDI
    rfc_emisor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    nombre_emisor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rfc_receptor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    nombre_receptor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    moneda: Mapped[str] = mapped_column(String(8), default="MXN")
    # emitida | recibida | intercompania | desconocida (relativo a las empresas del negocio)
    direccion: Mapped[str] = mapped_column(String(16), default="desconocida", index=True)
    source: Mapped[str] = mapped_column(String(16), default="sat")  # sat | importado
    # Referencia suave (sin FK, como el resto del esquema) a la factura de cartera.
    invoice_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    xml: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Reminder(Base, TenantMixin, TimestampMixin):
    """Trabajo redactado por un agente que espera aprobación humana.

    Nació para recordatorios de cobranza; la bandeja es del equipo completo:
    cotizaciones de ventas, avisos, etc. (invoice_id es opcional)."""

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft','pending_approval','approved','sent','rejected','failed')",
            name="ck_reminder_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    agent: Mapped[str] = mapped_column(String(24), default="mariana", index=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("invoices.id"), nullable=True, index=True
    )
    # Para trabajos sin factura (ej. cotización): qué es y para quién
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    bucket: Mapped[str] = mapped_column(String(32))
    tone: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    # Canal por el que se entrega: whatsapp (vivo) | correo | sms. Lo decide el
    # humano al aprobar, según los canales conectados y los datos del cliente.
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    # draft → pending_approval → approved → sent | rejected | failed
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Contexto del trabajo para quien aprueba (no se envía al cliente). Ej. la
    # `procedencia` de una cotización: de qué fuente salieron los precios.
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class PaymentPromise(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payment_promises"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    promised_date: Mapped[date] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fulfilled: Mapped[bool] = mapped_column(default=False)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Payment(Base, TenantMixin, TimestampMixin):
    """Un pago que llegó (banco/Stripe/manual) y espera conciliación. Diego propone
    a qué factura corresponde; el humano confirma, corrige o lo ignora. Un match de
    monto NO cierra la factura solo — la soberanía es del humano (igual que un dicho
    del cliente no es un pago)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status in ('pendiente','conciliado','ignorado')", name="ck_payment_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="MXN")
    paid_at: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))  # banco | stripe | manual | reportado
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Quién depositó/cobró, tal como lo reporta el banco/pasarela (pista de match).
    counterparty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pendiente", index=True
    )  # pendiente | conciliado | ignorado
    invoice_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("invoices.id"), nullable=True, index=True
    )  # se fija al conciliar
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Conversation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "remote_phone"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    remote_phone: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    # El humano puede tomar el control cuando quiera; el agente se pausa.
    human_takeover: Mapped[bool] = mapped_column(default=False)


class Message(Base, TenantMixin, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in | out
    author: Mapped[str] = mapped_column(String(8), default="agent")  # agent | human
    body: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Solo salientes: pending (encolado, sin veredicto) | sent | failed | held (sombra).
    # NULL en entrantes y en el histórico previo a esta columna (sin rastreo).
    delivery: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)


class WhatsappChat(Base, TenantMixin, TimestampMixin):
    """Triage de las conversaciones de WhatsApp que wacli trae del store local.

    Una fila por JID que el dueño YA clasificó: ligado a un cliente (customer_id) o
    descartado (no es cliente: chat personal, grupo, spam). Los JID sin clasificar no
    tienen fila; se derivan en vivo del listado de wacli y aparecen como 'por revisar'.
    No guardamos los mensajes (viven en wacli); solo la decisión de triage."""

    __tablename__ = "whatsapp_chats"
    __table_args__ = (UniqueConstraint("tenant_id", "jid"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    jid: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    dismissed: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Nombre del chat al clasificar (referencia humana; el nombre vivo lo da wacli).
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class OutboxEntry(Base, TenantMixin, TimestampMixin):
    """Write-back: lo que aiuda registra se inyecta de regreso al sistema fuente.

    aiuda no acumula verdad propia — la devuelve a donde el negocio registra
    (Odoo, la tienda, etc.). Patrón outbox transaccional: el evento se encola
    junto con la transacción y un worker lo procesa con reintentos."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','done','failed')", name="ck_outbox_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    target: Mapped[str] = mapped_column(String(24))  # odoo | shopify | woocommerce | ...
    action: Mapped[str] = mapped_column(String(32))  # registrar_pago | nota_gestion | ...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | done | failed
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageEvent(Base, TenantMixin, TimestampMixin):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    model: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)


class Ayudante(Base, TenantMixin, TimestampMixin):
    """Un ayudante que el dueño crea y compone (capability-first).

    No hay ayudantes con nombre pre-hechos: el dueño crea el suyo, lo nombra, le
    da apariencia y le agrega *aiuditas* (capacidades del catálogo), cada una con
    su propia config. El motor arma el ejecutor desde las aiuditas activas y lee
    su config en runtime; ya no hay un ejecutor por persona.
    """

    __tablename__ = "ayudantes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    # Apariencia por capas: {color, hair, eyes, mouth, hat, accessory, symbol}.
    appearance: Mapped[dict] = mapped_column(JSON, default=dict)
    # Instrucciones/persona que el dueño escribe (texto libre). Son el CARÁCTER y estilo
    # base del ayudante en el system prompt (arriba de las reglas), siempre subordinadas a
    # las reglas inquebrantables de fábrica: agregan estilo, nunca las contradicen.
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Aiuditas activas: { "<aiudita_id>": { <perilla_key>: valor, ... }, ... }.
    # La presencia de la llave = activa; su valor = la config validada de esa aiudita.
    aiuditas: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentFeedback(Base, TenantMixin, TimestampMixin):
    """Señal de aprendizaje: cómo el humano corrigió (o no) un borrador del agente.

    Es el foso del producto. Cada aprobación deja rastro: se envió tal cual, se editó (con
    qué cambios), o se rechazó. Las ediciones son correcciones del dueño — el agente las
    RE-INYECTA como ejemplos en su propio prompt y redacta cada vez más como él. La
    soberanía humana convertida en mejora, no solo en un veto."""

    __tablename__ = "agent_feedback"
    __table_args__ = (
        CheckConstraint(
            "decision in ('approved','edited','rejected')", name="ck_agent_feedback_decision"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    agent: Mapped[str] = mapped_column(String(24), default="mariana", index=True)
    bucket: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Referencias suaves (sin FK, como el resto del esquema) para ligar el desenlace luego.
    reminder_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # El borrador que escribió el agente y el texto que el humano realmente envió.
    draft_original: Mapped[str] = mapped_column(Text)
    final_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # None si rechazado
    decision: Mapped[str] = mapped_column(String(12))  # approved | edited | rejected
    # Desenlace, llenado por el sync más tarde: {paid_at, days_to_pay, ...}.
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)


class CuaMission(Base, TenantMixin, TimestampMixin):
    """Un 'recado' de CUA: un Computer Use Agent que fue a un portal (SAT, banca…) a
    buscar algo. El dueño configura la misión una vez (eligiendo CUA como fuente); esto
    guarda cada corrida como un trabajo con su estado, lo que extrajo, la bitácora de pasos
    y la evidencia (capturas). Es el 'log' que el dueño ve — nunca mira el navegador."""

    __tablename__ = "cua_missions"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued','running','done','failed')", name="ck_cua_mission_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    capacidad: Mapped[str] = mapped_column(String(48))
    sistema: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    resumen: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Datos extraídos por el agente (el JSON de la misión).
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Bitácora de pasos (qué hizo, en corto) y evidencia (capturas en base64, acotadas).
    steps: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
