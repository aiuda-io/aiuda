"""DEV: CFDIs reales en facturas Hanova, de forma coherente e idempotente.

1) Restaura los montos originales del demo y limpia CFDIs previos (evita el lío de
   una corrida anterior que dejaba montos raros y desalineados con los recordatorios).
2) Adjunta un CFDI realista (total > $1,000) solo a facturas SIN recordatorio
   (M-104/105/106), alineando el monto con el CFDI para que el cotejo salga en verde.

Uso: AIUDA_CFDI_SRC=/ruta/a/tus/cfdis python scripts/attach_cfdi_demo.py <db_url>

`AIUDA_CFDI_SRC` apunta a un directorio con subcarpetas, cada una con un
`invoice.xml` (CFDI) y opcionalmente `invoice.pdf`.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from aiuda_core.cfdi import parse_cfdi
from aiuda_core.models import Invoice

SRC = Path(os.environ.get("AIUDA_CFDI_SRC", "storage/invoices"))
TENANT = "7cd5302ace334c2ba6d3ebef818d1ad9"  # Hanova

# Montos canónicos del demo (cloud/.../api/main.py _SAMPLE_INVOICES).
ORIGINAL = {
    "M-101": 12500, "M-102": 4500, "M-103": 31200, "M-104": 2890,
    "M-105": 6750, "M-106": 9870, "M-107": 18750, "M-108": 3420,
}
# Facturas SIN recordatorio: seguras para alinear su monto con el CFDI.
TARGETS = ["M-104", "M-105", "M-106"]


def _inv(s, folio):
    return s.scalar(
        select(Invoice).where(Invoice.tenant_id == TENANT, Invoice.folio == folio)
    )


def main(url: str) -> None:
    realistas = [
        f
        for f in sorted(SRC.iterdir())
        if (f / "invoice.xml").exists()
        and (parse_cfdi((f / "invoice.xml").read_bytes()).get("total") or 0) > 1000
    ]
    engine = create_engine(url)
    with Session(engine) as s:
        # 1) restaura montos y limpia CFDIs previos
        for folio, amount in ORIGINAL.items():
            inv = _inv(s, folio)
            if inv is None:
                continue
            inv.amount = amount
            inv.currency = "MXN"
            inv.cfdi = {}
            inv.cfdi_xml = None
            inv.cfdi_pdf = None
        s.flush()
        # 2) adjunta CFDI realista a las facturas sin recordatorio
        for folio, folder in zip(TARGETS, realistas):
            inv = _inv(s, folio)
            if inv is None:
                continue
            xml = (folder / "invoice.xml").read_bytes()
            pdf = folder / "invoice.pdf"
            data = parse_cfdi(xml)
            inv.cfdi = data
            inv.cfdi_xml = xml.decode("utf-8", errors="replace")
            inv.cfdi_pdf = pdf.read_bytes() if pdf.exists() else None
            inv.amount = Decimal(str(data["total"]))
            inv.currency = data.get("moneda") or "MXN"
            print(f"CFDI {data.get('uuid')} -> {folio} (total {data.get('total')})")
        s.commit()
    print("OK: montos restaurados y CFDIs alineados")


if __name__ == "__main__":
    main(sys.argv[1])
