"""Datos de demostración de aiuda — ricos, deterministas y fácilmente desactivables.

  uv run python scripts/seed.py # siembra el dataset demo completo
  uv run python scripts/seed.py --wipe # elimina TODO lo del tenant demo
  uv run python scripts/seed.py --reset # wipe + siembra de nuevo

No llama al LLM: los textos son fijos para que sembrar sea instantáneo y gratis.
El tenant demo queda marcado con config.demo=true; --wipe borra solo eso.
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from aiuda_core.db import create_all, session_scope
from aiuda_core.models import (
    Conversation,
    Customer,
    Invoice,
    Message,
    PaymentPromise,
    Reminder,
    Tenant,
    UsageEvent,
)

TODAY = date.today()


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


def dt(d: date, hour: int = 10) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


# (nombre, teléfono) — negocios mexicanos típicos de la cartera de una PyME
CUSTOMERS = [
    ("Abarrotes Don Pepe", "5215511111111"),
    ("Ferretería El Martillo", "5215522222222"),
    ("Estética Rosy", "5215533333333"),
    ("Constructora GAMA", "5215544444444"),
    ("Refaccionaria López e Hijos", "5215555555501"),
    ("Panadería La Espiga Dorada", "5215555555502"),
    ("Clínica Dental Sonrisa", "5215555555503"),
    ("Transportes Aguilar", "5215555555504"),
    ("Papelería El Estudiante", "5215555555505"),
    ("Restaurante Mar y Tierra", "5215555555506"),
    ("Uniformes Industriales del Norte", "5215555555507"),
    ("Vidriería Cristal Azul", "5215555555508"),
]

# (folio, cliente_idx, monto, emitida hace, vence en (rel. a hoy), estatus, pagada hace)
INVOICES = [
    # --- abiertas: por vencer ---
    ("F-201", 4, 7800.00, -10, 20, "open", None),
    # pedidos de la tienda en línea (entran por sync de Shopify)
    ("#1042", 9, 1450.00, 0, 0, "open", None),
    ("#1043", 6, 3890.00, -1, -1, "open", None),
    ("F-202", 5, 2340.50, -5, 25, "open", None),
    ("F-203", 6, 15600.00, -12, 18, "open", None),
    ("F-204", 9, 4980.00, -8, 22, "open", None),
    # --- abiertas: vencen pronto (0-3 días) ---
    ("F-205", 7, 22400.00, -28, 2, "open", None),
    ("F-206", 8, 1150.00, -29, 1, "open", None),
    # --- abiertas: vencidas 1-15 días ---
    ("F-102", 1, 18750.50, -39, -9, "open", None),
    ("F-207", 10, 9870.00, -34, -4, "open", None),
    ("F-208", 11, 3420.00, -42, -12, "open", None),
    ("F-209", 5, 6750.00, -44, -14, "open", None),
    # --- abiertas: vencidas 16-45 días ---
    ("F-100", 0, 4500.00, -70, -40, "open", None),
    ("F-210", 7, 31200.00, -55, -25, "open", None),
    ("F-211", 9, 2890.00, -48, -18, "open", None),
    # --- abiertas: críticas ---
    ("F-104", 3, 95000.00, -100, -70, "open", None),
    ("F-212", 10, 12500.00, -90, -60, "open", None),
    # --- pagadas este mes (con recordatorio enviado → alimentan "$ recuperado") ---
    ("F-103", 2, 860.00, -38, -8, "paid", 4),
    ("F-213", 4, 18200.00, -40, -10, "paid", 6),
    ("F-214", 6, 7450.00, -45, -15, "paid", 2),
    ("F-215", 8, 12980.00, -50, -20, "paid", 9),
    ("F-216", 11, 8730.00, -36, -6, "paid", 1),
    # --- pagadas a tiempo (sin recordatorio, no cuentan en la métrica) ---
    ("F-217", 0, 5400.00, -60, -30, "paid", 31),
    ("F-218", 1, 3200.00, -58, -28, "paid", 29),
]

# Recordatorios pendientes de aprobación (folio, tono, mensaje)
PENDING = [
    (
        "F-104",
        "critica",
        "urgente_escalado",
        "Estimado equipo de Constructora GAMA:\n\nLe contactamos de parte de Taquería La "
        "Bonita en relación con la factura F-104 por $95,000.00 MXN, vencida hace 70 días.\n\n"
        "Dado el tiempo transcurrido, el asunto ha sido escalado y el responsable del negocio "
        "se pondrá en contacto con usted personalmente en los próximos días.\n\nAgradecemos su "
        "atención.\n\nTaquería La Bonita",
    ),
    (
        "F-102",
        "vencida_reciente",
        "amable_directo",
        "Buen día, equipo de Ferretería El Martillo \n\nLe escribimos de Taquería La Bonita. "
        "La factura *F-102* por *$18,750.50 MXN* venció hace 9 días y aún no registramos el "
        "pago. Si ya lo realizó, ¿nos comparte su comprobante? Si no, le agradecemos liquidarla "
        "a la brevedad.\n\n¡Gracias!",
    ),
    (
        "F-210",
        "vencida",
        "firme",
        "Estimado equipo de Transportes Aguilar:\n\nLa factura F-210 por $31,200.00 MXN "
        "presenta 25 días de atraso. Le pedimos nos confirme una fecha concreta de pago esta "
        "semana para evitar que la cuenta pase a un proceso de gestión mayor.\n\nQuedamos al "
        "pendiente.\n\nTaquería La Bonita",
    ),
    (
        "F-206",
        "vence_pronto",
        "amable",
        "Hola, equipo de Papelería El Estudiante \n\nSolo para recordarles que su factura "
        "F-206 por $1,150.00 MXN vence mañana. Cualquier duda con los datos de depósito, aquí "
        "estamos.\n\n¡Gracias por su preferencia!\nTaquería La Bonita",
    ),
]

# Conversaciones: (cliente_idx, [(direction, texto, hace_días, hora)])
CONVERSATIONS = [
    (
        2,
        [
            ("out", "Hola, le recordamos que su factura F-103 por $860.00 venció hace unos días. ¿Nos ayuda con el pago? ", 6, 9),
            ("in", "uy si perdón, esta semana sin falta", 6, 11),
            ("out", "¡No se preocupe! Registro su promesa para esta semana. Le mando los datos de depósito por si los necesita.", 6, 11),
            ("in", "ya quedó, le mandé el comprobante al correo", 4, 17),
            ("out", "¡Recibido! Su pago quedó registrado. Muchas gracias ", 4, 17),
        ],
    ),
    (
        1,
        [
            ("out", "Buen día La factura F-102 por $18,750.50 venció el mes pasado. ¿Cómo vamos con el pago?", 3, 10),
            ("in", "dejame checar con contabilidad y te digo", 3, 13),
            ("in", "te deposito el viernes sin falta", 2, 12),
            ("out", "Perfecto, registro su promesa de pago para el viernes. ¡Gracias!", 2, 12),
        ],
    ),
    (
        7,
        [
            ("out", "Estimado equipo de Transportes Aguilar, la factura F-210 por $31,200.00 lleva 25 días de atraso. ¿Podemos acordar una fecha de pago?", 5, 9),
            ("in", "estamos esperando un pago de un cliente, nos das chance a la otra semana?", 5, 14),
            ("out", "Entiendo. Registro su promesa para el lunes próximo. Si necesitan factura con complemento de pago, avísenme.", 5, 14),
        ],
    ),
    (
        4,
        [
            ("in", "oye ya te pagué la F-213 desde el martes, checa porfa", 6, 16),
            ("out", "¡Tiene razón! Ya lo veo reflejado. Factura F-213 marcada como pagada. Disculpe la molestia y gracias ", 6, 16),
        ],
    ),
    (
        9,
        [
            ("out", "Hola Su factura F-207 por $9,870.00 venció hace 4 días. ¿Nos apoya con el pago o nos avisa si ya lo realizó?", 1, 10),
            ("in", "quien eres?", 1, 10),
            ("out", "Soy Mariana, asistente de cobranza de Taquería La Bonita Le escribo de su parte sobre la factura F-207. ¿Le comparto los datos de depósito?", 1, 10),
            ("in", "ah ok, si pasamelos", 1, 11),
            ("out", "Buenas tardes, le atiende José, el dueño ‍ Con gusto: CLABE 012345678901234567, a nombre de Taquería La Bonita. Cualquier cosa aquí ando.", 1, 12, "human"),
        ],
    ),
    (
        5,
        [
            ("out", "Buen día Le recordamos que la factura F-209 por $6,750.00 lleva 14 días vencida. ¿Nos ayuda con el pago?", 2, 10),
            ("in", "esa ya la pagué la semana pasada eh", 2, 11),
            ("out", "¡Gracias por avisar! Registré su reporte de pago de la F-209 — queda pendiente de verificarse en cuanto se refleje en el banco. En cuanto se confirme le aviso ", 2, 11),
        ],
    ),
]

# Facturas que vienen del Odoo del negocio (fuente de registro → verificadas)
ODOO_FOLIOS = {"F-201", "F-203", "F-205", "F-102", "F-104", "F-213"}
# El cliente reporta haber pagado — pendiente de verificación (fact-check)
REPORTED_FOLIOS = {"F-209"}
# Pedidos que entraron por la integración de Shopify
SHOPIFY_FOLIOS = {"#1042", "#1043"}

# Promesas activas: (folio, en cuántos días prometió, nota)
PROMISES = [
    ("F-102", 2, "Ferretería El Martillo prometió depositar el viernes"),
    ("F-210", 5, "Transportes Aguilar pidió hasta el lunes próximo"),
    ("F-208", -2, "Vidriería Cristal Azul prometió pagar y no se ha reflejado"),
]

# Promesas cumplidas (historial): (folio, prometió hace, se cumplió hace, nota)
FULFILLED_PROMISES = [
    ("F-103", 7, 4, "Estética Rosy prometió pagar esta semana — cumplió"),
    ("F-213", 9, 6, "Refaccionaria López avisó que ya había pagado — confirmado"),
]

# Uso de IA del mes: (modelo, tarea, eventos, in_tokens c/u, out_tokens c/u)
USAGE = [
    ("claude-haiku-4-5", "clasificar_respuesta", 46, 410, 12),
    ("claude-sonnet-4-6", "redactar_recordatorio", 21, 580, 170),
    ("claude-sonnet-4-6", "conversacion_deudor", 14, 1240, 210),
]


def wipe(session) -> int:
    tenants = session.scalars(select(Tenant)).all()
    removed = 0
    for tenant in tenants:
        is_demo = (tenant.config or {}).get("demo") or tenant.evolution_instance == "demo"
        if not is_demo:
            continue
        for model in (UsageEvent, Message, Conversation, PaymentPromise, Reminder, Invoice, Customer):
            session.execute(delete(model).where(model.tenant_id == tenant.id))
        session.delete(tenant)
        removed += 1
    return removed


def seed(session) -> None:
    existing = session.scalar(select(Tenant).where(Tenant.evolution_instance == "demo"))
    if existing is not None:
        print("Ya hay un tenant demo. Usa --reset para regenerarlo.")
        return

    tenant = Tenant(
        name="Taquería La Bonita",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={
            "api_key": "k-demo",
            "demo": True,
            "members": [
                {"name": "Demo aiuda", "email": "demo@aiuda.mx", "role": "dueño", "status": "activo"},
            ],
            # La consola es modular: el demo arranca con 2 agentes en el equipo
            "active_agents": ["mariana", "carlos"],
            "agent_config": {
                "mariana": {
                    "user_rules": [
                        "A Constructora GAMA siempre tratarla de usted: es nuestro cliente más grande.",
                        "Si preguntan cómo pagar, ofrece transferencia o depósito en OXXO.",
                    ]
                }
            },
        },
    )
    session.add(tenant)
    session.flush()

    customers = []
    for name, phone in CUSTOMERS:
        c = Customer(tenant_id=tenant.id, name=name, phone=phone)
        session.add(c)
        customers.append(c)
    session.flush()

    invoices: dict[str, Invoice] = {}
    for folio, idx, amount, issued, due, status, paid_ago in INVOICES:
        from_odoo = folio in ODOO_FOLIOS
        from_shopify = folio in SHOPIFY_FOLIOS
        source = "odoo" if from_odoo else "shopify" if from_shopify else "excel"
        inv = Invoice(
            tenant_id=tenant.id,
            customer_id=customers[idx].id,
            folio=folio,
            amount=amount,
            issued_date=days(issued),
            due_date=days(due),
            status=status,
            paid_at=dt(days(-paid_ago)) if paid_ago is not None else None,
            source=source,
            presence={source: {"ref": folio}},
            verified="verificada" if (from_odoo or from_shopify) else "sin_verificar",
            payment_reported=folio in REPORTED_FOLIOS,
            paid_source=("odoo" if from_odoo else "manual") if status == "paid" else None,
        )
        session.add(inv)
        invoices[folio] = inv
    session.flush()

    # Recordatorios enviados sobre las facturas pagadas este mes (→ "$ recuperado")
    for folio in ("F-103", "F-213", "F-214", "F-215", "F-216"):
        inv = invoices[folio]
        session.add(
            Reminder(
                tenant_id=tenant.id,
                invoice_id=inv.id,
                bucket="vencida_reciente",
                tone="amable_directo",
                message=f"Recordatorio enviado sobre la factura {folio}.",
                status="sent",
                sent_at=inv.paid_at - timedelta(days=2),
            )
        )
    # Enviados sobre facturas aún abiertas (historial)
    for folio, bucket, tone in (
        ("F-207", "vencida_reciente", "amable_directo"),
        ("F-209", "vencida_reciente", "amable_directo"),
        ("F-211", "vencida", "firme"),
    ):
        session.add(
            Reminder(
                tenant_id=tenant.id,
                invoice_id=invoices[folio].id,
                bucket=bucket,
                tone=tone,
                message=f"Recordatorio enviado sobre la factura {folio}.",
                status="sent",
                sent_at=dt(days(-3), 9),
            )
        )
    # Uno rechazado (el dueño no quiso presionar a este cliente)
    session.add(
        Reminder(
            tenant_id=tenant.id,
            invoice_id=invoices["F-212"].id,
            bucket="critica",
            tone="urgente_escalado",
            message="Borrador rechazado: el dueño prefirió llamar personalmente.",
            status="rejected",
        )
    )
    # Pendientes de aprobación (Mariana)
    for folio, bucket, tone, message in PENDING:
        session.add(
            Reminder(
                tenant_id=tenant.id,
                agent="mariana",
                invoice_id=invoices[folio].id,
                bucket=bucket,
                tone=tone,
                message=message,
                status="pending_approval",
            )
        )

    # Pendientes de aprobación (Carlos · ventas): la bandeja es del equipo completo
    for title, phone, message in [
        (
            "Cotización · 120 órdenes para evento de empresa",
            "5215599887766",
            "¡Hola! Gracias por escribirnos Para su evento del sábado le cotizo:\n\n"
            "• 120 órdenes de tacos (pastor, bistec, suadero) — $7,800.00\n"
            "• Salsas, cebollitas y tortilla hecha a mano incluidas\n"
            "• Entrega e instalación en Polanco — $450.00\n\n"
            "*Total: $8,250.00 MXN* (IVA incluido, con factura)\n\n"
            "Apartamos su fecha con el 30% de anticipo. ¿Se la confirmo?",
        ),
        (
            "Cotización · servicio de taquiza mensual para oficina",
            "5215588776655",
            "¡Buen día! Le preparé la propuesta para la taquiza mensual de su oficina:\n\n"
            "• 60 personas, un viernes al mes — $4,900.00 por evento\n"
            "• Menú rotativo y opción vegetariana\n"
            "• Precio fijo por 6 meses con contrato\n\n"
            "Si le funciona, le mando el calendario propuesto. ¿Cómo ve?",
        ),
    ]:
        session.add(
            Reminder(
                tenant_id=tenant.id,
                agent="carlos",
                invoice_id=None,
                title=title,
                recipient_phone=phone,
                bucket="cotizacion",
                tone="comercial",
                message=message,
                status="pending_approval",
            )
        )
    # Una cotización ya enviada (historial de Carlos)
    session.add(
        Reminder(
            tenant_id=tenant.id,
            agent="carlos",
            invoice_id=None,
            title="Cotización · 40 órdenes para posada",
            recipient_phone="5215577665544",
            bucket="cotizacion",
            tone="comercial",
            message="Cotización enviada: 40 órdenes para su posada — $2,950.00 MXN.",
            status="sent",
            sent_at=dt(days(-2), 13),
        )
    )

    for folio, in_days, note in PROMISES:
        session.add(
            PaymentPromise(
                tenant_id=tenant.id,
                invoice_id=invoices[folio].id,
                promised_date=days(in_days),
                note=note,
            )
        )
    for folio, promised_ago, fulfilled_ago, note in FULFILLED_PROMISES:
        session.add(
            PaymentPromise(
                tenant_id=tenant.id,
                invoice_id=invoices[folio].id,
                promised_date=days(-promised_ago),
                note=note,
                fulfilled=True,
                fulfilled_at=dt(days(-fulfilled_ago), 12),
            )
        )

    for idx, thread in CONVERSATIONS:
        conv = Conversation(tenant_id=tenant.id, remote_phone=customers[idx].phone)
        session.add(conv)
        session.flush()
        for entry in thread:
            direction, body, ago, hour = entry[:4]
            author = entry[4] if len(entry) > 4 else "agent"
            session.add(
                Message(
                    tenant_id=tenant.id,
                    conversation_id=conv.id,
                    direction=direction,
                    author=author,
                    body=body,
                    created_at=dt(days(-ago), hour),
                )
            )

    for model, task, events, in_tokens, out_tokens in USAGE:
        for i in range(events):
            session.add(
                UsageEvent(
                    tenant_id=tenant.id,
                    model=model,
                    task=task,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    created_at=dt(days(-(i % 28)), 9 + (i % 8)),
                )
            )

    # Presencia multi-sistema de demo: la F-102 vive en Odoo y en el Excel
    invoices["F-102"].presence = {"odoo": {"ref": "F-102"}, "excel": {"ref": "F-102"}}

    # Workspace real #1: Hanova Consulting. Arranca vacío para importar su cartera.
    hanova = Tenant(
        name="Hanova Consulting",
        owner_phone="5215500000000",
        evolution_instance="hanova",
        config={
            "active_agents": ["mariana"],
            "members": [
                {
                    "name": "José González",
                    "email": "consulting@hanova.mx",
                    "role": "dueño",
                    "status": "invitado",
                },
            ],
        },
    )
    session.add(hanova)
    session.flush()

    print(f"Tenant demo: {tenant.name} (API key: k-demo)")
    print(f" {len(CUSTOMERS)} clientes · {len(INVOICES)} facturas · {len(PENDING)} por aprobar")
    print(f" {len(CONVERSATIONS)} conversaciones · {len(PROMISES)} promesas · uso de IA del mes")
    print(f"Workspace real: {hanova.name} (vacío; importa tu cartera desde la consola)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Siembra o limpia los datos demo de aiuda")
    parser.add_argument("--wipe", action="store_true", help="elimina los datos demo y termina")
    parser.add_argument("--reset", action="store_true", help="elimina y vuelve a sembrar")
    args = parser.parse_args()

    create_all()
    with session_scope() as session:
        if args.wipe or args.reset:
            removed = wipe(session)
            print(f" Tenants demo eliminados: {removed}")
            if args.wipe:
                return
        seed(session)


if __name__ == "__main__":
    main()
