"""Contrato de LECTURA del conector Odoo contra respuestas REALES grabadas.

VERIFICADO EN VIVO el 2026-07-07 contra el Odoo de Hanova Consulting
(Odoo 19.0+e-20260318, XML-RPC): test_connection, fetch_open_invoices,
fetch_partners, fetch_products y fetch_purchase_orders corrieron contra la
instancia real con la credencial cifrada del tenant, y cada llamada
(model, method, args, kwargs, response) quedó grabada en
``data/contratos/odoo/*.json`` con los datos personales REDACTADOS
(nombres/teléfonos/emails reales -> sintéticos con la MISMA forma; False sigue
siendo False, los pares [id, nombre] siguen siendo pares).

Estos tests corren SIN red: reproducen las respuestas grabadas y verifican dos
cosas a la vez:
1. Request: el conector manda EXACTAMENTE lo que mandó en vivo (mismo orden,
   mismos domains, mismos fields). Si alguien cambia el conector, esto truena.
2. Parsing: el conector entiende la FORMA real de Odoo 19 — que es más rasposa
   que los fakes: `name: false` en borradores, `invoice_date: false`,
   `phone: false`, y campos que Odoo 19 YA NO TIENE (`mobile` en res.partner,
   `qty_available` en product.template sin el módulo de inventario).

Qué NO queda verificado en vivo (honesto):
- fetch_purchase_orders con DATOS: Hanova no tenía órdenes de compra el día de
  la grabación; el contrato pinned es el request + la respuesta vacía. El
  parsing con datos se cubre con los fakes de test_connectors/test_sync.
- La PAGINACIÓN que el conector ganó DESPUÉS de la grabación (limit/offset/
  order='id' en search_read): los kwargs de los fixtures se extendieron a mano
  (campo `ajuste_post_grabacion` en cada uno) y las respuestas siguen siendo
  las grabadas en vivo, reordenadas por id donde aplica. El loop multi-página,
  el tope y los reintentos se cubren en test_odoo_robustez.py; falta
  re-verificar el request paginado en vivo contra Hanova.
"""

import json
from datetime import date
from pathlib import Path

import pytest

import aiuda_core.connectors.odoo as odoo_mod
from aiuda_core.connectors.odoo import OdooConnector

DIR_CONTRATOS = Path(__file__).parent / "data" / "contratos" / "odoo"
FECHA_VERIFICACION = "2026-07-07"


def _fixture(nombre: str) -> dict:
    return json.loads((DIR_CONTRATOS / f"{nombre}.json").read_text())


def _forma_json(valor):
    """Normaliza a la forma que viaja por el cable: XML-RPC (y el fixture JSON)
    no distinguen tupla de lista, el conector sí las usa internamente."""
    if isinstance(valor, (list, tuple)):
        return [_forma_json(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _forma_json(v) for k, v in valor.items()}
    return valor


class ReplayOdoo:
    """Reproduce la sesión XML-RPC grabada.

    Sirve las respuestas en FIFO por (model, method) y REGISTRA cada request que
    hace el conector; el test compara al final la lista completa contra lo
    grabado (así un drift en fields_get no se pierde en el try/except de
    `_existing_fields`, que se traga excepciones a propósito)."""

    def __init__(self, fixture: dict):
        self.esperadas = list(fixture["llamadas"])
        self._colas: dict[tuple[str, str], list] = {}
        for c in self.esperadas:
            self._colas.setdefault((c["model"], c["method"]), []).append(c["response"])
        self.hechas: list[dict] = []

    def execute(self, model, method, *args, **kwargs):
        self.hechas.append(
            {
                "model": model,
                "method": method,
                "args": _forma_json(list(args)),
                "kwargs": _forma_json(kwargs),
            }
        )
        cola = self._colas.get((model, method))
        if not cola:
            raise LookupError(f"Llamada no grabada en el contrato: {model}.{method}")
        return cola.pop(0)

    def verifica(self):
        """El conector hizo EXACTAMENTE las llamadas grabadas, en el mismo orden."""
        grabadas = [
            {"model": c["model"], "method": c["method"], "args": c["args"], "kwargs": c["kwargs"]}
            for c in self.esperadas
        ]
        assert self.hechas == grabadas


@pytest.fixture()
def conector():
    def _para(nombre: str) -> tuple[OdooConnector, ReplayOdoo]:
        conn = OdooConnector(
            url="https://odoo.ejemplo.mx", db="db", username="u", api_key="k"
        )
        replay = ReplayOdoo(_fixture(nombre))
        conn._execute = replay.execute  # mismo seam que usa todo el conector
        return conn, replay

    return _para


# ---------- Guardias del fixture: si alguien lo recorta, deja de ser contrato ----------


def test_fixtures_declaran_verificacion_en_vivo():
    nombres = [
        "test_connection",
        "fetch_open_invoices",
        "fetch_partners",
        "fetch_products",
        "fetch_purchase_orders",
    ]
    for nombre in nombres:
        data = _fixture(nombre)
        assert data["verificado_en_vivo"] == FECHA_VERIFICACION
        assert "REDACTADOS" in data["fuente"]
        assert data["llamadas"], f"{nombre}: fixture sin llamadas grabadas"


def test_odoo19_ya_no_tiene_mobile_ni_qty_available():
    """Documenta POR QUÉ existe `_existing_fields`: en el Odoo 19 real de Hanova,
    res.partner ya no trae `mobile` y product.template no trae `qty_available`
    (sin el módulo de inventario). Pedirlos tumbaba el search_read entero."""
    partner_fields = next(
        c["response"]
        for c in _fixture("fetch_open_invoices")["llamadas"]
        if c["method"] == "fields_get"
    )
    assert "mobile" not in partner_fields
    assert "phone" in partner_fields
    product_fields = next(
        c["response"]
        for c in _fixture("fetch_products")["llamadas"]
        if c["method"] == "fields_get"
    )
    assert "qty_available" not in product_fields
    assert "list_price" in product_fields


# ---------- Contrato por método: request idéntico al vivo + parsing de la forma real ----------


def test_test_connection_contrato_real(conector, monkeypatch):
    conn, replay = conector("test_connection")
    version_grabada = _fixture("test_connection")["version_response"]

    class FakeCommon:
        def version(self):
            return dict(version_grabada)

        def authenticate(self, db, user, key, ctx):
            return 7

    monkeypatch.setattr(odoo_mod, "_proxy", lambda url: FakeCommon())
    out = conn.test_connection()
    replay.verifica()
    # La forma real: version del server + conteos como enteros. `partners` sigue
    # siendo el search_count SIN domain (25 contactos en vivo, señal de vida);
    # `clientes` cuenta customer_rank>0 (3 en vivo, lo que fetch_partners lee) e
    # `invoices` usa el filtro de fetch_open_invoices (saldo pendiente). Así el
    # "Probar conexión" del dueño ya no sugiere que se ingiere más de lo real.
    assert out == {
        "version": "19.0+e-20260318",
        "partners": 25,
        "clientes": 3,
        "invoices": 1,
    }


def test_fetch_open_invoices_contrato_real(conector):
    """La factura viva de Hanova era un BORRADOR: `name: false` (sin folio aún)
    e `invoice_date: false`. El conector debe sintetizar folio provisional y
    caer la emisión al vencimiento — con datos reales, no un fake amable."""
    conn, replay = conector("fetch_open_invoices")
    invoices = conn.fetch_open_invoices()
    replay.verifica()

    assert len(invoices) == 1
    inv = invoices[0]
    assert inv.move_id == 1
    assert inv.folio == "borrador-1"  # name era false -> folio provisional por id
    assert inv.customer_name == "Cliente Sintetico 1"
    assert inv.customer_phone == "+525551010001"  # espacios fuera, prefijo intacto
    assert inv.amount == 29000.0
    assert inv.currency == "MXN"
    # invoice_date false -> la emisión cae a la fecha de vencimiento
    assert inv.issued_date == date(2026, 7, 7)
    assert inv.due_date == date(2026, 7, 7)
    assert inv.partner_id == 11


def test_fetch_partners_contrato_real(conector):
    """Los 3 clientes reales (customer_rank>0) venían SIN teléfono (`phone: false`)
    y uno sin correo. El conector normaliza False -> cadena vacía, nunca truena."""
    conn, replay = conector("fetch_partners")
    partners = conn.fetch_partners()
    replay.verifica()

    assert len(partners) == 3
    assert [p.partner_id for p in partners] == [28, 29, 30]
    assert all(p.phone == "" for p in partners)  # phone false en los 3, en vivo
    assert partners[0].email == "contacto1@ejemplo.mx"
    assert partners[1].email == ""  # email false -> ""
    assert partners[2].name == "Cliente Sintetico 4 SA de CV"


def test_fetch_products_contrato_real(conector):
    """9 productos reales: `default_code: false` (sin SKU) y SIN `qty_available`
    en el modelo (Odoo 19 de Hanova, sin inventario) -> stock 0.0 honesto.
    Con la paginación el request pide order='id', así que vienen por id."""
    conn, replay = conector("fetch_products")
    products = conn.fetch_products()
    replay.verifica()

    assert len(products) == 9
    assert [p.product_id for p in products] == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    primero = products[0]
    assert primero.name == "Servicio sintetico 9"
    assert primero.sku == ""  # default_code false -> ""
    assert primero.price == 71716.67
    assert primero.unit == "Units"
    # qty_available no existe en este Odoo: el conector no lo pide y el stock
    # queda 0.0 para TODOS. Honesto pero engañoso en UI si se muestra como "0".
    assert all(p.stock == 0.0 for p in products)


def test_fetch_purchase_orders_contrato_real(conector):
    """Hanova no tenía órdenes de compra: el contrato pinned aquí es el REQUEST
    (domain vacío + fields) y que la respuesta vacía no truene. El parsing con
    datos NO quedó verificado en vivo (se cubre con fakes en test_sync)."""
    conn, replay = conector("fetch_purchase_orders")
    orders = conn.fetch_purchase_orders()
    replay.verifica()
    assert orders == []


def test_lectura_paginada_en_contrato():
    """Cierre del hallazgo de la verificación en vivo (2026-07-07): las cuatro
    lecturas ahora paginan (limit/offset con order='id' estable) y así quedó
    pinned en el contrato. El loop multi-página y el tope viven en
    test_odoo_robustez.py; este pin protege el REQUEST."""
    for nombre in (
        "fetch_open_invoices",
        "fetch_partners",
        "fetch_products",
        "fetch_purchase_orders",
    ):
        data = _fixture(nombre)
        sr = next(c for c in data["llamadas"] if c["method"] == "search_read")
        assert sr["kwargs"]["limit"] == 200, nombre
        assert sr["kwargs"]["offset"] == 0, nombre
        assert sr["kwargs"]["order"] == "id", nombre
        # Honestidad del fixture: el kwargs paginado se agregó a mano tras la
        # grabación en vivo y el fixture lo declara.
        assert "pagina" in data.get("ajuste_post_grabacion", ""), nombre


def test_partners_de_la_cartera_en_un_solo_read():
    """Cierre del N+1 destapado en vivo: por corrida hay UN read de res.partner
    con TODOS los clientes de la cartera, ya no un read por factura."""
    llamadas = _fixture("fetch_open_invoices")["llamadas"]
    reads = [c for c in llamadas if c["method"] == "read"]
    assert len(reads) == 1
    sr = next(c for c in llamadas if c["method"] == "search_read")
    ids_cartera = [r["partner_id"][0] for r in sr["response"] if r.get("partner_id")]
    assert reads[0]["args"] == [ids_cartera]


# ---------- fetch_invoice_states: lectura dirigida grabada contra la réplica local ----------


def test_fixture_fetch_invoice_states_es_de_la_replica_local():
    """Guardia del fixture nuevo: grabado el 2026-07-11 contra la réplica local
    Odoo 19 (datos ya sintéticos, sin redacción) con UN solo read tipado."""
    data = _fixture("fetch_invoice_states")
    assert data["verificado_en_vivo"] == "2026-07-11"
    assert "réplica local Odoo 19" in data["fuente"]
    reads = [c for c in data["llamadas"] if c["method"] == "read"]
    assert len(reads) == 1
    assert reads[0]["model"] == "account.move"
    assert reads[0]["kwargs"]["fields"] == [
        "name", "state", "payment_state", "amount_residual"
    ]


def test_fetch_invoice_states_contrato_real(conector):
    """Lectura dirigida por id contra la réplica local Odoo 19: un read único de
    account.move con los cuatro campos del estado. La respuesta real MEZCLA los tres
    desenlaces que el sync distingue —pagada, parcial (se deja igual) y cancelada— y
    una cancelada trae `name: false`, como cualquier borrador sin folio."""
    conn, replay = conector("fetch_invoice_states")
    estados = conn.fetch_invoice_states([1, 131, 248])
    replay.verifica()

    assert set(estados) == {1, 131, 248}
    assert estados[1]["payment_state"] == "paid"  # pagada del todo -> el sync la cierra
    assert estados[131]["payment_state"] == "partial"  # parcial -> se deja como está
    assert estados[131]["amount_residual"] == 45593.86
    assert estados[248]["state"] == "cancel"  # cancelada -> el sync la marca cancelled
    assert estados[248]["name"] is False  # sin folio, forma real de Odoo 19
