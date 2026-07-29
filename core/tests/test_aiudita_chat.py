"""El chat de un ayudante se arma desde sus aiuditas activas (capability-first)."""

import pytest

from aiuda_core.aiuditas.chat import (
    AyudanteChatExecutor,
    chat_system_prompt,
    chat_tools,
)


def test_chat_tools_solo_lectura(session, tenant):
    # Activa una de lectura (consultar_cartera) y una de escritura (redactar): solo
    # la de lectura es herramienta de chat; las escrituras no entran al chat.
    activos = ["cobranza.consultar_cartera", "cobranza.redactar_recordatorio"]
    tools = chat_tools(activos)
    assert [t["name"] for t in tools] == ["consultar_cartera"]


def test_executor_despacha_a_la_capacidad_real(session, tenant, customer, invoice):
    ex = AyudanteChatExecutor(session, tenant, ["cobranza.consultar_cartera"])
    assert ex.has_tools
    salida = ex("consultar_cartera", {})
    assert "F-001" in salida  # consultó la cartera real, no la inventó


def test_executor_combina_perfiles(session, tenant):
    # Un ayudante con aiuditas de cobranza + ventas despacha ambas con un solo ejecutor.
    ex = AyudanteChatExecutor(
        session, tenant, ["cobranza.consultar_cartera", "ventas.consultar_catalogo"]
    )
    assert "Sin facturas" in ex("consultar_cartera", {})  # sin invoice fixture: vacío, pero responde
    assert ex("consultar_catalogo", {}) is not None


def test_executor_rechaza_tool_no_activa(session, tenant):
    ex = AyudanteChatExecutor(session, tenant, ["cobranza.consultar_cartera"])
    with pytest.raises(ValueError):
        ex("consultar_catalogo", {})  # no la activó este ayudante


def test_persona_incluye_capacidades_y_reglas(session, tenant):
    activos = {
        "cobranza.consultar_cartera": {},
        "cobranza.redactar_recordatorio": {"reglas": "No menciones recargos."},
    }
    system = chat_system_prompt("abi", tenant.name, activos)
    assert "abi" in system
    assert "Consultar cartera" in system  # describe lo que sabe hacer
    assert "No menciones recargos." in system  # respeta las reglas del dueño
    assert "markdown" in system  # mantiene la regla dura de salida


def test_instrucciones_van_bajo_la_base_de_seguridad(session, tenant):
    instr = "Trata al cliente de tú y usa un tono muy relajado."
    system = chat_system_prompt("abi", tenant.name, {}, instructions=instr)
    assert instr in system
    # Las instrucciones del dueño aparecen DESPUÉS de la regla inquebrantable de no-autoenvío:
    # agregan, no reemplazan (la base de seguridad manda).
    assert system.index("nunca envías mensajes a clientes") < system.index(instr)


def test_instrucciones_vacias_no_ensucian_el_prompt(session, tenant):
    base = chat_system_prompt("abi", tenant.name, {})
    assert chat_system_prompt("abi", tenant.name, {}, instructions="   ") == base
    assert chat_system_prompt("abi", tenant.name, {}, instructions=None) == base
