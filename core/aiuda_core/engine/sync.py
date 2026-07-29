"""Sincronización de fuentes: los conectores alimentan y verifican la cartera.

Dos movimientos, siempre con procedencia:
1. sync_pedidos — pedidos por cobrar de la tienda (Shopify/WooCommerce) entran
   como facturas abiertas, con su origen marcado.
2. detectar_pagos — depósitos (Belvo) y cobros (Stripe) confirman facturas:
   la fuente real verifica, no el dicho.

Los clients son inyectables para tests; en producción se construyen solo si
hay credenciales configuradas.
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from aiuda_core.cfdi import parse_cfdi
from aiuda_core.config import settings
from aiuda_core.connectors import custom_api
from aiuda_core.connectors.credentials import ctor_kwargs, get_credential
from aiuda_core.folios import FOLIO_PROVISIONAL_PREFIX, es_provisional
from aiuda_core.engine.presence import (
    REGISTRY_SYSTEMS,
    add_presence,
    odoo_record_url,
    shopify_order_url,
)
from aiuda_core.models import (
    Appointment,
    CfdiBoveda,
    Customer,
    IntegrationCredential,
    Invoice,
    Payment,
    Product,
    PurchaseOrder,
    Tenant,
)
from aiuda_core.phones import normalize_mx

log = logging.getLogger("aiuda.sync")


@dataclass
class SyncReport:
    pedidos_importados: int = 0
    productos_importados: int = 0  # altas de catálogo (productos nuevos de una fuente)
    clientes_importados: int = 0  # altas de directorio (clientes nuevos de una fuente)
    citas_importadas: int = 0  # altas de agenda (citas nuevas de una fuente)
    ocs_importadas: int = 0  # altas de compras (órdenes de compra nuevas de una fuente)
    cfdis_importados: int = 0  # CFDI vinculados como respaldo fiscal de una factura
    correos_importados: int = 0  # correos de clientes que entraron a la bandeja (canal correo)
    pagos_confirmados: list[str] = field(default_factory=list)  # folios (legado)
    pagos_por_conciliar: int = 0  # pagos detectados que esperan que el humano concilie
    fuentes: list[str] = field(default_factory=list)
    # Fuentes que no respondieron o leyeron parcial: se dice, no se truena ni se inventa.
    avisos: list[str] = field(default_factory=list)


def _ensure_customer(session: Session, tenant_id: str, name: str, phone: str) -> Customer:
    customer = None
    if phone:
        customer = session.scalar(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone == phone)
        )
    if customer is None:
        customer = session.scalar(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.name == name)
        )
    if customer is None:
        customer = Customer(tenant_id=tenant_id, name=name or "Cliente", phone=phone or "")
        session.add(customer)
        session.flush()
    elif phone and not customer.phone:
        # La fuente ya trae teléfono y aiuda lo tenía vacío: se rellena (no se pisa uno
        # existente, para no romper un número ya bueno). Así un teléfono agregado en Odoo
        # después baja en el siguiente sync, no solo al crear el cliente.
        customer.phone = phone
    return customer


def _import_orders(
    session: Session,
    tenant: Tenant,
    orders,
    source: str,
    today: date,
    shopify_store_domain: str = "",
) -> int:
    """Pedidos impagos → facturas abiertas (idempotente por folio). El dominio de
    Shopify es per-tenant para que el deep-link no apunte a la tienda de otro."""
    created = 0
    for order in orders:
        folio = order.name
        exists = session.scalar(
            select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == folio)
        )
        url = (
            shopify_order_url(
                shopify_store_domain or settings.shopify_store_domain, str(order.id)
            )
            if source == "shopify" and getattr(order, "id", None)
            else None
        )
        if exists is not None:
            add_presence(exists, source, folio, url=url)  # upsert: tambien vive aqui
            continue
        customer = _ensure_customer(
            session, tenant.id, order.customer_name, order.customer_phone
        )
        issued = today
        session.add(
            Invoice(
                tenant_id=tenant.id,
                customer_id=customer.id,
                folio=folio,
                amount=order.total,
                currency=order.currency or "MXN",
                issued_date=issued,
                due_date=issued,  # pedido en línea: se cobra de inmediato
                source=source,
                verified="verificada",  # viene del sistema de registro de la tienda
                presence={source: {"ref": folio, **({"url": url} if url else {})}},
            )
        )
        created += 1
    session.flush()
    return created


def _fuente_permitida(
    fuente_prefs: dict[str, str] | None, capacidad: str, source: str
) -> bool:
    """¿El tenant permite leer `capacidad` desde `source`? True si no eligió otra fuente.

    `fuente_prefs` solo trae elecciones EXPLÍCITAS del dueño (una fuente distinta del
    default), resueltas en la capa de capacidades. Sin preferencia = se leen todas las
    fuentes conectadas (comportamiento por defecto: no privilegiar ninguna). Así, "de
    dónde lee" un ayudante deja de ser cosmético: si el dueño eligió Odoo para su cartera,
    las demás fuentes de esa capacidad no la pisan."""
    if not fuente_prefs:
        return True
    elegida = fuente_prefs.get(capacidad)
    return elegida is None or elegida == source


def _ml_build(session: Session, tenant: Tenant):
    """Construye el cliente de Mercado Libre desde las credenciales del tenant, o
    None si no hay. Fábrica compartida por los tres lectores (pedidos/catálogo/
    directorio) para no repetir el gate."""
    creds = get_credential(session, tenant.id, "mercadolibre")
    if creds and creds.get("access_token"):
        from aiuda_core.connectors.mercadolibre import MercadoLibreClient

        return MercadoLibreClient(**ctor_kwargs("mercadolibre", creds))
    return None


def _ml_persistir_token(session: Session, tenant: Tenant, client) -> None:
    """ML rota el refresh_token en cada refresco (uso único): si el cliente refrescó
    durante la corrida, se guarda el par nuevo cifrado para que la próxima corrida no
    use un refresh_token ya invalidado. Falla en silencio (aviso en log): un problema
    al guardar no debe tumbar el sync que ya leyó bien."""
    if not getattr(client, "token_refreshed", False):
        return
    try:
        from aiuda_core.connectors.credentials import set_credential

        prev = get_credential(session, tenant.id, "mercadolibre") or {}
        prev["access_token"] = client.access_token
        prev["refresh_token"] = client.refresh_token
        set_credential(session, tenant.id, "mercadolibre", prev)
        client.token_refreshed = False  # ya persistido: no re-guardar en otro lector
    except Exception as exc:  # noqa: BLE001 — cifrado/DB: se avisa, no se truena
        log.warning("Mercado Libre: no se pudo guardar el token refrescado: %s", exc)


def sync_pedidos(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    shopify_client=None,
    woocommerce_client=None,
    mercadolibre_client=None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    today = today or date.today()
    report = SyncReport()

    shopify_domain = ""
    if shopify_client is None:
        creds = get_credential(session, tenant.id, "shopify")
        if creds and creds.get("access_token"):
            from aiuda_core.connectors.shopify import ShopifyClient

            shopify_client = ShopifyClient(**ctor_kwargs("shopify", creds))
            shopify_domain = creds.get("store_domain") or ""
    if woocommerce_client is None:
        creds = get_credential(session, tenant.id, "woocommerce")
        if creds and creds.get("consumer_key"):
            from aiuda_core.connectors.woocommerce import WooCommerceClient

            woocommerce_client = WooCommerceClient(**ctor_kwargs("woocommerce", creds))
    if mercadolibre_client is None:
        mercadolibre_client = _ml_build(session, tenant)

    if shopify_client is not None and _fuente_permitida(fuente_prefs, "cuentas_por_cobrar", "shopify"):
        report.pedidos_importados += _import_orders(
            session, tenant, shopify_client.list_unpaid_orders(), "shopify", today,
            shopify_store_domain=shopify_domain,
        )
        report.fuentes.append("shopify")
    if woocommerce_client is not None and _fuente_permitida(fuente_prefs, "cuentas_por_cobrar", "woocommerce"):
        report.pedidos_importados += _import_orders(
            session, tenant, woocommerce_client.list_unpaid_orders(), "woocommerce", today
        )
        report.fuentes.append("woocommerce")
    if mercadolibre_client is not None and _fuente_permitida(fuente_prefs, "cuentas_por_cobrar", "mercadolibre"):
        report.pedidos_importados += _import_orders(
            session, tenant, mercadolibre_client.list_unpaid_orders(), "mercadolibre", today
        )
        report.fuentes.append("mercadolibre")
        _ml_persistir_token(session, tenant, mercadolibre_client)
    return report


def detectar_pagos(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    window_days: int = 30,
    belvo_client=None,
    belvo_link_id: str | None = None,
    stripe_client=None,
    pasarela_clients: dict | None = None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Cruza facturas abiertas contra depósitos/cobros reales y las confirma."""
    today = today or date.today()
    report = SyncReport()

    if belvo_client is None:
        creds = get_credential(session, tenant.id, "belvo")
        if creds and creds.get("secret_id"):
            from aiuda_core.connectors.belvo import BelvoClient

            belvo_client = BelvoClient(**ctor_kwargs("belvo", creds))
            belvo_link_id = belvo_link_id or creds.get("belvo_link_id")
    if stripe_client is None:
        creds = get_credential(session, tenant.id, "stripe")
        if creds and creds.get("api_key"):
            from aiuda_core.connectors.stripe_pagos import StripeClient

            stripe_client = StripeClient(**ctor_kwargs("stripe", creds))

    inflows = []
    if (
        belvo_client is not None
        and belvo_link_id
        and _fuente_permitida(fuente_prefs, "confirmacion_pago", "belvo")
    ):
        inflows = belvo_client.list_inflows(
            belvo_link_id, today - timedelta(days=window_days), today
        )
        report.fuentes.append("belvo")
    charges = []
    if stripe_client is not None and _fuente_permitida(fuente_prefs, "confirmacion_pago", "stripe"):
        charges = stripe_client.list_recent_charges()
        report.fuentes.append("stripe")

    # Pasarelas de cobro (Mercado Pago, Clip, Conekta): confirman el pago igual que Stripe.
    # Cada una expone list_recent_payments/match_payment con la misma forma. pasarela_clients
    # inyecta clientes fake en tests; en vivo se arman de la credencial cifrada del tenant.
    pasarela_clients = pasarela_clients or {}
    pasarelas: list[tuple[str, object, list]] = []
    for prov, modpath, clsname, gate in (
        ("mercadopago", "aiuda_core.connectors.mercadopago", "MercadoPagoClient", "access_token"),
        ("clip", "aiuda_core.connectors.clip", "ClipClient", "api_key"),
        ("conekta", "aiuda_core.connectors.conekta", "ConektaClient", "api_key"),
    ):
        client = pasarela_clients.get(prov)
        if client is None:
            creds = get_credential(session, tenant.id, prov)
            if creds and creds.get(gate):
                import importlib

                cls = getattr(importlib.import_module(modpath), clsname)
                client = cls(**ctor_kwargs(prov, creds))
        if client is not None and _fuente_permitida(fuente_prefs, "confirmacion_pago", prov):
            pagos = client.list_recent_payments()
            report.fuentes.append(prov)
            pasarelas.append((prov, client, pagos))

    open_invoices = session.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.status == "open")
    ).all()
    # Diego PROPONE, no cierra: cada pago detectado entra como pendiente de
    # conciliación. Un match de monto no es prueba de que sea ESA factura — eso lo
    # confirma el humano. (Soberanía humana: un depósito del mismo monto no cierra
    # una factura solo.)
    for invoice in open_invoices:
        amount = float(invoice.amount)
        source = None
        if belvo_client is not None and inflows and belvo_client.match_payment(inflows, amount):
            source = "banco"
        elif (
            stripe_client is not None
            and charges
            and stripe_client.match_payment(charges, amount)
        ):
            source = "stripe"
        else:
            for prov, client, pagos in pasarelas:
                if pagos and client.match_payment(pagos, amount):
                    source = prov
                    break
        if not source:
            continue
        # No dupliques en re-corridas: ya hay un pago vivo por ese monto+fuente
        # DENTRO de la ventana de detección. Acotarlo por fecha importa: el dedup
        # era por monto a secas y la renta mensual del mismo importe hacía que el
        # depósito del mes siguiente jamás entrara a conciliación (pagos que se
        # pierden). Dentro de la misma ventana el monto sigue deduplicando — las
        # fuentes no dan referencia estable a esta altura del cruce.
        existing = session.scalar(
            select(Payment).where(
                Payment.tenant_id == tenant.id,
                Payment.source == source,
                Payment.amount == invoice.amount,
                Payment.status != "ignorado",
                Payment.paid_at >= today - timedelta(days=window_days),
            )
        )
        if existing:
            continue
        session.add(
            Payment(
                tenant_id=tenant.id,
                amount=invoice.amount,
                currency=invoice.currency,
                paid_at=today,
                source=source,
                status="pendiente",
            )
        )
        report.pagos_por_conciliar += 1
    session.flush()
    return report


def sync_odoo(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    odoo_client=None,
    odoo_base_url: str = "",
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Facturas abiertas de Odoo: upsert con presencia y liga directa al registro."""
    today = today or date.today()
    report = SyncReport()
    if not _fuente_permitida(fuente_prefs, "cuentas_por_cobrar", "odoo"):
        return report  # el dueño eligió otra fuente para su cartera
    if odoo_client is None:
        creds = get_credential(session, tenant.id, "odoo")
        if creds and creds.get("url"):
            from aiuda_core.connectors.odoo import OdooConnector

            odoo_client = OdooConnector(**ctor_kwargs("odoo", creds))
            odoo_base_url = odoo_base_url or creds["url"]
    if odoo_client is None:
        return report

    report.fuentes.append("odoo")
    vistos: set[str] = set()  # folios que la cartera de Odoo SIGUE trayendo (para el cierre)
    for odoo_inv in odoo_client.fetch_open_invoices():
        vistos.add(odoo_inv.folio)
        url = odoo_record_url(odoo_base_url, getattr(odoo_inv, "move_id", 0))
        # Asegurar al cliente SIEMPRE (no solo al crear factura): así se rellena su teléfono
        # si en Odoo se agregó después, aunque la factura ya exista.
        customer = _ensure_customer(
            session, tenant.id, odoo_inv.customer_name, odoo_inv.customer_phone
        )
        # El cliente también vive en Odoo (su res.partner): marcarlo para que la ficha lo
        # muestre como ESPEJO de Odoo con liga a la fuente, no como registro nativo. La
        # cartera de Odoo (partner_id) es la que alimenta esto; sync_directorio solo cubre
        # a los res.partner con customer_rank>0, y muchos deudores no lo tienen.
        partner_id = getattr(odoo_inv, "partner_id", 0)
        if partner_id:
            add_presence(
                customer, "odoo", str(partner_id),
                url=odoo_record_url(odoo_base_url, partner_id, "res.partner"),
            )
        exists = session.scalar(
            select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == odoo_inv.folio)
        )
        if exists is not None:
            add_presence(exists, "odoo", odoo_inv.folio, url=url)
            # Refresca desde la fuente SOLO si Odoo es el maestro de esta factura
            # (source="odoo"); una factura que nació en Excel y también vive en Odoo no
            # se deja pisar por el espejo. Se refresca lo que Odoo manda en la cartera:
            # saldo vigente (amount_residual, que baja con cada abono hecho EN Odoo),
            # moneda y fechas. NO se tocan campos de aiuda (verified, payment_reported,
            # meta/abonos, cfdi, paid_*). Antes esto era insert-only: un abono parcial
            # hecho en Odoo quedaba invisible aquí (saldo viejo para siempre).
            if exists.source == "odoo":
                exists.amount = odoo_inv.amount
                exists.currency = odoo_inv.currency or "MXN"
                exists.issued_date = odoo_inv.issued_date
                exists.due_date = odoo_inv.due_date
            continue
        session.add(
            Invoice(
                tenant_id=tenant.id,
                customer_id=customer.id,
                folio=odoo_inv.folio,
                amount=odoo_inv.amount,
                currency=odoo_inv.currency or "MXN",
                issued_date=odoo_inv.issued_date,
                due_date=odoo_inv.due_date,
                source="odoo",
                verified="verificada",
                presence={"odoo": {"ref": odoo_inv.folio, **({"url": url} if url else {})}},
            )
        )
        report.pedidos_importados += 1
    session.flush()
    _cerrar_facturas_odoo_desaparecidas(session, tenant, odoo_client, vistos, today)
    return report


def _odoo_move_id(invoice: Invoice) -> int | None:
    """El move_id de Odoo de una factura interna, sin adivinar. Sale de la liga de
    presencia (`.../odoo/account.move/<id>`) o, si el folio es provisional
    (`borrador-<id>`, un borrador de Odoo sin número), del propio folio. None si no
    se puede resolver (p.ej. se guardó sin liga y con folio real): esa se deja como
    está en vez de arriesgar una lectura contra el id equivocado."""
    url = ((invoice.presence or {}).get("odoo") or {}).get("url") or ""
    m = re.search(r"/account\.move/(\d+)", url)
    if m:
        return int(m.group(1))
    if es_provisional(invoice.folio):
        try:
            return int(invoice.folio.removeprefix(FOLIO_PROVISIONAL_PREFIX))
        except ValueError:
            return None
    return None


def _cerrar_facturas_odoo_desaparecidas(
    session: Session, tenant: Tenant, odoo_client, vistos: set[str], today: date
) -> None:
    """Cierra honesto las facturas de Odoo que SALIERON de la cartera leída.

    Una factura interna source="odoo", status="open", con procedencia odoo, cuyo
    folio ya no vino en `fetch_open_invoices` (salió de amount_residual>0) o se pagó
    del todo o se canceló EN Odoo. No se adivina por la ausencia: se pregunta el
    estado real (`fetch_invoice_states`) y solo se cierra CON evidencia —
    payment_state paid/in_payment → pagada (paid_source="odoo"); state cancel →
    cancelada. Cualquier otro caso, un id irresoluble o un error de lectura la dejan
    intacta. NO se encola write-back: el pago ya ocurrió EN Odoo, reinyectarlo lo
    duplicaría. NO se crean Payments (eso es de detectar_pagos/conciliación) ni se
    tocan recordatorios (igual que hoy al marcar pagada una factura: cobranza ya no
    redacta sobre facturas cerradas y lo pendiente lo resuelve el humano)."""
    candidatas = session.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant.id,
            Invoice.source == "odoo",
            Invoice.status == "open",
        )
    ).all()
    por_move: dict[int, Invoice] = {}
    for inv in candidatas:
        if inv.folio in vistos:
            continue  # sigue viva en la cartera de Odoo: nada que cerrar
        if "odoo" not in (inv.presence or {}):
            continue  # sin procedencia odoo no hay a quién preguntar
        mid = _odoo_move_id(inv)
        if mid is not None:
            por_move[mid] = inv
    if not por_move:
        return
    try:
        estados = odoo_client.fetch_invoice_states(list(por_move))
    except Exception as exc:  # noqa: BLE001 — un error de lectura NO cierra nada (honesto)
        log.warning("Odoo: no se pudo leer el estado de facturas desaparecidas: %s", exc)
        return
    paid_at = datetime.combine(today, datetime.min.time())
    for mid, inv in por_move.items():
        estado = estados.get(mid)
        if not estado:
            continue  # Odoo ya no lo trajo (borrado/ilegible): se deja como está
        if estado.get("payment_state") in ("paid", "in_payment"):
            inv.status = "paid"
            inv.paid_source = "odoo"
            inv.paid_at = paid_at
            inv.payment_reported = False  # el dicho, si lo había, quedó confirmado por la fuente
        elif estado.get("state") == "cancel":
            inv.status = "cancelled"
        # cualquier otro estado (posted con saldo, borrador, etc.): se deja como está
    session.flush()


def _upsert_producto(
    session: Session,
    tenant_id: str,
    *,
    name: str,
    sku: str,
    price: float,
    stock: float,
    unit: str,
    source: str,
    ref: str,
    url: str | None = None,
    presence_key: str | None = None,
) -> bool:
    """Da de alta o actualiza un producto del catálogo desde una fuente. Dedup por
    SKU (si hay) o nombre. Refresca precio/existencia con los de la fuente y marca su
    presencia (la procedencia que el dueño ve). `presence_key` permite que la presencia
    lleve un nombre distinto de la columna `source` (las conexiones a la medida marcan
    el nombre que el dueño les puso). Devuelve True si fue alta."""
    pkey = presence_key or source
    existing = None
    if sku:
        existing = session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
        )
    if existing is None:
        existing = session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.name == name)
        )
    if existing is None:
        session.add(
            Product(
                tenant_id=tenant_id,
                name=name,
                sku=sku or None,
                price=price,
                stock=stock,
                unit=unit or None,
                source=source,
                presence={pkey: {"ref": ref, **({"url": url} if url else {})}},
            )
        )
        return True
    if price is not None:
        existing.price = price
    if stock is not None:
        existing.stock = stock
    if unit:
        existing.unit = unit
    add_presence(existing, pkey, ref, url=url)  # marca que también vive en `source`
    return False


def _upsert_cliente(
    session: Session,
    tenant_id: str,
    *,
    name: str,
    phone: str,
    email: str,
    source: str,
    ref: str,
    url: str | None = None,
    kind: str = "cliente",
    meta: dict | None = None,
) -> bool:
    """Da de alta o completa un cliente/prospecto del directorio desde una fuente. Dedup
    por teléfono (si hay) o nombre. RELLENA datos faltantes pero NO pisa lo que el dueño
    editó (aiuda no es el maestro del directorio; eso lo respeta el write-back) ni cambia
    el `kind` de un registro existente (un cliente no se degrada a prospecto). Marca su
    presencia. Devuelve True si fue alta."""
    existing = None
    if phone:
        existing = session.scalar(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone == phone)
        )
    if existing is None:
        existing = session.scalar(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.name == name)
        )
    if existing is None:
        session.add(
            Customer(
                tenant_id=tenant_id,
                name=name,
                phone=phone or None,
                email=email or None,
                kind=kind,
                meta=meta or {},
                presence={source: {"ref": ref, **({"url": url} if url else {})}},
            )
        )
        return True
    if email and not existing.email:
        existing.email = email
    if phone and not existing.phone:
        existing.phone = phone
    if meta:  # enriquece la bolsa sin pisar lo que ya estaba
        existing.meta = {**meta, **(existing.meta or {})}
    add_presence(existing, source, ref, url=url)
    return False


def sync_directorio(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    odoo_client=None,
    hubspot_client=None,
    shopify_client=None,
    mercadolibre_client=None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Directorio de clientes desde las fuentes conectadas que lo expongan. Hoy Odoo
    (res.partner), HubSpot (CRM contacts), Shopify (customers) y Mercado Libre
    (compradores recientes) —misma capacidad, varias fuentes, ninguna privilegiada;
    las demás entran igual cuando su conector liste contactos."""
    report = SyncReport()
    odoo_base_url = ""
    if odoo_client is None:
        creds = get_credential(session, tenant.id, "odoo")
        if creds and creds.get("url"):
            from aiuda_core.connectors.odoo import OdooConnector

            odoo_client = OdooConnector(**ctor_kwargs("odoo", creds))
            odoo_base_url = creds["url"]
    if hubspot_client is None:
        creds = get_credential(session, tenant.id, "hubspot")
        if creds and creds.get("token"):
            from aiuda_core.connectors.hubspot import HubSpotClient

            hubspot_client = HubSpotClient(**ctor_kwargs("hubspot", creds))
    if shopify_client is None:
        creds = get_credential(session, tenant.id, "shopify")
        if creds and creds.get("access_token"):
            from aiuda_core.connectors.shopify import ShopifyClient

            shopify_client = ShopifyClient(**ctor_kwargs("shopify", creds))
    if mercadolibre_client is None:
        mercadolibre_client = _ml_build(session, tenant)

    if odoo_client is not None and _fuente_permitida(fuente_prefs, "directorio_clientes", "odoo"):
        report.fuentes.append("odoo")
        for p in odoo_client.fetch_partners():
            if _upsert_cliente(
                session, tenant.id, name=p.name, phone=p.phone, email=p.email,
                source="odoo", ref=str(p.partner_id),
                url=odoo_record_url(odoo_base_url, p.partner_id, "res.partner"),
            ):
                report.clientes_importados += 1
        session.flush()
    if hubspot_client is not None and _fuente_permitida(fuente_prefs, "directorio_clientes", "hubspot"):
        report.fuentes.append("hubspot")
        for c in hubspot_client.list_contacts():
            if _upsert_cliente(
                session, tenant.id, name=c.nombre, phone=c.telefono, email=c.email,
                source="hubspot", ref=str(c.id),
            ):
                report.clientes_importados += 1
        session.flush()
    if shopify_client is not None and _fuente_permitida(fuente_prefs, "directorio_clientes", "shopify"):
        report.fuentes.append("shopify")
        for c in shopify_client.list_customers():
            if _upsert_cliente(
                session, tenant.id, name=c.name, phone=c.phone, email=c.email,
                source="shopify", ref=str(c.id),
            ):
                report.clientes_importados += 1
        session.flush()
    if mercadolibre_client is not None and _fuente_permitida(fuente_prefs, "directorio_clientes", "mercadolibre"):
        report.fuentes.append("mercadolibre")
        for c in mercadolibre_client.list_customers():
            if _upsert_cliente(
                session, tenant.id, name=c.name, phone=c.phone, email=c.email,
                source="mercadolibre", ref=str(c.id),
            ):
                report.clientes_importados += 1
        session.flush()
        _ml_persistir_token(session, tenant, mercadolibre_client)
    return report


def sync_prospeccion(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    hubspot_client=None,
    denue_client=None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Prospectos desde las fuentes que los listen. Hoy HubSpot (deals abiertos del
    pipeline = oportunidades que el equipo trabaja) y DENUE · INEGI (directorio público:
    empresas por giro y zona, el perfil de cliente ideal que el dueño define en
    `tenant.config["prospeccion"]["busquedas"]`). Misma capacidad, varias fuentes, ninguna
    privilegiada. El prospecto es un Customer kind='prospecto' con su origen/contexto en la
    meta (la bolsa flexible que usa Sofía)."""
    report = SyncReport()
    if hubspot_client is None:
        creds = get_credential(session, tenant.id, "hubspot")
        if creds and creds.get("token"):
            from aiuda_core.connectors.hubspot import HubSpotClient

            hubspot_client = HubSpotClient(**ctor_kwargs("hubspot", creds))
    busquedas = ((tenant.config or {}).get("prospeccion") or {}).get("busquedas") or []
    if denue_client is None and busquedas:
        creds = get_credential(session, tenant.id, "denue")
        if creds and creds.get("token"):
            from aiuda_core.connectors.denue import DenueClient

            denue_client = DenueClient(**ctor_kwargs("denue", creds))

    if hubspot_client is not None and _fuente_permitida(fuente_prefs, "prospeccion", "hubspot"):
        report.fuentes.append("hubspot")
        for o in hubspot_client.list_open_deals():
            if _upsert_cliente(
                session, tenant.id, name=o.nombre, phone="", email="",
                source="hubspot", ref=str(o.id), kind="prospecto",
                meta={"etapa": o.etapa, "monto": o.monto, "origen": "hubspot"},
            ):
                report.clientes_importados += 1
        session.flush()
    if (
        denue_client is not None
        and busquedas
        and _fuente_permitida(fuente_prefs, "prospeccion", "denue")
    ):
        report.fuentes.append("denue")
        for b in busquedas:
            for n in denue_client.buscar(
                b.get("condicion", ""), b.get("lat"), b.get("lng"), b.get("radio_m", 5000)
            ):
                if _upsert_cliente(
                    session, tenant.id, name=(n.nombre or n.razon_social or "Negocio"),
                    phone=n.telefono, email=n.correo, source="denue", ref=str(n.id),
                    kind="prospecto",
                    meta={"actividad": n.actividad, "direccion": n.direccion, "origen": "denue"},
                ):
                    report.clientes_importados += 1
        session.flush()
    return report


def _parse_wall(value: str) -> datetime | None:
    """Lee la fecha/hora de un evento como hora de pared (naive): lo que el negocio ve
    en su calendario es lo que aiuda muestra, sin reinterpretar zona horaria. Acepta
    'YYYY-MM-DD' (día completo) y 'YYYY-MM-DDTHH:MM:SS±zz' (descarta el offset)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def _upsert_cita(
    session: Session,
    tenant_id: str,
    *,
    title: str,
    starts_at: datetime | None,
    customer_name: str,
    notes: str,
    source: str,
    ref: str,
    url: str | None = None,
) -> bool:
    """Da de alta o completa una cita de la agenda desde una fuente. Dedup por
    (título, hora de inicio) para que re-sincronizar no duplique. RELLENA datos
    faltantes sin pisar y marca la procedencia en meta. Devuelve True si fue alta."""
    existing = session.scalar(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.title == title,
            Appointment.starts_at == starts_at,
        )
    )
    meta = {"ref": ref, **({"url": url} if url else {})}
    if existing is None:
        session.add(
            Appointment(
                tenant_id=tenant_id,
                title=title,
                starts_at=starts_at,
                customer_name=customer_name or None,
                notes=notes or None,
                source=source,
                meta=meta,
            )
        )
        return True
    if customer_name and not existing.customer_name:
        existing.customer_name = customer_name
    if notes and not existing.notes:
        existing.notes = notes
    existing.meta = {**(existing.meta or {}), **meta}  # procedencia, sin perder lo previo
    return False


def sync_agenda(
    session: Session, tenant: Tenant, today: date | None = None, gcal_client=None,
    fuente_prefs: dict[str, str] | None = None,  # mono-fuente: se acepta e ignora
) -> SyncReport:
    """Agenda (citas) desde las fuentes que la expongan. Hoy Google Calendar (eventos
    próximos, con o sin hora); las demás entran igual cuando su conector liste eventos
    —misma capacidad, ninguna fuente privilegiada."""
    report = SyncReport()
    if gcal_client is None:
        creds = get_credential(session, tenant.id, "googlecalendar")
        if creds and creds.get("token"):
            from aiuda_core.connectors.gcal import GoogleCalendarClient

            gcal_client = GoogleCalendarClient(**ctor_kwargs("googlecalendar", creds))
    if gcal_client is not None:
        report.fuentes.append("googlecalendar")
        for ev in gcal_client.list_events():
            if _upsert_cita(
                session, tenant.id, title=ev.summary, starts_at=_parse_wall(ev.start),
                customer_name="", notes="", source="googlecalendar",
                ref=str(ev.id), url=ev.html_link,
            ):
                report.citas_importadas += 1
        session.flush()
    return report


def _vincular_cfdi(
    session: Session,
    tenant_id: str,
    *,
    cfdi,
    source: str,
) -> bool:
    """Adjunta el respaldo fiscal (CFDI) a la factura del mismo folio: llena `cfdi` sin
    pisar lo que ya hubiera y marca la presencia del PAC (que eleva la verificación: un
    comprobante del SAT respalda la factura). No inventa cartera —si no hay factura con
    ese folio, lo ignora. Devuelve True solo cuando aporta respaldo nuevo a una factura."""
    if not cfdi.folio:
        return False
    inv = session.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.folio == cfdi.folio)
    )
    if inv is None:
        return False
    nuevo = not inv.cfdi
    if not inv.cfdi:  # no pisa un CFDI ya adjunto
        inv.cfdi = {
            "id": cfdi.id,
            "folio": cfdi.folio,
            "total": cfdi.total,
            "rfc_receptor": cfdi.rfc_receptor,
            "razon_receptor": cfdi.razon_receptor,
            "fecha": cfdi.fecha,
            "status": cfdi.status,
            "source": source,
        }
    add_presence(inv, source, cfdi.id)
    return nuevo


# --------------------------------------------------------------------------- #
# La bóveda fiscal del SAT: CFDIs de hasta 3 empresas (RFCs) del mismo negocio  #
# --------------------------------------------------------------------------- #

# Una PyME mexicana normal opera con más de una razón social (la persona física,
# la S.A., a veces una tercera). Para el SAT son contribuyentes separados; para
# el dueño son el mismo changarro. aiuda acepta hasta TRES.
SAT_MAX_EMPRESAS = 3
SAT_EFIRMA_PREFIX = "sat_efirma:"  # una credencial POR RFC: sat_efirma:<RFC>

# El CFDI no trae plazo de pago. Para un ingreso a crédito (PPD) se usa el plazo
# que el dueño eligió para ese RFC; 30 días es el default, siempre marcado como
# estimado. El valor vive en tenant.config para no exigir migración.
SAT_PLAZO_DEFAULT = 30


def sat_plazo_dias(tenant: Tenant, rfc: str) -> int:
    """Plazo estimado de un RFC, acotado aunque la config se haya editado a mano."""
    raw = ((tenant.config or {}).get("sat_plazos") or {}).get((rfc or "").upper())
    try:
        return max(1, min(365, int(raw or SAT_PLAZO_DEFAULT)))
    except (TypeError, ValueError):
        return SAT_PLAZO_DEFAULT


def sat_empresas(session: Session, tenant: Tenant) -> list[dict]:
    """Las empresas (RFCs) del negocio: las que tienen e.firma conectada (fila
    cifrada ``sat_efirma:<RFC>``) más las declaradas a mano en
    ``tenant.config['sat_empresas']`` (para clasificar XML subidos sin e.firma).
    Máximo ``SAT_MAX_EMPRESAS``; el tope se valida al agregar, no aquí."""
    out: list[dict] = []
    vistos: set[str] = set()
    rows = session.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider.like(f"{SAT_EFIRMA_PREFIX}%"),
            IntegrationCredential.status != "disabled",
        )
    ).all()
    for row in rows:
        rfc = row.provider.removeprefix(SAT_EFIRMA_PREFIX)
        pub = row.public_config or {}
        out.append(
            {
                "rfc": rfc,
                "nombre": pub.get("titular") or "",
                "efirma": True,
                "vigente_hasta": pub.get("vigente_hasta"),
                "plazo_dias": sat_plazo_dias(tenant, rfc),
            }
        )
        vistos.add(rfc)
    for emp in (tenant.config or {}).get("sat_empresas") or []:
        rfc = (emp.get("rfc") or "").upper()
        if rfc and rfc not in vistos:
            out.append(
                {"rfc": rfc, "nombre": emp.get("nombre") or "", "efirma": False,
                 "vigente_hasta": None, "plazo_dias": sat_plazo_dias(tenant, rfc)}
            )
            vistos.add(rfc)
    return out


def _sat_folio(d: dict) -> str:
    """El folio de cartera de un CFDI: serie-folio si trae, si no el UUID corto.
    Sirve además para EMPATAR con una factura que ya vive en aiuda (Odoo/Excel)."""
    serie, folio = d.get("serie") or "", d.get("folio") or ""
    if serie and folio:
        return f"{serie}-{folio}"
    return folio or serie or f"CFDI-{(d.get('uuid') or '')[:8]}"


def _sat_fecha(d: dict) -> date | None:
    return _parse_date((d.get("fecha") or "")[:10])


def _sat_cfdi_dict(d: dict, source: str) -> dict:
    """Lo que la ficha de la factura muestra del comprobante (Invoice.cfdi)."""
    return {
        "id": d.get("uuid"),
        "uuid": d.get("uuid"),
        "folio": _sat_folio(d),
        "total": d.get("total"),
        "rfc_emisor": (d.get("emisor") or {}).get("rfc"),
        "rfc_receptor": (d.get("receptor") or {}).get("rfc"),
        "razon_receptor": (d.get("receptor") or {}).get("nombre"),
        "fecha": d.get("fecha"),
        "tipo": d.get("tipo"),
        "metodo_pago": d.get("metodo_pago"),
        "status": "vigente",
        "source": source,
    }


def _sat_direccion(d: dict, empresas: set[str]) -> str:
    """De qué lado quedó el negocio en este CFDI, contra SUS empresas (RFCs).
    Si el emisor y el receptor son empresas suyas es dinero moviéndose dentro de
    la misma casa (intercompania): se guarda en la bóveda pero NO es cartera."""
    emisor = ((d.get("emisor") or {}).get("rfc") or "").upper()
    receptor = ((d.get("receptor") or {}).get("rfc") or "").upper()
    es_emisor, es_receptor = emisor in empresas, receptor in empresas
    if es_emisor and es_receptor:
        return "intercompania"
    if es_emisor:
        return "emitida"
    if es_receptor:
        return "recibida"
    return "desconocida"


def _sat_aplicar_pago(session: Session, tenant: Tenant, d: dict, res: dict) -> None:
    """Un complemento de pago (tipo P) emitido por una de tus empresas NO es una
    cuenta por cobrar nueva: es la constancia fiscal de que TE PAGARON. Se aplica
    a la factura relacionada: saldo insoluto 0 la cierra (paid_source='sat');
    saldo mayor la deja abierta con el saldo vigente (mismo criterio que el
    amount_residual de Odoo)."""
    for docto in d.get("pagos") or []:
        rel = session.scalar(
            select(CfdiBoveda).where(
                CfdiBoveda.tenant_id == tenant.id,
                CfdiBoveda.uuid == docto["id_documento"],
            )
        )
        if rel is None or not rel.invoice_id:
            continue  # el ingreso relacionado no está en la bóveda o no es cartera
        inv = session.get(Invoice, rel.invoice_id)
        if inv is None or inv.status != "open":
            continue
        saldo = docto.get("imp_saldo_insoluto")
        if saldo is None:
            continue  # sin saldo declarado no se adivina
        abonos = list((inv.meta or {}).get("abonos") or [])
        abonos.append(
            {
                "fecha": (d.get("fecha") or "")[:10],
                "monto": docto.get("imp_pagado"),
                "uuid_pago": d.get("uuid"),
            }
        )
        inv.meta = {**(inv.meta or {}), "abonos": abonos}
        if saldo <= 0.005:
            inv.status = "paid"
            inv.paid_source = "sat"
            fecha = _sat_fecha(d)
            inv.paid_at = datetime.combine(fecha, datetime.min.time()) if fecha else None
            inv.payment_reported = False
        else:
            inv.amount = Decimal(str(saldo))
        res["pagos_aplicados"] += 1


def _sat_aplicar_egreso(session: Session, tenant: Tenant, d: dict, res: dict) -> None:
    """Un egreso (nota de crédito, tipo E) emitido por una de tus empresas RESTA
    de la factura que relaciona. Si la deja en cero, esa cuenta ya no se cobra
    (cancelled con la nota en meta). Sin relación resoluble no se toca nada."""
    total = d.get("total")
    if not total:
        return
    for rel_ref in d.get("relacionados") or []:
        rel = session.scalar(
            select(CfdiBoveda).where(
                CfdiBoveda.tenant_id == tenant.id, CfdiBoveda.uuid == rel_ref["uuid"]
            )
        )
        if rel is None or not rel.invoice_id:
            continue
        inv = session.get(Invoice, rel.invoice_id)
        if inv is None or inv.status != "open":
            continue
        restante = Decimal(str(inv.amount)) - Decimal(str(total))
        notas = list((inv.meta or {}).get("notas_credito") or [])
        notas.append({"uuid": d.get("uuid"), "monto": total, "fecha": (d.get("fecha") or "")[:10]})
        if restante <= Decimal("0.005"):
            inv.amount = Decimal("0")
            inv.status = "cancelled"
            inv.meta = {**(inv.meta or {}), "notas_credito": notas,
                        "cerrada_por": "nota de crédito"}
        else:
            inv.amount = restante
            inv.meta = {**(inv.meta or {}), "notas_credito": notas}
        res["egresos_aplicados"] += 1
        return  # una nota resta una vez, contra la primera factura resoluble


def _sat_crear_cartera(
    session: Session, tenant: Tenant, d: dict, xml_texto: str, today: date, res: dict,
    crear: bool = True,
) -> str | None:
    """Un ingreso (I) EMITIDO por una de tus empresas entra a la cartera:
    PPD (a crédito) crea la cuenta por cobrar; PUE (cobrado al emitir) solo se
    guarda en la bóveda —meterlo abierto inflaría la cartera y rompería el
    producto. Si ya existe una factura con ese folio (vino de Odoo/Excel), se le
    adjunta el comprobante en vez de duplicarla. Devuelve el invoice_id ligado."""
    folio = _sat_folio(d)
    exists = session.scalar(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == folio)
    )
    if exists is not None:
        if not exists.cfdi:
            exists.cfdi = _sat_cfdi_dict(d, "sat")
        if not exists.cfdi_xml:
            exists.cfdi_xml = xml_texto
        if not (exists.meta or {}).get("empresa_rfc"):
            exists.meta = {**(exists.meta or {}),
                           "empresa_rfc": (d.get("emisor") or {}).get("rfc")}
        add_presence(exists, "sat", d.get("uuid") or folio)
        res["facturas_vinculadas"] += 1
        return exists.id
    if d.get("metodo_pago") != "PPD":
        res["pue_en_boveda"] += 1  # cobrado al emitir: bóveda sí, cartera no
        return None
    if not crear:
        return None  # el dueño eligió otra fuente para su cartera: no se pisa
    receptor = d.get("receptor") or {}
    customer = _ensure_customer(session, tenant.id, receptor.get("nombre") or "Cliente", "")
    emitida = _sat_fecha(d) or today
    empresa_rfc = (d.get("emisor") or {}).get("rfc") or ""
    plazo_dias = sat_plazo_dias(tenant, empresa_rfc)
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio=folio,
        amount=Decimal(str(d.get("total") or 0)),
        currency=d.get("moneda") or "MXN",
        issued_date=emitida,
        due_date=emitida + timedelta(days=plazo_dias),
        source="sat",
        verified="verificada",  # respaldada por el comprobante timbrado del SAT
        presence={"sat": {"ref": d.get("uuid") or folio}},
        cfdi=_sat_cfdi_dict(d, "sat"),
        cfdi_xml=xml_texto,
        meta={
            "empresa_rfc": empresa_rfc,
            "rfc_receptor": receptor.get("rfc"),
            # Honesto: el CFDI no trae plazo; se asume el típico y se dice.
            "vencimiento_estimado": f"{plazo_dias} días (el CFDI no trae plazo)",
        },
    )
    session.add(inv)
    session.flush()
    res["facturas_creadas"] += 1
    return inv.id


def _sat_reclasificar(session: Session, row: CfdiBoveda, direccion: str, res: dict) -> None:
    """Un CFDI que ya estaba en la bóveda puede cambiar de clasificación cuando el
    dueño agrega otra de sus empresas: lo que parecía una venta normal resulta ser
    entre sus propias razones sociales. Se marca intercompania y, si había creado
    cartera, esa cuenta se cierra (era dinero de la misma casa, no cobranza)."""
    if direccion == "intercompania" and row.direccion != "intercompania":
        row.direccion = "intercompania"
        if row.invoice_id:
            inv = session.get(Invoice, row.invoice_id)
            if inv is not None and inv.status == "open":
                inv.status = "cancelled"
                inv.meta = {**(inv.meta or {}),
                            "cerrada_por": "intercompañía (factura entre tus empresas)"}
        res["intercompania"] += 1
    elif row.direccion == "desconocida" and direccion != "desconocida":
        row.direccion = direccion  # ahora sí sabemos de qué empresa es


def importar_cfdis(
    session: Session,
    tenant: Tenant,
    xmls: list[bytes | str],
    today: date | None = None,
    source: str = "importado",
    crear_cartera: bool = True,
) -> dict:
    """Mete CFDIs a la bóveda fiscal y CREA la cartera desde los emitidos, con
    procedencia sat. Reglas de producto (si se inflan las cuentas por cobrar, se
    rompió el producto):

    - Dedupe por UUID: re-subir o re-descargar el mismo comprobante no duplica.
    - Solo un ingreso (I) EMITIDO por una empresa del negocio y a crédito (PPD)
      es cuenta por cobrar. PUE se cobró al emitir: bóveda sí, cartera no.
    - Un complemento de pago (P) no es cartera nueva: abona o cierra la factura.
    - Un egreso (E) resta de la factura que relaciona.
    - Nómina (N) y traslado (T) son respaldo fiscal, nunca cartera.
    - Entre empresas del MISMO negocio (intercompania) nada cuenta como cobranza.
    - Recibidos: bóveda (gasto/compra del negocio), no cartera.

    ``crear_cartera=False`` respeta al dueño que eligió OTRA fuente para sus
    cuentas por cobrar: la bóveda y los ajustes (P/E) siguen; facturas nuevas no.
    """
    today = today or date.today()
    empresas = {e["rfc"].upper() for e in sat_empresas(session, tenant)}
    res: dict = {
        "cfdis": 0, "nuevos": 0, "duplicados": 0,
        "facturas_creadas": 0, "facturas_vinculadas": 0, "pue_en_boveda": 0,
        "pagos_aplicados": 0, "egresos_aplicados": 0,
        "intercompania": 0, "recibidas": 0, "sin_clasificar": 0,
        "avisos": [],
    }
    parsed: list[tuple[dict, str]] = []
    for xml in xmls:
        try:
            d = parse_cfdi(xml)
        except ValueError as exc:
            res["avisos"].append(f"Un archivo no es un CFDI válido: {exc}")
            continue
        if not d.get("uuid"):
            res["avisos"].append("Un CFDI viene sin timbre (UUID): no se puede identificar.")
            continue
        texto = xml.decode("utf-8", errors="replace") if isinstance(xml, bytes) else xml
        parsed.append((d, texto))

    # Primero los ingresos (crean cartera), luego egresos y pagos (la ajustan):
    # así un lote con la factura y su complemento se aplica bien venga como venga.
    orden = {"I": 0, "N": 1, "T": 1, "E": 2, "P": 3}
    parsed.sort(key=lambda par: orden.get(par[0].get("tipo") or "", 1))

    for d, texto in parsed:
        res["cfdis"] += 1
        direccion = _sat_direccion(d, empresas)
        row = session.scalar(
            select(CfdiBoveda).where(
                CfdiBoveda.tenant_id == tenant.id, CfdiBoveda.uuid == d["uuid"]
            )
        )
        if row is not None:
            res["duplicados"] += 1
            _sat_reclasificar(session, row, direccion, res)
            continue
        emisor, receptor = d.get("emisor") or {}, d.get("receptor") or {}
        row = CfdiBoveda(
            tenant_id=tenant.id,
            uuid=d["uuid"],
            tipo=d.get("tipo") or "I",
            metodo_pago=d.get("metodo_pago"),
            folio=_sat_folio(d),
            fecha=d.get("fecha"),
            rfc_emisor=(emisor.get("rfc") or "").upper() or None,
            nombre_emisor=emisor.get("nombre"),
            rfc_receptor=(receptor.get("rfc") or "").upper() or None,
            nombre_receptor=receptor.get("nombre"),
            total=Decimal(str(d["total"])) if d.get("total") is not None else None,
            moneda=d.get("moneda") or "MXN",
            direccion=direccion,
            source=source,
            xml=texto,
        )
        session.add(row)
        res["nuevos"] += 1
        if direccion == "intercompania":
            res["intercompania"] += 1
        elif direccion == "recibida":
            res["recibidas"] += 1
        elif direccion == "desconocida":
            res["sin_clasificar"] += 1
        if direccion == "emitida":
            tipo = d.get("tipo")
            if tipo == "I":
                row.invoice_id = _sat_crear_cartera(
                    session, tenant, d, texto, today, res, crear=crear_cartera
                )
            elif tipo == "E":
                _sat_aplicar_egreso(session, tenant, d, res)
            elif tipo == "P":
                _sat_aplicar_pago(session, tenant, d, res)
        session.flush()
    if not empresas and res["sin_clasificar"]:
        res["avisos"].append(
            "No sé cuál RFC es del negocio: agrega tus empresas (hasta "
            f"{SAT_MAX_EMPRESAS}) o conecta tu e.firma para clasificar los CFDI "
            "y armar tu cartera."
        )
    session.flush()
    return res


# --- La Descarga Masiva del SAT: el ciclo por empresa, con estado persistido --- #

# Primera conexión: se piden los últimos 90 días (cubre hasta la cartera crítica,
# que son más de 45 días de atraso). De ahí en adelante es incremental.
_SAT_VENTANA_INICIAL_DIAS = 90
# Incremental: desde la última fecha sincronizada MENOS 2 días. El SAT tarda en
# dejar consultables los CFDI recién timbrados; el traslape no duplica (dedupe
# por UUID) y sí evita hoyos.
_SAT_TRASLAPE_DIAS = 2


def _sat_build_clients(session: Session, tenant: Tenant) -> dict:
    """Un cliente de Descarga Masiva por empresa con e.firma. La credencial se
    descifra AQUÍ y solo vive en la memoria de esta corrida: sin caché, sin
    archivos, sin logs de parámetros. Una e.firma que no abre no tumba a las
    demás: se avisa por empresa en el ciclo."""
    from aiuda_core.connectors.sat_descarga import SatDescargaClient

    out: dict = {}
    for e in sat_empresas(session, tenant):
        if not e["efirma"]:
            continue
        try:
            creds = get_credential(session, tenant.id, f"{SAT_EFIRMA_PREFIX}{e['rfc']}")
            if not creds or not creds.get("key"):
                continue
            out[e["rfc"]] = SatDescargaClient(
                base64.b64decode(creds["cer"]),
                base64.b64decode(creds["key"]),
                creds["password"],
            )
        except Exception as exc:  # noqa: BLE001 — una empresa rota no apaga el resto
            out[e["rfc"]] = exc  # el ciclo lo reporta como aviso, con su RFC
    return out


def _sat_ciclo_scope(
    session: Session,
    tenant: Tenant,
    rfc: str,
    client,
    scope: str,
    st: dict,
    today: date,
    report: SyncReport,
    crear_cartera: bool,
) -> None:
    """Una vuelta del ciclo para (empresa, emitidas|recibidas). El web service es
    asíncrono: se SOLICITA un periodo, el SAT lo prepara y en una corrida
    siguiente se VERIFICA y DESCARGA. La solicitud pendiente se PERSISTE
    (tenant.config) y se verifica por su id: jamás se re-pide un periodo a
    ciegas — el código 5002 agota las solicitudes DE POR VIDA para esos
    parámetros exactos, y quemarlas por no guardar estado rompe la fuente."""
    from aiuda_core.connectors.sat_descarga import extraer_xmls

    sol = st.get("solicitud")
    if sol:
        v = client.verificar(sol["id"])
        estado = int(v.get("EstadoSolicitud") or 0)
        codigo = str(v.get("CodigoEstadoSolicitud") or v.get("CodEstatus") or "")
        if estado in (1, 2):  # aceptada / en proceso: el SAT sigue preparando
            report.avisos.append(
                f"SAT {rfc} ({scope}): el SAT sigue preparando los CFDI; "
                "se descargan en una corrida siguiente."
            )
            return
        if estado == 3:  # terminada: descargar los paquetes e importar
            xmls: list[bytes] = []
            for paquete in v.get("IdsPaquetes") or []:
                xmls.extend(extraer_xmls(client.descargar(paquete)))
            res = importar_cfdis(
                session, tenant, xmls, today=today, source="sat",
                crear_cartera=crear_cartera,
            )
            report.cfdis_importados += res["nuevos"]
            report.pedidos_importados += res["facturas_creadas"]
            report.avisos.extend(res["avisos"])
            st["ultima_fecha"] = sol["hasta"][:10]
            st.pop("solicitud", None)
            return
        if estado == 5 and codigo == "5002":
            # Agotada DE POR VIDA para ese periodo exacto: se registra para no
            # volver a pedirlo jamás. La última fecha NO avanza (esos CFDI no
            # llegaron); la siguiente corrida pide con fecha final nueva, que
            # para el SAT son parámetros distintos.
            agotadas = st.setdefault("agotadas", [])
            periodo = f"{sol['desde']}|{sol['hasta']}"
            if periodo not in agotadas:
                agotadas.append(periodo)
            st.pop("solicitud", None)
            report.avisos.append(
                f"SAT {rfc} ({scope}): el SAT agotó las solicitudes para ese "
                "periodo exacto (código 5002). No se vuelve a pedir igual; la "
                "próxima corrida pide con fechas nuevas."
            )
            return
        if estado == 5 and codigo == "5004":
            # No encontró información: periodo sin CFDIs. No es error.
            st["ultima_fecha"] = sol["hasta"][:10]
            st.pop("solicitud", None)
            return
        # 4 error, 5 con otro código, 6 vencida, o una respuesta rara: se suelta
        # la solicitud y la siguiente corrida pide de nuevo (con fechas nuevas).
        st.pop("solicitud", None)
        report.avisos.append(
            f"SAT {rfc} ({scope}): la solicitud terminó en estado {estado}"
            f"{f' (código {codigo})' if codigo else ''}; se pide de nuevo en la "
            "próxima corrida."
        )
        return

    # Sin solicitud pendiente: pedir el periodo incremental.
    ultima = _parse_date(st.get("ultima_fecha") or "")
    desde = (
        ultima - timedelta(days=_SAT_TRASLAPE_DIAS)
        if ultima
        else today - timedelta(days=_SAT_VENTANA_INICIAL_DIAS)
    )
    inicio = datetime.combine(desde, datetime.min.time())
    fin = datetime.combine(today, datetime.max.time().replace(microsecond=0))
    periodo = f"{inicio.isoformat()}|{fin.isoformat()}"
    if periodo in (st.get("agotadas") or []):
        return  # ese periodo exacto ya se agotó (5002): jamás re-pedirlo
    r = client.solicitar(scope, inicio, fin)
    id_solicitud = r.get("IdSolicitud")
    if not id_solicitud:
        detalle = r.get("Mensaje") or r.get("CodEstatus") or "sin respuesta"
        report.avisos.append(
            f"SAT {rfc} ({scope}): el SAT no aceptó la solicitud: {detalle}."
        )
        return
    st["solicitud"] = {
        "id": id_solicitud,
        "desde": inicio.isoformat(),
        "hasta": fin.isoformat(),
    }
    report.avisos.append(
        f"SAT {rfc} ({scope}): solicitud enviada; el SAT prepara los CFDI y se "
        "descargan en una corrida siguiente."
    )


def _sync_sat(
    session: Session,
    tenant: Tenant,
    clients: dict,
    today: date,
    report: SyncReport,
    crear_cartera: bool,
) -> None:
    """El ciclo completo para todas las empresas conectadas. Aislado por RFC:
    que una empresa falle (red, e.firma vencida, SAT caído) no tumba a las otras
    dos. El estado por empresa vive en tenant.config['sat_descarga'][rfc]."""
    cfg = dict(tenant.config or {})
    estado = {k: dict(v) for k, v in (cfg.get("sat_descarga") or {}).items()}
    for rfc, client in clients.items():
        st_rfc = {
            scope: dict((estado.get(rfc) or {}).get(scope) or {})
            for scope in ("emitidas", "recibidas")
        }
        if isinstance(client, Exception):  # la e.firma no abrió al construir
            report.avisos.append(f"SAT {rfc}: no se pudo usar la e.firma: {client}")
            continue
        for scope in ("emitidas", "recibidas"):
            try:
                _sat_ciclo_scope(
                    session, tenant, rfc, client, scope, st_rfc[scope], today,
                    report, crear_cartera,
                )
            except Exception as exc:  # noqa: BLE001 — se avisa y se sigue con lo demás
                log.warning("SAT %s (%s): %s", rfc, scope, exc)
                report.avisos.append(f"SAT {rfc} ({scope}): no se pudo: {exc}")
        estado[rfc] = st_rfc
    cfg["sat_descarga"] = estado
    tenant.config = cfg
    flag_modified(tenant, "config")
    session.flush()


def sync_cfdi(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    facturama_client=None,
    facturapi_client=None,
    fuente_prefs: dict[str, str] | None = None,
    sat_clients: dict | None = None,
) -> SyncReport:
    """Respaldo fiscal (CFDI) desde las fuentes conectadas que lo listen: el SAT
    directo (Descarga Masiva con la e.firma, hasta 3 empresas), Facturama (cfdi
    issuedLite) y Facturapi (invoices); misma capacidad, ninguna privilegiada.
    Solo lectura —el timbrado queda para después. El SAT además CREA cartera con
    los ingresos emitidos a crédito (importar_cfdis); los PAC vinculan cada CFDI
    a la factura de su folio para dar procedencia y verificación."""
    report = SyncReport()
    if facturama_client is None:
        creds = get_credential(session, tenant.id, "facturama")
        if creds and creds.get("user"):
            from aiuda_core.connectors.facturama import FacturamaClient

            facturama_client = FacturamaClient(**ctor_kwargs("facturama", creds))
    if facturapi_client is None:
        creds = get_credential(session, tenant.id, "facturapi")
        if creds and creds.get("api_key"):
            from aiuda_core.connectors.facturapi import FacturapiClient

            facturapi_client = FacturapiClient(**ctor_kwargs("facturapi", creds))

    if facturama_client is not None and _fuente_permitida(fuente_prefs, "cfdi", "facturama"):
        report.fuentes.append("facturama")
        for c in facturama_client.list_cfdis():
            if _vincular_cfdi(session, tenant.id, cfdi=c, source="facturama"):
                report.cfdis_importados += 1
        session.flush()
    if facturapi_client is not None and _fuente_permitida(fuente_prefs, "cfdi", "facturapi"):
        report.fuentes.append("facturapi")
        for c in facturapi_client.list_invoices():
            if _vincular_cfdi(session, tenant.id, cfdi=c, source="facturapi"):
                report.cfdis_importados += 1
        session.flush()
    # El SAT directo (Descarga Masiva con la e.firma). `sat_clients` inyecta fakes
    # en tests: {rfc: cliente}; en vivo se construye por empresa desde la
    # credencial cifrada, descifrada SOLO en memoria de esta corrida.
    if _fuente_permitida(fuente_prefs, "cfdi", "sat"):
        if sat_clients is None:
            sat_clients = _sat_build_clients(session, tenant)
        if sat_clients:
            report.fuentes.append("sat")
            _sync_sat(
                session, tenant, sat_clients, today or date.today(), report,
                crear_cartera=_fuente_permitida(
                    fuente_prefs, "cuentas_por_cobrar", "sat"
                ),
            )
    return report


def sync_catalogo(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    odoo_client=None,
    shopify_client=None,
    woocommerce_client=None,
    mercadolibre_client=None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Lee el catálogo (productos/precios) de las fuentes conectadas que saben
    listarlo y lo upserta con su procedencia. Hoy implementan Odoo (product.template),
    Shopify (products), WooCommerce (products) y Mercado Libre (publicaciones); las
    demás entran por aquí cuando su conector exponga productos —mismo patrón, ninguna
    fuente privilegiada."""
    report = SyncReport()
    if odoo_client is None:
        creds = get_credential(session, tenant.id, "odoo")
        if creds and creds.get("url"):
            from aiuda_core.connectors.odoo import OdooConnector

            odoo_client = OdooConnector(**ctor_kwargs("odoo", creds))
    if shopify_client is None:
        creds = get_credential(session, tenant.id, "shopify")
        if creds and creds.get("access_token"):
            from aiuda_core.connectors.shopify import ShopifyClient

            shopify_client = ShopifyClient(**ctor_kwargs("shopify", creds))
    if woocommerce_client is None:
        creds = get_credential(session, tenant.id, "woocommerce")
        if creds and creds.get("consumer_key"):
            from aiuda_core.connectors.woocommerce import WooCommerceClient

            woocommerce_client = WooCommerceClient(**ctor_kwargs("woocommerce", creds))
    if mercadolibre_client is None:
        mercadolibre_client = _ml_build(session, tenant)

    if odoo_client is not None and _fuente_permitida(fuente_prefs, "catalogo_productos", "odoo"):
        report.fuentes.append("odoo")
        for p in odoo_client.fetch_products():
            if _upsert_producto(
                session, tenant.id, name=p.name, sku=p.sku, price=p.price,
                stock=p.stock, unit=p.unit, source="odoo", ref=(p.sku or p.name),
            ):
                report.productos_importados += 1
        session.flush()
    if shopify_client is not None and _fuente_permitida(fuente_prefs, "catalogo_productos", "shopify"):
        report.fuentes.append("shopify")
        for p in shopify_client.list_products():
            if _upsert_producto(
                session, tenant.id, name=p.name, sku=p.sku, price=p.price,
                stock=p.stock, unit="", source="shopify", ref=(p.sku or str(p.id)),
            ):
                report.productos_importados += 1
        session.flush()
    if woocommerce_client is not None and _fuente_permitida(fuente_prefs, "catalogo_productos", "woocommerce"):
        report.fuentes.append("woocommerce")
        for p in woocommerce_client.list_products():
            if _upsert_producto(
                session, tenant.id, name=p.name, sku=p.sku, price=p.price,
                stock=p.stock, unit="", source="woocommerce", ref=(p.sku or str(p.id)),
            ):
                report.productos_importados += 1
        session.flush()
    if mercadolibre_client is not None and _fuente_permitida(fuente_prefs, "catalogo_productos", "mercadolibre"):
        report.fuentes.append("mercadolibre")
        for p in mercadolibre_client.list_products():
            if _upsert_producto(
                session, tenant.id, name=p.name, sku=p.sku, price=p.price,
                stock=p.stock, unit="", source="mercadolibre", ref=(p.sku or str(p.id)),
            ):
                report.productos_importados += 1
        session.flush()
        _ml_persistir_token(session, tenant, mercadolibre_client)
    return report


def _parse_date(value: str) -> date | None:
    """Fecha (sin hora) tolerante: acepta 'YYYY-MM-DD' o el prefijo de un ISO más largo."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _upsert_oc(session: Session, tenant_id: str, *, oc, source: str) -> bool:
    """Da de alta o actualiza una orden de compra desde una fuente. Dedup por folio.
    Refresca total/estado (p.ej. de 'sin confirmar' a confirmada) y marca presencia.
    Devuelve True si fue alta."""
    if not oc.folio:
        return False
    existing = session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.folio == oc.folio
        )
    )
    if existing is None:
        session.add(
            PurchaseOrder(
                tenant_id=tenant_id, folio=oc.folio, supplier=(oc.supplier or None),
                total=oc.total, currency=(oc.currency or "MXN"), status=oc.status,
                ordered_at=_parse_date(oc.ordered_at), source=source,
                presence={source: {"ref": oc.folio}},
            )
        )
        return True
    existing.total = oc.total
    existing.status = oc.status  # el estado en la fuente manda (confirmada o no)
    add_presence(existing, source, oc.folio)
    return False


def sync_compras(
    session: Session, tenant: Tenant, today: date | None = None, odoo_client=None,
    fuente_prefs: dict[str, str] | None = None,  # mono-fuente: se acepta e ignora
) -> SyncReport:
    """Órdenes de compra desde las fuentes que las expongan. Hoy Odoo (purchase.order);
    las demás entran igual cuando su conector liste OCs —misma capacidad, ninguna
    privilegiada. Roberto las vigila para detectar proveedores que no han confirmado."""
    report = SyncReport()
    if odoo_client is None:
        creds = get_credential(session, tenant.id, "odoo")
        if creds and creds.get("url"):
            from aiuda_core.connectors.odoo import OdooConnector

            odoo_client = OdooConnector(**ctor_kwargs("odoo", creds))
    if odoo_client is not None:
        report.fuentes.append("odoo")
        for oc in odoo_client.fetch_purchase_orders():
            if _upsert_oc(session, tenant.id, oc=oc, source="odoo"):
                report.ocs_importadas += 1
        session.flush()
    return report


# --------------------------------------------------------------------------- #
# Conexiones a la medida: la fuente REST que el dueño declaró entra al motor    #
# --------------------------------------------------------------------------- #

# La columna `source` de las entidades (String(16)); la presencia lleva el nombre real.
_CUSTOM_SOURCE = "custom"
_SIN_INGESTA = "Esta necesidad aún no se ingesta automáticamente."


def _texto(value) -> str:
    """Campo mapeado → texto plano ('' si no vino). El mapeo puede traer números."""
    return str(value).strip() if value is not None else ""


def _to_decimal(value) -> Decimal | None:
    """Monto tolerante → Decimal: acepta 1234.5, '1,234.50' o '$ 1234.50'.
    None si no hay número (no se inventa un cero)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _to_date(value) -> date | None:
    """Fecha tolerante → date: ISO ('2026-07-15' o prefijo de un ISO largo) o DD/MM/YYYY."""
    s = _texto(value)
    parsed = _parse_date(s)
    if parsed is not None:
        return parsed
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def _custom_secret(src: dict) -> tuple[str, str | None]:
    """Descifra la clave de una conexión a la medida (secret_ct/secret_ver en config).
    Sin clave guardada = '' (APIs públicas). Si no se puede descifrar (p.ej. rotación
    que retiró la versión), error legible: la corrida no truena ni manda basura."""
    ct = src.get("secret_ct") or ""
    if not ct:
        return "", None
    try:
        from aiuda_core.security import crypto

        return crypto.decrypt(base64.b64decode(ct), int(src.get("secret_ver") or 1)), None
    except Exception:  # noqa: BLE001 — cualquier fallo de descifrado es un aviso, no un crash
        return "", "No se pudo descifrar la clave guardada. Vuelve a capturarla en la conexión."


def _custom_presence_key(src: dict) -> str:
    """La llave de presencia = el nombre que el dueño le puso a SU conexión, para que el
    badge diga 'Mi ERP' y no 'custom'. Si chocara con un sistema de registro real (odoo,
    shopify…) se le añade sufijo: una API arbitraria no hereda la verificación de esos."""
    name = (src.get("name") or "").strip() or "a la medida"
    if name.lower() in REGISTRY_SYSTEMS:
        name = f"{name} (a la medida)"
    return name


def _ref_index(session: Session, model, tenant_id: str, pkey: str) -> dict:
    """external_id → registro, leyendo el ref de presencia de ESTA conexión. Es el
    dedupe primario de la ingesta a la medida; las llaves naturales (teléfono/nombre,
    folio, SKU) quedan de fallback para registros que aún no traen la marca."""
    idx: dict[str, object] = {}
    for rec in session.scalars(select(model).where(model.tenant_id == tenant_id)):
        ref = ((rec.presence or {}).get(pkey) or {}).get("ref")
        if ref:
            idx[str(ref)] = rec
    return idx


def _custom_directorio(
    session: Session, tenant: Tenant, rows: list[dict], pkey: str, today: date,
    report: SyncReport, kind: str = "cliente",
) -> None:
    idx = _ref_index(session, Customer, tenant.id, pkey)
    for row in rows:
        name = _texto(row.get("name"))
        if not name:
            continue  # un registro sin nombre no sirve (misma regla que el builder)
        phone = normalize_mx(_texto(row.get("phone")))
        email = _texto(row.get("email"))
        ext = _texto(row.get("external_id"))
        existing = idx.get(ext) if ext else None
        if existing is not None:
            # Ya lo trajimos de esta conexión: rellena sin pisar (aiuda no es el maestro).
            if email and not existing.email:
                existing.email = email
            if phone and not existing.phone:
                existing.phone = phone
            add_presence(existing, pkey, ext)
            continue
        meta = {"origen": pkey} if kind == "prospecto" else None
        if _upsert_cliente(
            session, tenant.id, name=name, phone=phone, email=email,
            source=pkey, ref=ext or phone or name, kind=kind, meta=meta,
        ):
            report.clientes_importados += 1
    session.flush()


def _custom_prospeccion(session, tenant, rows, pkey, today, report) -> None:
    _custom_directorio(session, tenant, rows, pkey, today, report, kind="prospecto")


def _custom_cartera(
    session: Session, tenant: Tenant, rows: list[dict], pkey: str, today: date,
    report: SyncReport,
) -> None:
    """Facturas por cobrar desde la API del dueño. Dedupe por folio (la llave natural de
    la cartera); sin folio se usa el external_id. Montos → Decimal, fechas → date,
    teléfono → normalize_mx. Una fila sin folio o sin monto se omite (no se inventa)."""
    for row in rows:
        folio = _texto(row.get("folio")) or _texto(row.get("external_id"))
        amount = _to_decimal(row.get("amount"))
        if not folio or amount is None:
            continue
        ext = _texto(row.get("external_id")) or folio
        exists = session.scalar(
            select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.folio == folio)
        )
        if exists is not None:
            add_presence(exists, pkey, ext)  # upsert: también vive en la fuente del dueño
            continue
        customer = _ensure_customer(
            session, tenant.id,
            _texto(row.get("customer")) or "Cliente",
            normalize_mx(_texto(row.get("phone"))),
        )
        due = _to_date(row.get("due_date")) or today
        session.add(
            Invoice(
                tenant_id=tenant.id,
                customer_id=customer.id,
                folio=folio,
                amount=amount,
                currency="MXN",
                issued_date=min(today, due),
                due_date=due,
                source=_CUSTOM_SOURCE,
                presence={pkey: {"ref": ext}},
            )
        )
        report.pedidos_importados += 1
    session.flush()


def _custom_catalogo(
    session: Session, tenant: Tenant, rows: list[dict], pkey: str, today: date,
    report: SyncReport,
) -> None:
    idx = _ref_index(session, Product, tenant.id, pkey)
    for row in rows:
        name = _texto(row.get("name"))
        if not name:
            continue
        sku = _texto(row.get("sku"))
        price = _to_decimal(row.get("price"))
        stock = _to_decimal(row.get("stock"))
        ext = _texto(row.get("external_id"))
        existing = idx.get(ext) if ext else None
        if existing is not None:
            if price is not None:
                existing.price = price
            if stock is not None:
                existing.stock = stock
            add_presence(existing, pkey, ext)
            continue
        if _upsert_producto(
            session, tenant.id, name=name, sku=sku, price=price, stock=stock, unit="",
            source=_CUSTOM_SOURCE, ref=ext or sku or name, presence_key=pkey,
        ):
            report.productos_importados += 1
    session.flush()


def _custom_agenda(
    session: Session, tenant: Tenant, rows: list[dict], pkey: str, today: date,
    report: SyncReport,
) -> None:
    for row in rows:
        title = _texto(row.get("title"))
        if not title:
            continue
        if _upsert_cita(
            session, tenant.id, title=title,
            starts_at=_parse_wall(_texto(row.get("starts_at"))),
            customer_name=_texto(row.get("customer")), notes="",
            source=_CUSTOM_SOURCE, ref=_texto(row.get("external_id")) or title,
        ):
            report.citas_importadas += 1
    session.flush()


# Qué necesidad (cap) ingesta a qué entidad. Una cap fuera de este mapa (p.ej.
# expedientes) aún no tiene entidad destino: se registra el porqué, no se simula.
_CUSTOM_READERS = {
    "directorio_clientes": _custom_directorio,
    "prospeccion": _custom_prospeccion,
    "cuentas_por_cobrar": _custom_cartera,
    "catalogo_productos": _custom_catalogo,
    "agenda": _custom_agenda,
}


def sync_custom(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Conexiones a la medida (tenant.config['custom_sources']): por cada conexión
    guardada hace el GET con su receta (auth, paginación, reintentos), mapea y upserta
    entidades con su procedencia. Dedupe por external_id (el ref de presencia) con
    fallback a las llaves naturales. No-op HONESTO si la fuente no responde: el error
    queda en la conexión (last_error) y en el reporte (avisos); no truena, no inventa.
    El resultado de cada corrida (last_sync_at / last_count) también se guarda para
    que la lista de conexiones diga la verdad."""
    today = today or date.today()
    report = SyncReport()
    sources = list((tenant.config or {}).get("custom_sources") or [])
    if not sources:
        return report
    changed = False
    for src in sources:
        cap = src.get("cap") or ""
        reader = _CUSTOM_READERS.get(cap)
        if reader is None:
            if src.get("last_error") != _SIN_INGESTA:
                src["last_error"] = _SIN_INGESTA
                changed = True
            continue
        if not _fuente_permitida(fuente_prefs, cap, f"custom:{src.get('id')}"):
            continue  # el dueño eligió otra fuente para esta capacidad: no la pisamos
        secret, err = _custom_secret(src)
        rows: list[dict] = []
        if err is None:
            rows, err = custom_api.fetch_rows(**custom_api.kwargs_from_source(src, secret))
        src["last_sync_at"] = datetime.now().isoformat(timespec="seconds")
        src["last_error"] = err or ""
        src["last_count"] = len(rows)
        changed = True
        if err:
            report.avisos.append(f"{src.get('name') or 'Conexión a la medida'}: {err}")
            if not rows:
                continue  # nada llegó: no-op (una lectura parcial sí ingesta lo leído)
        reader(session, tenant, rows, _custom_presence_key(src), today, report)
        report.fuentes.append(src.get("name") or "a la medida")
    if changed:
        # Columna JSON: reasignar + flag_modified para que el estado persista.
        tenant.config = {**(tenant.config or {}), "custom_sources": sources}
        flag_modified(tenant, "config")
    session.flush()
    return report


# Tipo declarado en la hoja de Google -> (capacidad, lector custom que la ingiere).
# Reusa los MISMOS lectores que las conexiones a la medida (fuente mapeada a entidad),
# sin duplicar la ingesta: la hoja produce filas ya mapeadas y aquí solo se enrutan.
_SHEETS_TIPO: dict[str, tuple[str, object]] = {
    "facturas": ("cuentas_por_cobrar", _custom_cartera),
    "clientes": ("directorio_clientes", _custom_directorio),
    "productos": ("catalogo_productos", _custom_catalogo),
}


def sync_google_sheets(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    google_sheets_client=None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Google Sheets: una hoja compartida como fuente de solo lectura. Lee el rango
    declarado, mapea los encabezados a los campos de aiuda (en el conector) y los
    ingesta por el lector custom del `tipo` (facturas/clientes/productos). No-op
    HONESTO si no hay credencial, si el tipo no está declarado o si la hoja no
    responde (el error va a `avisos`, no truena)."""
    today = today or date.today()
    report = SyncReport()
    # El rango/tipo son operativos del credential (no del ctor): se resuelven SIEMPRE,
    # también cuando el cliente se inyecta en tests.
    creds = get_credential(session, tenant.id, "google_sheets") or {}
    spreadsheet_id = creds.get("spreadsheet_id") or ""
    sheet_range = creds.get("sheet_range") or ""
    tipo = creds.get("tipo") or ""
    if google_sheets_client is None:
        if creds.get("api_key") and spreadsheet_id:
            from aiuda_core.connectors.google_sheets import GoogleSheetsClient

            google_sheets_client = GoogleSheetsClient(**ctor_kwargs("google_sheets", creds))
    if google_sheets_client is None:
        return report
    entry = _SHEETS_TIPO.get(tipo)
    if entry is None:
        return report  # tipo no declarado/soportado: no-op honesto (nada que ingerir)
    cap, reader = entry
    if not _fuente_permitida(fuente_prefs, cap, "google_sheets"):
        return report  # el dueño eligió otra fuente para esta capacidad
    rows, err = google_sheets_client.fetch_rows(spreadsheet_id, sheet_range, tipo)
    if err:
        report.avisos.append(f"Google Sheets: {err}")
        if not rows:
            return report  # nada llegó: no-op (una lectura parcial sí ingesta lo leído)
    report.fuentes.append("google_sheets")
    reader(session, tenant, rows, "google_sheets", today, report)
    session.flush()
    return report


def _merge(into: SyncReport, other: SyncReport) -> SyncReport:
    """Acumula un reporte de fuente en el total."""
    into.pedidos_importados += other.pedidos_importados
    into.productos_importados += other.productos_importados
    into.clientes_importados += other.clientes_importados
    into.citas_importadas += other.citas_importadas
    into.ocs_importadas += other.ocs_importadas
    into.cfdis_importados += other.cfdis_importados
    into.correos_importados += other.correos_importados
    into.pagos_confirmados.extend(other.pagos_confirmados)
    into.pagos_por_conciliar += other.pagos_por_conciliar
    into.avisos.extend(other.avisos)
    for f in other.fuentes:
        if f not in into.fuentes:
            into.fuentes.append(f)
    return into


def sync_fuentes(
    session: Session,
    tenant: Tenant,
    today: date | None = None,
    fuente_prefs: dict[str, str] | None = None,
) -> SyncReport:
    """Lee las fuentes conectadas del tenant, respetando "de dónde lee" cada capacidad.

    Cada lector jala los datos de su(s) fuente(s) si están conectadas y es no-op si
    no. Agregar una fuente = sumar su lector aquí; el mismo camino las corre a todas
    (antes una lista fija dejaba conectores huérfanos, p.ej. Odoo nunca se leía).
    El orden importa: primero el directorio y la prospección (clientes/prospectos que
    referencian las facturas), luego la cartera, el catálogo, la agenda y las compras
    (pedidos de tienda, Odoo, calendario, OCs…), después las conexiones a la medida
    del dueño (que pueden traer cualquiera de esas entidades), el CFDI que respalda
    esas facturas, y al final los pagos que concilian la cartera.

    `fuente_prefs` (capacidad -> fuente) lo resuelve la capa de capacidades desde la
    elección EXPLÍCITA del dueño en sus ayudantes; sin él, se leen todas (comportamiento
    previo). Los lectores mono-fuente (agenda, compras) no lo necesitan."""
    # Import perezoso: el lector de correo vive en su propio módulo (engine/correo.py)
    # y este módulo no debe cargarlo salvo al correr (evita el ciclo con SyncReport).
    from aiuda_core.engine.correo import sync_correo

    report = SyncReport()
    for reader in (
        sync_directorio, sync_prospeccion, sync_pedidos, sync_odoo,
        sync_catalogo, sync_agenda, sync_compras, sync_custom, sync_google_sheets,
        sync_cfdi, detectar_pagos,
        sync_correo,  # el buzón del negocio → hilos con clientes en la bandeja
    ):
        _merge(report, reader(session, tenant, today=today, fuente_prefs=fuente_prefs))
    # Fallback CUA: capacidades que el dueño enrutó explícitamente a un Computer Use Agent
    # (no hay conector API). El gate de arriba ya apagó las fuentes API de esa capacidad.
    if fuente_prefs:
        from aiuda_core.cua.fallback import CUA_FUENTE, CUA_TEMPLATES, sync_cua

        for cap, fuente in fuente_prefs.items():
            if fuente == CUA_FUENTE and cap in CUA_TEMPLATES:
                _merge(report, sync_cua(session, tenant, cap, today=today))
    return report
