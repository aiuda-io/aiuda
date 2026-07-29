"""Robustez del conector Odoo: paginación, lectura batch y reintentos.

El contrato con el Odoo real (requests exactos, formas de Odoo 19) vive en
test_odoo_contrato.py; aquí se prueba el comportamiento que los fixtures en
vivo no pueden ejercitar: el loop multi-página, el tope de registros, el
read único de res.partner con cartera de varias facturas y los reintentos
ante errores transitorios.
"""

import logging
import xmlrpc.client

import pytest

import aiuda_core.connectors.odoo as odoo_mod
from aiuda_core.connectors.odoo import OdooConnector


def _conector(page_size: int, max_records: int) -> OdooConnector:
    return OdooConnector(
        url="https://odoo.ejemplo.mx",
        db="db",
        username="u",
        api_key="k",
        page_size=page_size,
        max_records=max_records,
    )


class PaginasFalsas:
    """Sirve un search_read paginado como Odoo: respeta limit/offset sobre un
    dataset fijo y registra cada llamada (para asegurar los offsets pedidos)."""

    def __init__(self, registros: list[dict]):
        self.registros = registros
        self.llamadas: list[dict] = []

    def execute(self, model, method, *args, **kwargs):
        assert method == "search_read"
        self.llamadas.append({"model": model, "kwargs": dict(kwargs)})
        offset, limit = kwargs["offset"], kwargs["limit"]
        return [dict(r) for r in self.registros[offset : offset + limit]]


def test_paginacion_recorre_todas_las_paginas():
    datos = [{"id": i, "name": f"P{i}"} for i in range(1, 6)]  # 5 registros
    conn = _conector(page_size=2, max_records=100)
    paginas = PaginasFalsas(datos)
    conn._execute = paginas.execute

    out = conn._search_read_paginado("res.partner", [("customer_rank", ">", 0)], ["name"])

    assert [r["id"] for r in out] == [1, 2, 3, 4, 5]
    # 3 páginas: 2 + 2 + 1 (la corta termina el loop)
    assert [c["kwargs"]["offset"] for c in paginas.llamadas] == [0, 2, 4]
    assert all(c["kwargs"]["limit"] == 2 for c in paginas.llamadas)
    assert all(c["kwargs"]["order"] == "id" for c in paginas.llamadas)


def test_paginacion_pagina_exacta_no_pide_de_mas():
    # 4 registros con página de 2: la última página llena obliga UNA llamada más
    # (que regresa vacía) — así se sabe que ya no hay datos sin adivinar.
    datos = [{"id": i} for i in range(1, 5)]
    conn = _conector(page_size=2, max_records=100)
    paginas = PaginasFalsas(datos)
    conn._execute = paginas.execute

    out = conn._search_read_paginado("res.partner", [], ["name"])

    assert len(out) == 4
    assert [c["kwargs"]["offset"] for c in paginas.llamadas] == [0, 2, 4]


def test_paginacion_topa_en_max_records_y_lo_dice(caplog):
    datos = [{"id": i} for i in range(1, 11)]  # 10 registros, tope en 3
    # Tope que NO es múltiplo de la página: aún así nunca se devuelve de más.
    conn = _conector(page_size=2, max_records=3)
    paginas = PaginasFalsas(datos)
    conn._execute = paginas.execute

    with caplog.at_level(logging.WARNING, logger="aiuda.odoo"):
        out = conn._search_read_paginado("account.move", [], ["name"])

    # Lectura parcial honesta: corta en el tope exacto y lo avisa en el log
    assert [r["id"] for r in out] == [1, 2, 3]
    assert [c["kwargs"]["offset"] for c in paginas.llamadas] == [0, 2]
    assert any("topada" in rec.message for rec in caplog.records)


def test_cartera_lee_partners_en_un_solo_batch():
    """Con varias facturas (y clientes repetidos) hay UN solo read de
    res.partner: ids deduplicados en orden de aparición. Una factura cuyo
    cliente ya no exista en Odoo se omite sin tumbar el resto."""

    def factura(mid: int, folio: str, partner) -> dict:
        return {
            "id": mid,
            "name": folio,
            "partner_id": partner,
            "amount_residual": 100.0 * mid,
            "currency_id": [33, "MXN"],
            "invoice_date": "2026-07-01",
            "invoice_date_due": "2026-07-15",
        }

    class FakeCartera:
        def __init__(self):
            self.reads: list[list] = []

        def execute(self, model, method, *args, **kwargs):
            if method == "search_read":
                return [
                    factura(1, "F-001", [11, "Ana"]),
                    factura(2, "F-002", [12, "Beto"]),
                    factura(3, "F-003", [11, "Ana"]),  # cliente repetido
                    factura(4, "F-004", [13, "Fantasma"]),  # ya no existe
                ]
            if method == "fields_get":
                return {"name": {}, "phone": {}}  # Odoo 19: sin mobile
            if method == "read":
                self.reads.append(list(args))
                return [
                    {"id": 11, "name": "Ana", "phone": "55 1111"},
                    {"id": 12, "name": "Beto", "phone": False},
                ]
            raise AssertionError(f"llamada inesperada: {model}.{method}")

    conn = _conector(page_size=200, max_records=5000)
    fake = FakeCartera()
    conn._execute = fake.execute

    invoices = conn.fetch_open_invoices()

    assert fake.reads == [[[11, 12, 13]]]  # UN read batch, deduplicado y en orden
    assert [i.folio for i in invoices] == ["F-001", "F-002", "F-003"]  # F-004 se omite
    assert invoices[0].customer_name == "Ana"
    assert invoices[2].customer_name == "Ana"  # el repetido sale del mismo read
    assert invoices[0].customer_phone == "551111"
    assert invoices[1].customer_phone == ""  # phone False -> ""


def test_fetch_partners_pagina_de_verdad():
    """El método público usa el loop: dos páginas de clientes salen completas."""
    datos = [
        {"id": 1, "name": "A", "phone": "55 1", "email": "a@x.mx"},
        {"id": 2, "name": "B", "phone": False, "email": False},
        {"id": 3, "name": "C", "phone": False, "email": "c@x.mx"},
    ]

    class Fake(PaginasFalsas):
        def execute(self, model, method, *args, **kwargs):
            if method == "fields_get":
                return {"name": {}, "phone": {}, "email": {}}
            return super().execute(model, method, *args, **kwargs)

    conn = _conector(page_size=2, max_records=100)
    conn._execute = Fake(datos).execute

    partners = conn.fetch_partners()

    assert [p.partner_id for p in partners] == [1, 2, 3]
    assert partners[0].phone == "551"  # espacios fuera
    assert partners[1].email == ""  # False -> ""


# ---------- fetch_invoice_states: lectura dirigida por id (para el cierre del sync) ----------


def test_fetch_invoice_states_lee_por_id_y_omite_los_que_no_estan():
    """Un read único de account.move por ids; Odoo devuelve SOLO los que aún
    existen. Un id borrado no viene y se omite (no truena): el sync lo deja igual."""
    llamadas: list[tuple] = []

    def fake(model, method, *args, **kwargs):
        llamadas.append((model, method, list(args), dict(kwargs)))
        return [
            {"id": 5, "name": "INV/5", "state": "posted", "payment_state": "paid", "amount_residual": 0.0},
            {"id": 9, "name": False, "state": "cancel", "payment_state": "not_paid", "amount_residual": 10.0},
        ]

    conn = _conector(page_size=200, max_records=5000)
    conn._execute = fake

    out = conn.fetch_invoice_states([5, 9, 441])

    assert set(out) == {5, 9}  # 441 no vino en la respuesta: se omite
    assert out[5]["payment_state"] == "paid"
    assert out[9]["state"] == "cancel"
    assert llamadas == [
        (
            "account.move",
            "read",
            [[5, 9, 441]],
            {"fields": ["name", "state", "payment_state", "amount_residual"]},
        )
    ]


def test_fetch_invoice_states_sin_ids_no_toca_odoo():
    """Sin ids que preguntar no se hace roundtrip alguno (no-op barato)."""
    conn = _conector(page_size=200, max_records=5000)

    def no_debe(*args, **kwargs):
        raise AssertionError("no debe llamar a Odoo sin ids")

    conn._execute = no_debe
    assert conn.fetch_invoice_states([]) == {}


# ---------- Reintentos: solo errores transitorios, solo lecturas ----------


class ModelosFallones:
    """execute_kw truena con las fallas encoladas y luego contesta; cuenta intentos."""

    def __init__(self, fallas: list[Exception], respuesta=42):
        self.fallas = list(fallas)
        self.respuesta = respuesta
        self.intentos = 0

    def execute_kw(self, *args):
        self.intentos += 1
        if self.fallas:
            raise self.fallas.pop(0)
        return self.respuesta


class ComunOK:
    def authenticate(self, db, user, key, ctx):
        return 7


@pytest.fixture()
def sin_espera(monkeypatch):
    """Backoff en cero para que los tests no duerman de verdad."""
    monkeypatch.setattr(odoo_mod, "_ODOO_BACKOFF_S", (0.0, 0.0))


def _con_transporte(monkeypatch, modelos, common=None) -> OdooConnector:
    conn = _conector(page_size=200, max_records=5000)
    monkeypatch.setattr(
        odoo_mod,
        "_proxy",
        lambda url: (common or ComunOK()) if url.endswith("/common") else modelos,
    )
    return conn


def test_timeout_de_red_se_reintenta_y_queda_en_el_log(monkeypatch, sin_espera, caplog):
    modelos = ModelosFallones([TimeoutError("timed out")], respuesta=3)
    conn = _con_transporte(monkeypatch, modelos)

    with caplog.at_level(logging.WARNING, logger="aiuda.odoo"):
        out = conn._execute("res.partner", "search_count", [])

    assert out == 3
    assert modelos.intentos == 2  # falló una vez, el reintento la sacó
    assert any("reintento 1/2" in rec.message for rec in caplog.records)


def test_reintentos_se_agotan_y_el_error_sube(monkeypatch, sin_espera):
    fallas = [TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")]
    modelos = ModelosFallones(fallas)
    conn = _con_transporte(monkeypatch, modelos)

    with pytest.raises(TimeoutError):
        conn._execute("res.partner", "search_read", [])
    assert modelos.intentos == 3  # 1 intento + 2 reintentos, ni uno más


def test_fault_de_odoo_no_se_reintenta(monkeypatch, sin_espera):
    # Un Fault es Odoo contestando "no" (auth/permisos/datos): repetir no lo arregla.
    modelos = ModelosFallones([xmlrpc.client.Fault(1, "Access Denied")])
    conn = _con_transporte(monkeypatch, modelos)

    with pytest.raises(xmlrpc.client.Fault):
        conn._execute("res.partner", "search_read", [])
    assert modelos.intentos == 1


def test_5xx_reintenta_pero_4xx_no(monkeypatch, sin_espera):
    e502 = xmlrpc.client.ProtocolError("odoo.ejemplo.mx", 502, "Bad Gateway", {})
    modelos = ModelosFallones([e502], respuesta=1)
    conn = _con_transporte(monkeypatch, modelos)
    assert conn._execute("res.partner", "read", [1]) == 1
    assert modelos.intentos == 2

    e404 = xmlrpc.client.ProtocolError("odoo.ejemplo.mx", 404, "Not Found", {})
    modelos4 = ModelosFallones([e404])
    conn4 = _con_transporte(monkeypatch, modelos4)
    with pytest.raises(xmlrpc.client.ProtocolError):
        conn4._execute("res.partner", "read", [1])
    assert modelos4.intentos == 1


def test_credenciales_malas_no_se_reintentan(monkeypatch, sin_espera):
    class ComunRechaza:
        def __init__(self):
            self.intentos = 0

        def authenticate(self, db, user, key, ctx):
            self.intentos += 1
            return 0  # Odoo contesta uid falso: credenciales malas

    common = ComunRechaza()
    conn = _con_transporte(monkeypatch, ModelosFallones([]), common=common)

    with pytest.raises(PermissionError):
        conn._execute("res.partner", "search_read", [])
    assert common.intentos == 1  # jamás se reintenta un error de auth


def test_writes_nunca_se_reintentan(monkeypatch, sin_espera):
    # Un timeout en un write es ambiguo (pudo llegar a Odoo): reintentarlo
    # podría asentar un pago dos veces. Sube tal cual al primer intento.
    modelos = ModelosFallones([TimeoutError("timed out")])
    conn = _con_transporte(monkeypatch, modelos)

    with pytest.raises(TimeoutError):
        conn._execute("account.payment.register", "create", {"amount": 1.0})
    assert modelos.intentos == 1
