"""Import de facturas desde CSV — la fuente para pilotos sin sistema.

Columnas esperadas (plantilla en core/tests/data/facturas_demo.csv):
folio,cliente,telefono,monto,moneda,fecha_emision,fecha_vencimiento,estatus
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.models import Customer, Invoice

REQUIRED_COLUMNS = {"folio", "cliente", "telefono", "monto", "fecha_emision", "fecha_vencimiento"}


class CsvFormatError(Exception):
    pass


@dataclass
class ImportResult:
    created: int
    skipped: int
    errors: list[str]


def parse_rows(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise CsvFormatError(f"Faltan columnas en el CSV: {sorted(missing)}")
        return [row for row in reader if any((v or "").strip() for v in row.values())]


def import_invoices(session: Session, tenant_id: str, path: str | Path) -> ImportResult:
    """Idempotente por (tenant_id, folio): re-importar el mismo CSV no duplica."""
    created, skipped, errors = 0, 0, []
    for i, row in enumerate(parse_rows(path), start=2):  # 2 = primera fila de datos
        try:
            folio = row["folio"].strip()
            exists = session.scalar(
                select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.folio == folio)
            )
            if exists:
                from aiuda_core.engine.presence import add_presence

                add_presence(exists, "excel", folio)
                skipped += 1
                continue
            phone = row["telefono"].strip()
            customer = session.scalar(
                select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone == phone)
            )
            if customer is None:
                customer = Customer(
                    tenant_id=tenant_id, name=row["cliente"].strip(), phone=phone
                )
                session.add(customer)
                session.flush()
            session.add(
                Invoice(
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    folio=folio,
                    amount=float(row["monto"]),
                    currency=(row.get("moneda") or "MXN").strip() or "MXN",
                    issued_date=date.fromisoformat(row["fecha_emision"].strip()),
                    due_date=date.fromisoformat(row["fecha_vencimiento"].strip()),
                    status=(row.get("estatus") or "open").strip() or "open",
                    source="csv",
                )
            )
            created += 1
        except (KeyError, ValueError) as exc:
            errors.append(f"Fila {i}: {exc}")
    session.flush()
    return ImportResult(created=created, skipped=skipped, errors=errors)
