"""Presencia multi-sistema y upsert entre fuentes."""

from pathlib import Path

from aiuda_core.connectors.csv_import import import_invoices
from aiuda_core.engine.presence import add_presence, odoo_record_url, shopify_order_url
from aiuda_core.engine.sync import sync_odoo
from aiuda_core.connectors.odoo import OdooInvoice

DATA = Path(__file__).parent / "data" / "facturas_demo.csv"


def test_add_presence_eleva_verificacion(session, tenant, customer, invoice):
    assert invoice.verified == "sin_verificar"
    add_presence(invoice, "odoo", "F-001", url="https://erp.mx/odoo/account.move/7")
    assert invoice.presence["odoo"]["url"].endswith("/7")
    assert invoice.verified == "verificada"  # un sistema de registro la respalda

    add_presence(invoice, "excel", "F-001")
    assert set(invoice.presence) == {"odoo", "excel"}


def test_reimport_hace_upsert_de_presencia(session, tenant):
    import_invoices(session, tenant.id, DATA)
    result = import_invoices(session, tenant.id, DATA)  # re-importa el mismo Excel
    assert result.created == 0 and result.skipped == 5


class FakeOdoo:
    def fetch_open_invoices(self):
        from datetime import date

        return [
            OdooInvoice(
                move_id=7,
                folio="F-001",  # ya existe (fixture, source excel)
                customer_name="Cliente Demo",
                customer_phone="5215587654321",
                amount=12500.50,
                currency="MXN",
                issued_date=date(2026, 5, 1),
                due_date=date(2026, 5, 31),
            )
        ]


def test_sync_odoo_upsert_con_liga_directa(session, tenant, customer, invoice):
    report = sync_odoo(
        session, tenant, odoo_client=FakeOdoo(), odoo_base_url="https://erp.negocio.mx"
    )
    assert report.fuentes == ["odoo"]
    assert report.pedidos_importados == 0  # ya existia: upsert, no duplicado
    session.refresh(invoice)
    assert invoice.presence["odoo"]["url"] == "https://erp.negocio.mx/odoo/account.move/7"
    assert invoice.verified == "verificada"


# ---------- sync_odoo: refresco de existentes y cierre de desaparecidas ----------

from datetime import date  # noqa: E402

from sqlalchemy import select  # noqa: E402

from aiuda_core.models import Invoice, OutboxEntry  # noqa: E402

BASE_URL = "https://erp.negocio.mx"


class FakeOdooEstado:
    """Sirve una cartera abierta y un mapa move_id -> estado (para el cierre).

    `fetch_invoice_states` responde SOLO los ids con estado conocido (como Odoo, que
    omite los borrados) y registra cada llamada para asegurar qué se preguntó."""

    def __init__(self, abiertas, estados=None):
        self._abiertas = list(abiertas)
        self._estados = dict(estados or {})
        self.states_calls: list[list[int]] = []

    def fetch_open_invoices(self):
        return list(self._abiertas)

    def fetch_invoice_states(self, move_ids):
        self.states_calls.append(list(move_ids))
        return {m: self._estados[m] for m in move_ids if m in self._estados}


def _inv_odoo(session, tenant, customer, folio, move_id, amount=100.0, status="open"):
    """Factura interna que nació en Odoo (source='odoo'), con su liga de presencia."""
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio=folio,
        amount=amount,
        currency="MXN",
        issued_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        source="odoo",
        status=status,
        verified="verificada",
        presence={"odoo": {"ref": folio, "url": f"{BASE_URL}/odoo/account.move/{move_id}"}},
    )
    session.add(inv)
    session.flush()
    return inv


def _abierta(move_id, folio, amount):
    return OdooInvoice(
        move_id=move_id, folio=folio, customer_name="Cliente Demo",
        customer_phone="5215587654321", amount=amount, currency="MXN",
        issued_date=date(2026, 6, 5), due_date=date(2026, 7, 5),
    )


def test_sync_odoo_refresca_residual_de_existente(session, tenant, customer):
    """Un abono hecho EN Odoo baja el residual: el sync lo refleja (amount = residual
    vigente) y actualiza moneda/fechas. Antes era insert-only y quedaba el saldo viejo."""
    inv = _inv_odoo(session, tenant, customer, "INV/100", move_id=50, amount=100.0)
    fake = FakeOdooEstado(abiertas=[_abierta(50, "INV/100", 40.0)])

    report = sync_odoo(session, tenant, odoo_client=fake, odoo_base_url=BASE_URL)

    assert report.pedidos_importados == 0  # ya existia
    session.refresh(inv)
    assert float(inv.amount) == 40.0  # residual refrescado
    assert inv.due_date == date(2026, 7, 5)
    assert inv.status == "open"
    assert fake.states_calls == []  # sigue en cartera: no se pregunta estado


def test_sync_odoo_no_refresca_factura_de_otra_fuente(session, tenant, customer):
    """Una factura que nació en Excel y TAMBIÉN vive en Odoo no se deja pisar por el
    espejo: Excel es su maestro. Solo se marca la presencia."""
    inv = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio="INV/100", amount=100.0,
        currency="MXN", issued_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
        source="excel",
    )
    session.add(inv)
    session.flush()
    fake = FakeOdooEstado(abiertas=[_abierta(50, "INV/100", 40.0)])

    sync_odoo(session, tenant, odoo_client=fake, odoo_base_url=BASE_URL)

    session.refresh(inv)
    assert float(inv.amount) == 100.0  # NO pisado por Odoo
    assert set(inv.presence) == {"odoo"}  # pero sí marca que vive allá


def test_sync_odoo_cierra_pagada_desaparecida(session, tenant, customer):
    """Factura que salió de la cartera (residual 0 en Odoo): se pregunta su estado y,
    con evidencia (payment_state paid), se cierra como pagada con paid_source='odoo'.
    NO se encola write-back (el pago ya ocurrió en Odoo) ni se crean Payments."""
    inv = _inv_odoo(session, tenant, customer, "INV/200", move_id=60)
    fake = FakeOdooEstado(
        abiertas=[],
        estados={60: {"id": 60, "name": "INV/200", "state": "posted",
                      "payment_state": "paid", "amount_residual": 0.0}},
    )

    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake,
              odoo_base_url=BASE_URL)

    session.refresh(inv)
    assert inv.status == "paid"
    assert inv.paid_source == "odoo"
    assert inv.paid_at.date() == date(2026, 7, 11)
    assert fake.states_calls == [[60]]
    # Sin write-back (el pago vive en Odoo) y sin Payments desde el sync.
    assert session.scalar(select(OutboxEntry).where(OutboxEntry.tenant_id == tenant.id)) is None


def test_sync_odoo_cierra_in_payment(session, tenant, customer):
    """payment_state='in_payment' (asentado, aún no compensado) también cierra: para
    la cobranza ya está pagada."""
    inv = _inv_odoo(session, tenant, customer, "INV/210", move_id=61)
    fake = FakeOdooEstado(
        abiertas=[],
        estados={61: {"id": 61, "state": "posted", "payment_state": "in_payment",
                      "amount_residual": 0.0}},
    )
    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake, odoo_base_url=BASE_URL)
    session.refresh(inv)
    assert inv.status == "paid" and inv.paid_source == "odoo"


def test_sync_odoo_cierra_cancelada_desaparecida(session, tenant, customer):
    """Cancelada EN Odoo (state='cancel'): se marca cancelled, sin paid_source."""
    inv = _inv_odoo(session, tenant, customer, "INV/300", move_id=70)
    fake = FakeOdooEstado(
        abiertas=[],
        estados={70: {"id": 70, "name": False, "state": "cancel",
                      "payment_state": "not_paid", "amount_residual": 500.0}},
    )

    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake, odoo_base_url=BASE_URL)

    session.refresh(inv)
    assert inv.status == "cancelled"
    assert inv.paid_source is None


def test_sync_odoo_caso_ambiguo_se_queda_igual(session, tenant, customer):
    """Salió de la cartera pero su estado NO es concluyente (sigue posted con saldo
    parcial, o Odoo ya no la trajo): honesto, se deja como está —no se adivina."""
    parcial = _inv_odoo(session, tenant, customer, "INV/400", move_id=80, amount=90.0)
    fantasma = _inv_odoo(session, tenant, customer, "INV/401", move_id=81, amount=50.0)
    fake = FakeOdooEstado(
        abiertas=[],
        # 80 vuelve parcial (no concluyente); 81 no lo trae Odoo (borrado/ilegible).
        estados={80: {"id": 80, "state": "posted", "payment_state": "partial",
                      "amount_residual": 45.0}},
    )

    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake, odoo_base_url=BASE_URL)

    session.refresh(parcial)
    session.refresh(fantasma)
    assert parcial.status == "open"  # parcial sin cierre: se queda
    assert fantasma.status == "open"  # sin estado: se queda
    assert sorted(fake.states_calls[0]) == [80, 81]


def test_sync_odoo_cierre_es_idempotente(session, tenant, customer):
    """Cerrar una pagada no se repite: en la 2a corrida ya no es 'open', no entra a
    candidatas y ni se pregunta su estado."""
    inv = _inv_odoo(session, tenant, customer, "INV/500", move_id=90)
    estados = {90: {"id": 90, "state": "posted", "payment_state": "paid", "amount_residual": 0.0}}

    fake1 = FakeOdooEstado(abiertas=[], estados=estados)
    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake1, odoo_base_url=BASE_URL)
    session.refresh(inv)
    assert inv.status == "paid" and fake1.states_calls == [[90]]

    fake2 = FakeOdooEstado(abiertas=[], estados=estados)
    sync_odoo(session, tenant, today=date(2026, 7, 12), odoo_client=fake2, odoo_base_url=BASE_URL)
    session.refresh(inv)
    assert inv.status == "paid"
    assert fake2.states_calls == []  # ya cerrada: no se re-pregunta


def test_sync_odoo_sin_liga_resoluble_no_cierra(session, tenant, customer):
    """Factura source='odoo' con folio REAL y sin liga en presencia: no hay move_id
    que resolver sin adivinar, así que ni se pregunta y se deja como está."""
    inv = Invoice(
        tenant_id=tenant.id, customer_id=customer.id, folio="INV/600", amount=100.0,
        currency="MXN", issued_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
        source="odoo", status="open", presence={"odoo": {"ref": "INV/600"}},  # sin url
    )
    session.add(inv)
    session.flush()
    fake = FakeOdooEstado(abiertas=[], estados={})

    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake, odoo_base_url=BASE_URL)

    session.refresh(inv)
    assert inv.status == "open"
    assert fake.states_calls == []  # nada resoluble: no se pregunta


def test_sync_odoo_error_de_lectura_no_cierra_nada(session, tenant, customer):
    """Si la lectura del estado truena (Odoo caído), NO se cierra nada: se deja como
    está y el error queda en el log, la corrida no revienta."""
    inv = _inv_odoo(session, tenant, customer, "INV/700", move_id=95)

    class FakeExplota(FakeOdooEstado):
        def fetch_invoice_states(self, move_ids):
            raise TimeoutError("odoo no responde")

    fake = FakeExplota(abiertas=[])
    sync_odoo(session, tenant, today=date(2026, 7, 11), odoo_client=fake, odoo_base_url=BASE_URL)

    session.refresh(inv)
    assert inv.status == "open"  # error de lectura: intacta


def test_urls_de_salto():
    assert odoo_record_url("https://erp.mx/", 12).endswith("/odoo/account.move/12")
    assert odoo_record_url("", 12) is None
    assert shopify_order_url("tienda.myshopify.com", "99").endswith("/admin/orders/99")


class FakeOdooCatalogo:
    def fetch_products(self):
        from aiuda_core.connectors.odoo import OdooProduct

        return [
            OdooProduct(product_id=1, name="Anillo oro 14k", sku="AN-14", price=1200, stock=8, unit="Unidad"),
            OdooProduct(product_id=2, name="Pulsera plata", sku="PL-22", price=600, stock=3, unit="Unidad"),
        ]


def test_sync_catalogo_alta_y_upsert_desde_fuente(session, tenant):
    from aiuda_core.engine.sync import sync_catalogo
    from aiuda_core.models import Product
    from sqlalchemy import select

    # un producto ya existe por SKU (vino de Excel): debe hacerse upsert, no duplicar
    session.add(Product(tenant_id=tenant.id, name="Anillo oro 14k", sku="AN-14",
                        price=1000, stock=5, source="excel", presence={"excel": {"ref": "AN-14"}}))
    session.flush()

    report = sync_catalogo(session, tenant, odoo_client=FakeOdooCatalogo())
    assert report.fuentes == ["odoo"]
    assert report.productos_importados == 1  # solo "Pulsera plata" es alta

    anillo = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.sku == "AN-14"))
    assert float(anillo.price) == 1200  # precio refrescado desde Odoo
    assert set(anillo.presence) == {"excel", "odoo"}  # ahora vive en ambas (procedencia)
    pulsera = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.sku == "PL-22"))
    assert pulsera is not None and pulsera.source == "odoo"


class FakeOdooDirectorio:
    def fetch_partners(self):
        from aiuda_core.connectors.odoo import OdooPartner

        return [
            OdooPartner(partner_id=10, name="Cliente Demo", phone="5215587654321", email="demo@cliente.mx"),
            OdooPartner(partner_id=11, name="Joyería Aurora", phone="5215511112222", email=""),
        ]


def test_sync_directorio_alta_y_rellena_sin_pisar(session, tenant, customer):
    from aiuda_core.engine.sync import sync_directorio
    from aiuda_core.models import Customer
    from sqlalchemy import select

    # `customer` (fixture) ya existe con ese teléfono pero sin email -> se rellena
    customer.email = None
    session.flush()

    report = sync_directorio(session, tenant, odoo_client=FakeOdooDirectorio())
    assert report.fuentes == ["odoo"]
    assert report.clientes_importados == 1  # solo "Joyería Aurora" es alta

    demo = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == "5215587654321"))
    assert demo.email == "demo@cliente.mx"  # rellenó el faltante
    assert "odoo" in demo.presence  # procedencia marcada
    nueva = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Joyería Aurora"))
    assert nueva is not None and nueva.presence["odoo"]["ref"] == "11"


class FakeShopifyCatalogo:
    def list_products(self):
        from aiuda_core.connectors.shopify import ProductoTienda

        return [
            ProductoTienda(id=501, name="Playera logo", sku="PL-LOGO", price=350, stock=40),
            ProductoTienda(id=502, name="Taza marca", sku="", price=180, stock=12),
        ]


def test_sync_catalogo_lee_de_shopify_tambien(session, tenant):
    from aiuda_core.engine.sync import sync_catalogo
    from aiuda_core.models import Product
    from sqlalchemy import select

    report = sync_catalogo(session, tenant, shopify_client=FakeShopifyCatalogo())
    assert report.fuentes == ["shopify"]
    assert report.productos_importados == 2
    playera = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.sku == "PL-LOGO"))
    assert playera.source == "shopify" and float(playera.price) == 350
    # producto sin SKU: dedup por nombre, presencia con ref del id
    taza = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.name == "Taza marca"))
    assert taza is not None and taza.presence["shopify"]["ref"] == "502"


def test_fuente_permitida_gatea_solo_con_eleccion_explicita():
    from aiuda_core.engine.sync import _fuente_permitida

    assert _fuente_permitida(None, "catalogo_productos", "odoo") is True  # sin prefs: lee todo
    assert _fuente_permitida({}, "catalogo_productos", "odoo") is True
    prefs = {"catalogo_productos": "odoo"}
    assert _fuente_permitida(prefs, "catalogo_productos", "odoo") is True
    assert _fuente_permitida(prefs, "catalogo_productos", "shopify") is False  # suprimida
    assert _fuente_permitida(prefs, "cfdi", "facturama") is True  # otra capacidad: sin gate


def test_de_donde_lee_respeta_la_fuente_elegida(session, tenant):
    """'De dónde lee' deja de ser cosmético: con Odoo y Shopify conectados para el
    catálogo, si el dueño eligió Odoo, el ingest NO trae los productos de Shopify."""
    from aiuda_core.engine.sync import sync_catalogo
    from aiuda_core.models import Product
    from sqlalchemy import select

    report = sync_catalogo(
        session, tenant,
        odoo_client=FakeOdooCatalogo(), shopify_client=FakeShopifyCatalogo(),
        fuente_prefs={"catalogo_productos": "odoo"},
    )
    assert report.fuentes == ["odoo"]  # shopify quedó suprimido
    assert session.scalar(
        select(Product).where(Product.tenant_id == tenant.id, Product.sku == "PL-LOGO")
    ) is None  # no entró el producto de shopify
    assert session.scalar(
        select(Product).where(Product.tenant_id == tenant.id, Product.sku == "AN-14")
    ) is not None  # sí entró el de la fuente elegida


def test_sin_eleccion_de_esa_capacidad_lee_todas(session, tenant):
    """Una preferencia de OTRA capacidad no afecta al catálogo: se leen todas (previo)."""
    from aiuda_core.engine.sync import sync_catalogo

    report = sync_catalogo(
        session, tenant,
        odoo_client=FakeOdooCatalogo(), shopify_client=FakeShopifyCatalogo(),
        fuente_prefs={"directorio_clientes": "hubspot"},
    )
    assert set(report.fuentes) == {"odoo", "shopify"}


class FakeHubSpotDirectorio:
    def list_contacts(self):
        from aiuda_core.connectors.hubspot import Contacto

        return [
            Contacto(id="900", nombre="Cliente Demo", telefono="5215587654321", email="hs@cliente.mx"),
            Contacto(id="901", nombre="Boutique Lila", telefono="5215533334444", email="lila@correo.mx"),
        ]


def test_sync_directorio_lee_de_hubspot_tambien(session, tenant, customer):
    """Misma capacidad (directorio_clientes), segunda fuente por el mismo
    sync_directorio: ninguna fuente es privilegiada. Rellena sin pisar."""
    from aiuda_core.engine.sync import sync_directorio
    from aiuda_core.models import Customer
    from sqlalchemy import select

    customer.email = None  # el fixture ya existe con ese teléfono, sin email
    session.flush()

    report = sync_directorio(session, tenant, hubspot_client=FakeHubSpotDirectorio())
    assert report.fuentes == ["hubspot"]
    assert report.clientes_importados == 1  # solo "Boutique Lila" es alta

    demo = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == "5215587654321"))
    assert demo.email == "hs@cliente.mx"  # rellenó el faltante
    assert demo.presence["hubspot"]["ref"] == "900"  # procedencia marcada
    nueva = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Boutique Lila"))
    assert nueva is not None and nueva.presence["hubspot"]["ref"] == "901"


class FakeShopifyDirectorio:
    def list_customers(self):
        from aiuda_core.connectors.shopify import ContactoTienda

        return [
            ContactoTienda(id=601, name="Cliente Demo", phone="5215587654321", email="shop@cliente.mx"),
            ContactoTienda(id=602, name="Tienda Coral", phone="5215599998888", email="coral@correo.mx"),
        ]


def test_sync_directorio_lee_de_shopify_tambien(session, tenant, customer):
    """Cuarta fuente para directorio_clientes (Shopify customers) por el mismo
    sync_directorio: ninguna fuente es privilegiada. Rellena sin pisar."""
    from aiuda_core.engine.sync import sync_directorio
    from aiuda_core.models import Customer
    from sqlalchemy import select

    customer.email = None  # el fixture ya existe con ese teléfono, sin email
    session.flush()

    report = sync_directorio(session, tenant, shopify_client=FakeShopifyDirectorio())
    assert report.fuentes == ["shopify"]
    assert report.clientes_importados == 1  # solo "Tienda Coral" es alta

    demo = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == "5215587654321"))
    assert demo.email == "shop@cliente.mx"  # rellenó el faltante
    assert demo.presence["shopify"]["ref"] == "601"  # procedencia marcada
    nueva = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Tienda Coral"))
    assert nueva is not None and nueva.presence["shopify"]["ref"] == "602"


class FakeWooCatalogo:
    def list_products(self):
        from aiuda_core.connectors.woocommerce import ProductoTienda

        return [
            ProductoTienda(id=701, name="Vela aromática", sku="VL-LAV", price=220, stock=15),
            ProductoTienda(id=702, name="Difusor", sku="", price=480, stock=6),
        ]


def test_sync_catalogo_lee_de_woocommerce_tambien(session, tenant):
    """Misma capacidad (catalogo_productos), tercera familia de fuente por el mismo
    sync_catalogo: ninguna fuente es privilegiada."""
    from aiuda_core.engine.sync import sync_catalogo
    from aiuda_core.models import Product
    from sqlalchemy import select

    report = sync_catalogo(session, tenant, woocommerce_client=FakeWooCatalogo())
    assert report.fuentes == ["woocommerce"]
    assert report.productos_importados == 2
    vela = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.sku == "VL-LAV"))
    assert vela.source == "woocommerce" and float(vela.price) == 220
    # producto sin SKU: dedup por nombre, presencia con ref del id
    difusor = session.scalar(select(Product).where(Product.tenant_id == tenant.id, Product.name == "Difusor"))
    assert difusor is not None and difusor.presence["woocommerce"]["ref"] == "702"


class FakeHubSpotProspeccion:
    def list_open_deals(self):
        from aiuda_core.connectors.hubspot import Oportunidad

        return [
            Oportunidad(id="d1", nombre="Distribuidora Norte", monto=50000, etapa="appointmentscheduled"),
            Oportunidad(id="d2", nombre="Ferretería Sur", monto=12000, etapa="qualifiedtobuy"),
        ]


def test_sync_prospeccion_da_de_alta_prospectos_desde_hubspot(session, tenant):
    """Capacidad prospeccion por su propio lector: HubSpot deals -> Customer
    kind='prospecto' con etapa/monto/origen en meta. Ninguna fuente privilegiada."""
    from aiuda_core.engine.sync import sync_prospeccion
    from aiuda_core.models import Customer
    from sqlalchemy import select

    report = sync_prospeccion(session, tenant, hubspot_client=FakeHubSpotProspeccion())
    assert report.fuentes == ["hubspot"]
    assert report.clientes_importados == 2

    pros = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Distribuidora Norte"))
    assert pros.kind == "prospecto"
    assert pros.meta["etapa"] == "appointmentscheduled" and pros.meta["origen"] == "hubspot"
    assert pros.presence["hubspot"]["ref"] == "d1"


def test_sync_prospeccion_no_degrada_cliente_existente(session, tenant, customer):
    """Si un deal coincide por nombre con un cliente ya existente, se enriquece su meta
    y presencia pero NO se le baja a prospecto."""
    from aiuda_core.engine.sync import sync_prospeccion
    from aiuda_core.connectors.hubspot import Oportunidad

    class Solo:
        def list_open_deals(self):
            return [Oportunidad(id="d9", nombre=customer.name, monto=999, etapa="closedwon")]

    report = sync_prospeccion(session, tenant, hubspot_client=Solo())
    assert report.clientes_importados == 0  # ya existía, no alta
    session.refresh(customer)
    assert customer.kind == "cliente"  # no se degrada
    assert customer.meta["etapa"] == "closedwon"  # pero sí se enriquece
    assert "hubspot" in customer.presence


class FakeGcal:
    def list_events(self):
        from aiuda_core.connectors.gcal import CalendarEvent

        return [
            CalendarEvent(id="ev1", summary="Cita Joyería Aurora", start="2026-07-01T10:00:00-06:00",
                          end="2026-07-01T10:30:00-06:00", html_link="https://cal.google/ev1"),
            CalendarEvent(id="ev2", summary="Inventario", start="2026-07-02", end="2026-07-03",
                          html_link="https://cal.google/ev2"),
        ]


def test_sync_agenda_da_de_alta_citas_desde_calendar(session, tenant):
    """Capacidad agenda por su propio lector: Google Calendar -> Appointment, con o sin
    hora (día completo), procedencia en meta. Re-sincronizar no duplica."""
    from datetime import datetime
    from aiuda_core.engine.sync import sync_agenda
    from aiuda_core.models import Appointment
    from sqlalchemy import select

    report = sync_agenda(session, tenant, gcal_client=FakeGcal())
    assert report.fuentes == ["googlecalendar"]
    assert report.citas_importadas == 2

    cita = session.scalar(select(Appointment).where(Appointment.tenant_id == tenant.id, Appointment.title == "Cita Joyería Aurora"))
    assert cita.starts_at == datetime(2026, 7, 1, 10, 0)  # hora de pared, sin offset
    assert cita.source == "googlecalendar" and cita.meta["ref"] == "ev1"
    dia = session.scalar(select(Appointment).where(Appointment.tenant_id == tenant.id, Appointment.title == "Inventario"))
    assert dia.starts_at == datetime(2026, 7, 2, 0, 0)  # día completo -> medianoche

    # re-sincronizar: dedup por (título, hora) -> no duplica
    report2 = sync_agenda(session, tenant, gcal_client=FakeGcal())
    assert report2.citas_importadas == 0
    assert len(session.scalars(select(Appointment).where(Appointment.tenant_id == tenant.id)).all()) == 2


class FakeFacturama:
    def list_cfdis(self):
        from aiuda_core.connectors.facturama import Cfdi

        return [
            Cfdi(id="C-1", folio="F-001", total=12500.50, rfc_receptor="XAXX010101000",
                 razon_receptor="Cliente Demo", fecha="2026-05-01", status="active"),
            Cfdi(id="C-2", folio="NO-EXISTE", total=99, rfc_receptor="", razon_receptor="",
                 fecha="2026-05-02", status="active"),
        ]


class FakeFacturapi:
    def list_invoices(self):
        from aiuda_core.connectors.facturapi import FacturapiCfdi

        return [
            FacturapiCfdi(id="FA-9", folio="F-001", total=12500.50, rfc_receptor="XAXX010101000",
                          razon_receptor="Cliente Demo", fecha="2026-05-01", status="valid"),
        ]


def test_sync_cfdi_vincula_respaldo_fiscal_a_la_factura(session, tenant, customer, invoice):
    """Capacidad cfdi por su propio lector: el CFDI del PAC se adjunta a la factura del
    mismo folio (procedencia + verificación). Sin factura para el folio -> se ignora."""
    from aiuda_core.engine.sync import sync_cfdi

    assert invoice.cfdi == {} and invoice.verified == "sin_verificar"
    report = sync_cfdi(session, tenant, facturama_client=FakeFacturama())
    assert report.fuentes == ["facturama"]
    assert report.cfdis_importados == 1  # solo F-001 existe; "NO-EXISTE" se ignora

    session.refresh(invoice)
    assert invoice.cfdi["id"] == "C-1" and invoice.cfdi["source"] == "facturama"
    assert invoice.presence["facturama"]["ref"] == "C-1"
    assert invoice.verified == "verificada"  # un comprobante del SAT la respalda


def test_sync_cfdi_no_pisa_cfdi_existente_y_no_duplica(session, tenant, customer, invoice):
    """Re-sincronizar (o un segundo PAC) marca presencia pero no pisa el CFDI ya adjunto
    ni vuelve a contar."""
    from aiuda_core.engine.sync import sync_cfdi

    sync_cfdi(session, tenant, facturama_client=FakeFacturama())  # adjunta C-1
    report2 = sync_cfdi(session, tenant, facturapi_client=FakeFacturapi())  # otro PAC, mismo folio
    assert report2.fuentes == ["facturapi"]
    assert report2.cfdis_importados == 0  # ya tenía respaldo: no cuenta de nuevo

    session.refresh(invoice)
    assert invoice.cfdi["source"] == "facturama"  # no se pisó
    assert "facturapi" in invoice.presence and "facturama" in invoice.presence  # ambos respaldan


class FakeDenue:
    def buscar(self, condicion, lat, lng, radio_m=5000):
        from aiuda_core.connectors.denue import Negocio

        return [
            Negocio(id="D1", nombre="Ferretería El Tornillo", razon_social="", actividad="Ferreterías",
                    telefono="5215510101010", correo="", direccion="Calle 1, Centro, 06000"),
            Negocio(id="D2", nombre="", razon_social="Materiales del Sur SA", actividad="Materiales",
                    telefono="", correo="ventas@msur.mx", direccion="Av. 2, Sur, 03100"),
        ]


def test_sync_prospeccion_lee_de_denue_con_busquedas_del_config(session, tenant):
    """Segunda fuente de prospección (DENUE/INEGI): empresas por giro/zona según el perfil
    de cliente ideal que el dueño define en el config. Mismo sync_prospeccion, ninguna
    fuente privilegiada."""
    from aiuda_core.engine.sync import sync_prospeccion
    from aiuda_core.models import Customer
    from sqlalchemy import select

    tenant.config = {
        **(tenant.config or {}),
        "prospeccion": {"busquedas": [{"condicion": "ferreteria", "lat": 19.43, "lng": -99.13, "radio_m": 3000}]},
    }
    session.flush()

    report = sync_prospeccion(session, tenant, denue_client=FakeDenue())
    assert report.fuentes == ["denue"]
    assert report.clientes_importados == 2

    fer = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Ferretería El Tornillo"))
    assert fer.kind == "prospecto" and fer.meta["origen"] == "denue"
    assert fer.meta["actividad"] == "Ferreterías" and fer.presence["denue"]["ref"] == "D1"
    # sin nombre comercial: cae a la razón social
    msur = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Materiales del Sur SA"))
    assert msur is not None and msur.email == "ventas@msur.mx"


def test_sync_prospeccion_denue_sin_busquedas_es_noop(session, tenant):
    """Sin búsquedas en el config, DENUE no corre aunque se inyecte el cliente (no hay
    perfil que buscar)."""
    from aiuda_core.engine.sync import sync_prospeccion

    report = sync_prospeccion(session, tenant, denue_client=FakeDenue())
    assert "denue" not in report.fuentes
    assert report.clientes_importados == 0


class FakeOdooCompras:
    def fetch_purchase_orders(self):
        from aiuda_core.connectors.odoo import OdooPurchaseOrder

        return [
            OdooPurchaseOrder(order_id=1, folio="P00007", supplier="Aceros del Bajío",
                              total=45000, currency="MXN", status="sent", ordered_at="2026-06-10"),
            OdooPurchaseOrder(order_id=2, folio="P00008", supplier="Tornillos MX",
                              total=8200, currency="MXN", status="draft", ordered_at="2026-06-12"),
        ]


class FakeOdooComprasConfirmada:
    def fetch_purchase_orders(self):
        from aiuda_core.connectors.odoo import OdooPurchaseOrder

        return [
            OdooPurchaseOrder(order_id=1, folio="P00007", supplier="Aceros del Bajío",
                              total=46000, currency="MXN", status="purchase", ordered_at="2026-06-10"),
        ]


def test_sync_compras_alta_y_refresca_estado(session, tenant):
    """Capacidad compras por su propio lector: Odoo purchase.order -> PurchaseOrder.
    Re-sincronizar no duplica (dedup por folio) y refresca el estado/total de la fuente."""
    from datetime import date
    from aiuda_core.engine.sync import sync_compras
    from aiuda_core.models import PurchaseOrder
    from sqlalchemy import select

    report = sync_compras(session, tenant, odoo_client=FakeOdooCompras())
    assert report.fuentes == ["odoo"]
    assert report.ocs_importadas == 2

    oc = session.scalar(select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant.id, PurchaseOrder.folio == "P00007"))
    assert oc.supplier == "Aceros del Bajío" and oc.status == "sent"
    assert oc.ordered_at == date(2026, 6, 10) and oc.source == "odoo"
    assert oc.presence["odoo"]["ref"] == "P00007"

    # re-sync: P00007 ahora confirmada (state purchase) -> upsert, no duplica
    report2 = sync_compras(session, tenant, odoo_client=FakeOdooComprasConfirmada())
    assert report2.ocs_importadas == 0
    session.refresh(oc)
    assert oc.status == "purchase" and float(oc.total) == 46000  # estado/total refrescados
    total = len(session.scalars(select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant.id)).all())
    assert total == 2  # P00007 (upsert) + P00008, sin duplicar


def test_sync_fuentes_corre_cada_lector_sin_privilegiar(session, tenant, monkeypatch):
    """El orquestador corre el lector de CADA fuente (Odoo incluido, ya no huérfano),
    en orden directorio/prospección -> cartera/catálogo/agenda -> pagos, y acumula."""
    from aiuda_core.engine import sync as syncmod

    orden: list[str] = []

    def lector(nombre: str):
        def _f(s, t, today=None, fuente_prefs=None):
            orden.append(nombre)
            r = syncmod.SyncReport()
            r.fuentes.append(nombre)
            r.pedidos_importados = 1
            return r
        return _f

    monkeypatch.setattr(syncmod, "sync_directorio", lector("directorio"))
    monkeypatch.setattr(syncmod, "sync_prospeccion", lector("prospeccion"))
    monkeypatch.setattr(syncmod, "sync_pedidos", lector("pedidos"))
    monkeypatch.setattr(syncmod, "sync_odoo", lector("odoo"))
    monkeypatch.setattr(syncmod, "sync_catalogo", lector("catalogo"))
    monkeypatch.setattr(syncmod, "sync_agenda", lector("agenda"))
    monkeypatch.setattr(syncmod, "sync_compras", lector("compras"))
    monkeypatch.setattr(syncmod, "sync_cfdi", lector("cfdi"))
    monkeypatch.setattr(syncmod, "detectar_pagos", lector("pagos"))

    r = syncmod.sync_fuentes(session, tenant)
    # directorio/prospección primero, luego cartera/catálogo/agenda/compras, el CFDI que
    # respalda, y al final los pagos que concilian
    assert orden == ["directorio", "prospeccion", "pedidos", "odoo", "catalogo", "agenda", "compras", "cfdi", "pagos"]
    assert set(r.fuentes) == {"directorio", "prospeccion", "pedidos", "odoo", "catalogo", "agenda", "compras", "cfdi", "pagos"}
    assert r.pedidos_importados == 9  # acumulado
