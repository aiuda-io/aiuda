"""Motor genérico de aiudantes: registro + herramientas de chat (solo lectura)."""

from datetime import date, datetime

from aiuda_core.agents.carlos.tools import CarlosToolExecutor
from aiuda_core.agents.cleo.tools import CLEO_CHAT_TOOLS
from aiuda_core.agents.diego.tools import DiegoToolExecutor
from aiuda_core.agents.valeria.tools import ValeriaToolExecutor
from aiuda_core.aiuditas.chat import PERSONA_PERFIL, chat_aiuditas_de_perfil, chat_tools
from aiuda_core.models import Appointment, Customer, Invoice, Payment, Product


def test_personas_mapean_a_aiuditas_de_chat():
    """Capability-first: el chat por rol resuelve a las aiuditas de chat de su perfil
    (solo lectura); un rol sin ejecutor de chat no tiene herramientas."""
    assert chat_aiuditas_de_perfil("cobranza") == ["cobranza.consultar_cartera"]
    assert "ventas.consultar_catalogo" in chat_aiuditas_de_perfil("ventas")
    assert chat_aiuditas_de_perfil("conciliacion") == ["conciliacion.consultar_pagos"]
    assert chat_aiuditas_de_perfil("contenido") == []  # sin ejecutor todavía
    assert chat_tools(["contenido.redactar_post"]) == []
    # El puente de persona solo cubre los 4 roles con motor real.
    assert set(PERSONA_PERFIL) == {"mariana", "carlos", "valeria", "diego"}


def test_valeria_consulta_agenda(session, tenant):
    hoy = date(2026, 6, 15)
    session.add_all(
        [
            Appointment(
                tenant_id=tenant.id, title="Valuación de pieza", customer_name="Ana Ruiz",
                starts_at=datetime(2026, 6, 16, 11, 0),
            ),
            Appointment(
                tenant_id=tenant.id, title="Entrega de anillo", customer_name="Luis Roca",
                starts_at=datetime(2026, 6, 20, 17, 30),
            ),
            Appointment(
                tenant_id=tenant.id, title="Cita lejana", customer_name="Z",
                starts_at=datetime(2026, 8, 1, 9, 0),
            ),
        ]
    )
    session.flush()
    valeria = ValeriaToolExecutor(session, tenant, today=hoy)

    proximas = valeria("consultar_agenda", {"dias": 7})
    assert "Valuación de pieza" in proximas and "Ana Ruiz" in proximas
    assert "Cita lejana" not in proximas  # fuera de la ventana de 7 días

    res = valeria("buscar_cita", {"busqueda": "anillo"})
    assert "Entrega de anillo" in res and "Valuación" not in res

    assert "Sin citas" in valeria("buscar_cita", {"busqueda": "nada"})


def test_chat_de_mariana_es_solo_lectura():
    """En el chat Mariana solo consulta; las escrituras quedan fuera del chat."""
    nombres = {t["name"] for t in CLEO_CHAT_TOOLS}
    assert nombres == {"consultar_cartera"}
    assert "registrar_pago" not in nombres


def test_carlos_consulta_catalogo(session, tenant):
    session.add_all(
        [
            Product(tenant_id=tenant.id, name="Anillo oro 14k", sku="AN-014", price=8900, stock=4, unit="pza"),
            Product(tenant_id=tenant.id, name="Pulsera plata", sku="PL-220", price=1450, stock=12, unit="pza"),
        ]
    )
    session.flush()
    carlos = CarlosToolExecutor(session, tenant)

    todo = carlos("consultar_catalogo", {})
    assert "Anillo oro 14k" in todo and "Pulsera plata" in todo
    assert "$8,900.00" in todo

    filtrado = carlos("consultar_catalogo", {"busqueda": "pulsera"})
    assert "Pulsera plata" in filtrado and "Anillo oro 14k" not in filtrado

    vacio = carlos("consultar_catalogo", {"busqueda": "reloj"})
    assert "Sin productos" in vacio


def test_carlos_consulta_cliente_con_saldo(session, tenant):
    c = Customer(tenant_id=tenant.id, name="Joyería Aurora", phone="5215511112222")
    session.add(c)
    session.flush()
    session.add_all(
        [
            Invoice(tenant_id=tenant.id, customer_id=c.id, folio="F-1", amount=500,
                    issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open"),
            Invoice(tenant_id=tenant.id, customer_id=c.id, folio="F-2", amount=1500,
                    issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="open"),
            Invoice(tenant_id=tenant.id, customer_id=c.id, folio="F-3", amount=9999,
                    issued_date=date(2026, 5, 1), due_date=date(2026, 5, 31), status="paid"),
        ]
    )
    session.flush()
    carlos = CarlosToolExecutor(session, tenant)

    res = carlos("consultar_cliente", {"busqueda": "Aurora"})
    assert "Joyería Aurora" in res
    assert "$2,000.00" in res  # solo facturas abiertas, la pagada no cuenta
    assert "(cliente)" in res

    assert "Sin clientes" in carlos("consultar_cliente", {"busqueda": "Nadie"})


def test_executor_rechaza_tool_desconocido(session, tenant):
    carlos = CarlosToolExecutor(session, tenant)
    try:
        carlos("borrar_todo", {})
        assert False, "debió rechazar tool desconocido"
    except ValueError as exc:
        assert "desconocido" in str(exc)


def test_diego_consulta_pagos_con_match_propuesto(session, tenant):
    """Diego lee los depósitos pendientes y PROPONE la factura candidata con su razón;
    conciliar (confirmar) queda en manos del humano — el tool solo consulta."""
    c = Customer(tenant_id=tenant.id, name="Papelería Roma", phone="5215533334444")
    session.add(c)
    session.flush()
    session.add(
        Invoice(tenant_id=tenant.id, customer_id=c.id, folio="F-88", amount=3200,
                issued_date=date(2026, 6, 1), due_date=date(2026, 6, 30), status="open")
    )
    session.add(
        Payment(tenant_id=tenant.id, amount=3200, paid_at=date(2026, 7, 1),
                source="banco", counterparty="PAPELERIA ROMA SA")
    )
    session.flush()
    diego = DiegoToolExecutor(session, tenant)

    res = diego("consultar_pagos", {})
    assert "$3,200.00" in res
    assert "F-88" in res and "Papelería Roma" in res  # la candidata propuesta
    assert "confirme" in res  # deja claro que falta el humano

    # La factura sigue ABIERTA: consultar jamás concilia.
    from sqlalchemy import select

    inv = session.scalars(select(Invoice)).first()
    assert inv.status == "open"


def test_diego_sin_pagos_pendientes(session, tenant):
    diego = DiegoToolExecutor(session, tenant)
    assert "No hay pagos pendientes" in diego("consultar_pagos", {})
