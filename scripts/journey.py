#!/usr/bin/env python
"""El journey completo de aiuda, de punta a punta, con datos reales y assertions.

Prueba lo que promete el README, en orden y sin fingir nada:

  1. Conecta una fuente        Odoo local por XML-RPC, credencial CIFRADA.
  2. Sincroniza                la cartera entra CON PROCEDENCIA (source + presence).
  3. Crea tu ayudante          nombre libre y sus aiuditas.
  4. Conecta tu IA             el CLI que ya tienes; aiuda no guarda ningún token.
  5. Corre                     redacta y deja las propuestas en la bandeja.
  6. Aprueba                   la máquina de estados HITL, no un flag.
  7. Cobra                     el envío se RETIENE por modo sombra.

Nada sale a un cliente real: el modo sombra queda encendido de principio a fin y el
script falla si detecta que algo se envió.

Necesita el Odoo de pruebas arriba:

    cd ../odoo-local && docker compose up -d

Uso:

    uv run python scripts/journey.py                # con tu IA (gasta)
    uv run python scripts/journey.py --sin-ia       # sin llamar al modelo
    uv run python scripts/journey.py --tope 3       # cuántos borradores redactar

La base va a un archivo temporal: no toca tu ~/.aiuda.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import tempfile
from pathlib import Path

ODOO = {
    "url": os.environ.get("JOURNEY_ODOO_URL", "http://localhost:8069"),
    "db": os.environ.get("JOURNEY_ODOO_DB", "hanova_facturas"),
    "username": os.environ.get("JOURNEY_ODOO_USER", "admin"),
    "api_key": os.environ.get("JOURNEY_ODOO_PASS", "dF7qjSPGey05OCui"),
}

_paso = 0
_fallos: list[str] = []


def paso(titulo: str) -> None:
    global _paso
    _paso += 1
    print(f"\n\033[1m{_paso}. {titulo}\033[0m")


def ok(msg: str) -> None:
    print(f"   \033[32mok\033[0m  {msg}")


def revisar(condicion: bool, msg: str) -> None:
    if condicion:
        ok(msg)
    else:
        print(f"   \033[31mFALLA\033[0m  {msg}")
        _fallos.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description="El journey completo de aiuda.")
    ap.add_argument("--sin-ia", action="store_true", help="no llama al modelo")
    ap.add_argument("--tope", type=int, default=3, help="borradores por corrida")
    ap.add_argument("--db", default="", help="ruta de la base (por defecto, temporal)")
    args = ap.parse_args()

    destino = args.db or str(Path(tempfile.mkdtemp(prefix="aiuda-journey-")) / "journey.db")
    os.environ["AIUDA_DATABASE_URL"] = f"sqlite:///{destino}"
    print(f"base de la prueba: {destino}")

    from sqlalchemy import func, select

    from aiuda_core.connectors import credentials as cred
    from aiuda_core.db import create_all, get_sessionmaker
    from aiuda_core.engine.approval import InvalidTransition, advance
    from aiuda_core.engine.engine import CleoEngine, ShadowHold
    from aiuda_core.engine.provider import resolve_credential
    from aiuda_core.engine.sync import sync_fuentes
    from aiuda_core.models import Ayudante, Customer, Invoice, Reminder, Tenant

    create_all()
    db = get_sessionmaker()()

    # ---------------------------------------------------------------- 1
    paso("Conecta una fuente: tu Odoo")
    tenant = Tenant(
        name="Hanova Consulting",
        owner_phone="5218112345678",
        evolution_instance=f"journey-{os.getpid()}",
        # Modo sombra desde el minuto cero: nada sale a un cliente real.
        config={"modo_sombra": True, "max_borradores_corrida": args.tope},
    )
    db.add(tenant)
    db.flush()
    cred.set_credential(db, tenant.id, "odoo", ODOO)
    db.commit()

    fila = cred.get_credential(db, tenant.id, "odoo")
    revisar(fila is not None and fila["url"] == ODOO["url"], "la credencial se lee de vuelta")
    revisar(
        ODOO["api_key"] not in str(tenant.config),
        "la contraseña NO quedó en claro en tenant.config",
    )

    # ---------------------------------------------------------------- 2
    paso("Sincroniza: la cartera entra con procedencia")
    try:
        rep = sync_fuentes(db, tenant)
    except Exception as exc:
        print(f"   \033[31mno se pudo hablar con Odoo:\033[0m {exc}")
        print("   ¿está arriba?  cd ../odoo-local && docker compose up -d")
        return 2
    db.commit()

    abiertas = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant.id, Invoice.status == "open"
        )
    )
    clientes = db.scalar(
        select(func.count(Customer.id)).where(Customer.tenant_id == tenant.id)
    )
    revisar(abiertas > 0, f"{abiertas} facturas abiertas desde Odoo")
    revisar(clientes > 0, f"{clientes} clientes en el directorio")
    revisar("odoo" in rep.fuentes, f"la fuente quedó registrada: {rep.fuentes}")

    muestra = db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant.id, Invoice.status == "open").limit(1)
    ).first()
    revisar(muestra.source == "odoo", "cada factura sabe de qué fuente vino")
    marca = (muestra.presence or {}).get("odoo") or {}
    revisar(bool(marca.get("ref")), f"y con qué folio vive allá: {marca.get('ref')}")
    revisar(
        str(marca.get("url", "")).startswith("http"),
        "y con liga para abrirla en su sistema",
    )

    # ---------------------------------------------------------------- 3
    paso("Crea tu ayudante")
    ayudante = Ayudante(
        tenant_id=tenant.id,
        name="Male",
        appearance={"color": "#714B67"},
        instructions="Hablas directo y breve, sin adornos.",
        aiuditas={
            "cobranza.consultar_cartera": {"_fuente": "odoo"},
            "cobranza.redactar_recordatorio": {"_fuente": "odoo", "tono_base": "amable"},
        },
    )
    db.add(ayudante)
    db.commit()
    ok(f"{ayudante.name}, con {len(ayudante.aiuditas)} aiuditas")

    # ---------------------------------------------------------------- 4
    paso("Conecta tu IA: la que ya tienes instalada")
    cred.set_credential(db, tenant.id, "ia", {"name": "claude_cli", "mode": "cli", "secret": ""})
    db.commit()
    c = resolve_credential(tenant.config, session=db, tenant_id=tenant.id)
    revisar(c is not None and c.name == "claude_cli", f"proveedor: {c.name if c else None}")
    revisar(
        c is not None and not c.secret,
        "aiuda NO guarda token: el binario se autentica con la sesión del dueño",
    )

    if args.sin_ia:
        print("\n   (--sin-ia: se salta la redacción y todo lo que depende de ella)")
        return _cerrar(db)

    # ---------------------------------------------------------------- 5
    paso("Corre: redacta y deja las propuestas en tu bandeja")
    motor = CleoEngine(db, tenant, ayudante_id=ayudante.id)
    propuestas = motor.run_reminders(datetime.date.today())
    db.commit()
    revisar(len(propuestas) > 0, f"{len(propuestas)} propuestas redactadas")
    revisar(
        len(propuestas) <= args.tope,
        f"respetó el tope de {args.tope} por corrida",
    )

    r = propuestas[0]
    revisar(r.status == "pending_approval", "esperan tu visto bueno, no salieron solas")
    revisar(
        (r.meta or {}).get("ayudante_id") == ayudante.id,
        "cada propuesta dice qué ayudante la redactó",
    )
    revisar(bool(r.bucket and r.tone), f"con su antigüedad y su tono: {r.bucket} / {r.tone}")
    factura = db.get(Invoice, r.invoice_id) if r.invoice_id else None
    revisar(factura is not None, "y con la factura concreta que la origina")
    if factura is not None:
        revisar(
            factura.folio in r.message,
            f"el mensaje cita el folio real ({factura.folio}), no uno inventado",
        )

    # ---------------------------------------------------------------- 6
    paso("Aprueba: la máquina de estados, no un flag")
    try:
        advance(r, "sent")
        revisar(False, "pending_approval -> sent debería estar prohibido")
    except InvalidTransition:
        ok("no se puede saltar de propuesta a enviado")
    advance(r, "approved")
    db.flush()
    revisar(r.status == "approved" and r.sent_at is None, "aprobado, todavía sin enviar")

    # ---------------------------------------------------------------- 7
    paso("Cobra: y el modo sombra retiene")
    try:
        motor.send(r, "5215500000000")
        revisar(False, "SE ENVIÓ con modo sombra encendido")
    except ShadowHold:
        ok("el envío se retuvo: en modo sombra nada llega a un cliente")
    revisar(r.sent_at is None, "sent_at sigue vacío: no salió nada")

    enviados = db.scalar(
        select(func.count(Reminder.id)).where(
            Reminder.tenant_id == tenant.id, Reminder.sent_at.isnot(None)
        )
    )
    revisar(enviados == 0, "cero mensajes enviados en toda la corrida")

    return _cerrar(db)


def _cerrar(db) -> int:
    db.rollback()
    print()
    if _fallos:
        print(f"\033[31m{len(_fallos)} fallas:\033[0m")
        for f in _fallos:
            print(f"  - {f}")
        return 1
    print("\033[32mEl journey completo corre de punta a punta.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
