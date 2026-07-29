"""DEV: pagos pendientes de conciliar para ver a Diego en acción.

Crea pagos (banco/Stripe) que coinciden con facturas Hanova. Algunos comparten
monto (M-104/105/106 = 17,073.60), así que el nombre del depositante desempata —
justo lo que Diego usa para proponer la correcta.

Uso: python scripts/seed_payments_demo.py <db_url>
"""

import sys
from datetime import date

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from aiuda_core.models import Payment

TENANT = "7cd5302ace334c2ba6d3ebef818d1ad9"  # Hanova

PAGOS = [
    # monto exacto + nombre del cliente: match claro a M-107
    {"amount": 18750.00, "source": "banco", "counterparty": "TALLER MECANICO RIVERA SA"},
    # 17,073.60 lo comparten M-104/105/106; "Papelería Bic" desempata a M-104
    {"amount": 17073.60, "source": "stripe", "counterparty": "PAPELERIA BIC SA DE CV"},
    # match limpio a M-108
    {"amount": 3420.00, "source": "banco", "counterparty": "RESTAURANTE EL FOGON"},
]


def main(url: str) -> None:
    engine = create_engine(url)
    with Session(engine) as s:
        # Idempotente: limpia pendientes y vuelve a sembrar.
        s.execute(
            delete(Payment).where(Payment.tenant_id == TENANT, Payment.status == "pendiente")
        )
        for p in PAGOS:
            s.add(
                Payment(
                    tenant_id=TENANT,
                    amount=p["amount"],
                    currency="MXN",
                    paid_at=date(2026, 6, 15),
                    source=p["source"],
                    counterparty=p["counterparty"],
                    status="pendiente",
                )
            )
        s.commit()
    print(f"OK: {len(PAGOS)} pagos pendientes sembrados")


if __name__ == "__main__":
    main(sys.argv[1])
