"""Demo end-to-end de Cleo, sin credenciales.

Corre con: uv run python scripts/demo.py
  - Sin ANTHROPIC_API_KEY: usa redacciones simuladas (muestra el flujo completo).
  - Con ANTHROPIC_API_KEY: redacta los recordatorios con Claude de verdad.
"""

import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from aiuda_core.config import settings
from aiuda_core.connectors.csv_import import import_invoices
from aiuda_core.engine.engine import CleoEngine
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Base, Customer, Tenant

TODAY = date(2026, 6, 9)
DATA = Path(__file__).parent.parent / "core" / "tests" / "data" / "facturas_demo.csv"


class SimulatedMessages:
    def create(self, **kwargs):
        class Block:
            type = "text"
            text = (
                "Hola, le saludamos de Taquería La Bonita . Le recordamos amablemente "
                "su factura pendiente. ¿Nos ayuda con el pago o nos avisa si ya lo realizó? "
                "¡Gracias!"
            )

        class Usage:
            input_tokens = 0
            output_tokens = 0

        class Response:
            content = [Block()]
            stop_reason = "end_turn"
            usage = Usage()

        return Response()


class SimulatedClient:
    messages = SimulatedMessages()


def main() -> None:
    engine_db = create_engine("sqlite://")
    Base.metadata.create_all(engine_db)
    session = sessionmaker(bind=engine_db, expire_on_commit=False)()

    tenant = Tenant(
        name="Taquería La Bonita",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={},
    )
    session.add(tenant)
    session.flush()

    result = import_invoices(session, tenant.id, DATA)
    print(f" Facturas importadas del CSV: {result.created}\n")

    live = bool(settings.anthropic_api_key)
    runner = ClaudeRunner(client=None if live else SimulatedClient())
    print(f" Modo: {'Claude real' if live else 'simulado (sin ANTHROPIC_API_KEY)'}\n")

    outbox: list[tuple[str, str]] = []
    cleo = CleoEngine(
        session, tenant, runner=runner, send_whatsapp=lambda p, t: outbox.append((p, t))
    )

    print("=" * 70)
    print(cleo.daily_summary(TODAY))
    print("=" * 70)

    drafted = cleo.run_reminders(TODAY)
    print(f"\n✍ Cleo redactó {len(drafted)} recordatorios (estado: pending_approval):\n")
    for r in drafted:
        print(f"--- [{r.bucket} · tono {r.tone}] ---")
        print(r.message, "\n")

    print(" El dueño aprueba el primero y rechaza el resto...\n")
    cleo.approve(drafted[0])
    for r in drafted[1:]:
        cleo.reject(r)

    customer = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    cleo.send(drafted[0], customer.phone)
    print(f" Enviado por WhatsApp (simulado) a {outbox[0][0]}:")
    print(f" «{outbox[0][1][:80]}...»" if len(outbox[0][1]) > 80 else f" «{outbox[0][1]}»")
    print(f"\n Estado final del recordatorio: {drafted[0].status}")


if __name__ == "__main__":
    main()
