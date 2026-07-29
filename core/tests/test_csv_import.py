from pathlib import Path

import pytest
from sqlalchemy import select

from aiuda_core.connectors.csv_import import CsvFormatError, import_invoices, parse_rows
from aiuda_core.models import Customer, Invoice

DATA = Path(__file__).parent / "data" / "facturas_demo.csv"


def test_parse_rows_lee_plantilla():
    rows = parse_rows(DATA)
    assert len(rows) == 5
    assert rows[0]["folio"] == "F-100"


def test_import_crea_clientes_y_facturas(session, tenant):
    result = import_invoices(session, tenant.id, DATA)
    assert result.created == 5
    assert result.errors == []
    invoices = session.scalars(select(Invoice).where(Invoice.tenant_id == tenant.id)).all()
    assert len(invoices) == 5
    customers = session.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all()
    assert len(customers) == 4  # Don Pepe tiene 2 facturas, 1 cliente


def test_reimport_es_idempotente(session, tenant):
    import_invoices(session, tenant.id, DATA)
    result = import_invoices(session, tenant.id, DATA)
    assert result.created == 0
    assert result.skipped == 5


def test_csv_sin_columnas_obligatorias(tmp_path, session, tenant):
    bad = tmp_path / "malo.csv"
    bad.write_text("folio,monto\nF-1,100\n", encoding="utf-8")
    with pytest.raises(CsvFormatError):
        import_invoices(session, tenant.id, bad)


def test_fila_invalida_no_tumba_el_import(tmp_path, session, tenant):
    csv_text = (
        "folio,cliente,telefono,monto,moneda,fecha_emision,fecha_vencimiento,estatus\n"
        "F-1,Cliente A,5215500000001,100.00,MXN,2026-01-01,2026-02-01,open\n"
        "F-2,Cliente B,5215500000002,NO_ES_MONTO,MXN,2026-01-01,2026-02-01,open\n"
    )
    path = tmp_path / "mixto.csv"
    path.write_text(csv_text, encoding="utf-8")
    result = import_invoices(session, tenant.id, path)
    assert result.created == 1
    assert len(result.errors) == 1
    assert "Fila 3" in result.errors[0]
