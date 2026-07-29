"""Opt-out (BAJA/STOP) y no-molestar por tenant.

- El módulo optout: detección de la frase, registro/consulta/limpieza por match_key.
- El engine: send() respeta el opt-out (OptedOut) y la ventana global del negocio
  (Tenant.config["ventana_envio"]) cuando la aiudita no configuró la suya; y
  run_reminders no redacta cobranza para clientes dados de baja.
"""

from datetime import date, time

import pytest

from aiuda_core.engine.engine import CleoEngine, OutsideSendWindow
from aiuda_core.models import Reminder
from aiuda_core.optout import (
    OPT_OUT_CONFIRMATION,
    OptedOut,
    clear_opt_out,
    is_opt_out,
    mark_opt_out,
    opted_out,
)
from conftest import FakeResponse

TODAY = date(2026, 6, 9)


# ---------- detección de la frase ----------

@pytest.mark.parametrize(
    "body",
    ["BAJA", "baja", " Baja. ", "STOP", "stop", "Alto", "No molestar", "¡BAJA!",
     "ya no me manden mensajes", "No más mensajes"],
)
def test_is_opt_out_reconoce_variantes(body):
    assert is_opt_out(body)


@pytest.mark.parametrize(
    "body",
    ["no quiero darme de baja", "la baja de mi factura", "hola", "",
     "puedo pagar la próxima semana", "bajame el precio"],
)
def test_is_opt_out_no_marca_frases_que_solo_contienen_la_palabra(body):
    assert not is_opt_out(body)


# ---------- registro por match_key ----------

def test_mark_y_opted_out_cruzan_52_vs_521(tenant):
    assert mark_opt_out(tenant, "5215587654321")
    # El mismo número en formato 52 (sin el 1 móvil) sigue reconocido: match_key.
    entry = opted_out(tenant.config, "525587654321")
    assert entry is not None and entry["via"] == "whatsapp" and entry["at"]


def test_clear_opt_out_reactiva(tenant):
    mark_opt_out(tenant, "5215587654321")
    assert clear_opt_out(tenant, "55 8765 4321")
    assert opted_out(tenant.config, "5215587654321") is None
    assert not clear_opt_out(tenant, "5215587654321")  # ya no había registro


def test_mark_sin_telefono_usable_no_registra(tenant):
    assert not mark_opt_out(tenant, "123")
    assert (tenant.config or {}).get("optouts", {}) == {}


# ---------- registro por correo (la baja es POR MEDIO de contacto) ----------

def test_mark_y_opted_out_por_correo_normaliza_mayusculas(tenant):
    assert mark_opt_out(tenant, "Ana@Cliente.MX", via="correo")
    entry = opted_out(tenant.config, "ana@cliente.mx")
    assert entry is not None and entry["via"] == "correo"
    # La baja por correo NO toca el WhatsApp del mismo cliente (otra llave).
    assert opted_out(tenant.config, "5215587654321") is None


def test_clear_opt_out_por_correo(tenant):
    mark_opt_out(tenant, "ana@cliente.mx", via="correo")
    assert clear_opt_out(tenant, "ANA@cliente.mx")
    assert opted_out(tenant.config, "ana@cliente.mx") is None


def test_confirmacion_es_texto_determinista():
    assert "recordatorios" in OPT_OUT_CONFIRMATION


# ---------- engine ----------

def _engine(session, tenant, fake_client_factory, send_log):
    from aiuda_core.engine.llm import ClaudeRunner

    runner = ClaudeRunner(client=fake_client_factory(FakeResponse("hola")), usage_callback=None)
    engine = CleoEngine(
        session, tenant, runner=runner,
        send_whatsapp=lambda phone, text: send_log.append((phone, text)),
    )
    runner._usage_callback = engine._record_usage
    return engine


def _approved_reminder(session, tenant, invoice) -> Reminder:
    r = Reminder(
        tenant_id=tenant.id, invoice_id=invoice.id, bucket="vencida",
        tone="firme", message="Recordatorio", status="approved",
    )
    session.add(r)
    session.flush()
    return r


def test_send_respeta_opt_out(session, tenant, customer, invoice, fake_client_factory):
    mark_opt_out(tenant, customer.phone)
    sent: list = []
    engine = _engine(session, tenant, fake_client_factory, sent)
    reminder = _approved_reminder(session, tenant, invoice)
    with pytest.raises(OptedOut):
        engine.send(reminder, customer.phone)
    assert sent == [] and reminder.status == "approved"  # nada salió, nada se perdió


def test_opt_out_gana_sobre_modo_sombra(session, customer, invoice, fake_client_factory):
    """La baja del cliente manda incluso en sombra: la señal para el dueño es
    'este cliente pidió no recibir', no 'retenido por sombra'."""
    from aiuda_core.models import Tenant

    t = Tenant(name="S", owner_phone="5215500000001", evolution_instance="sombra-1",
               config={"modo_sombra": True})
    session.add(t)
    session.flush()
    mark_opt_out(t, customer.phone)
    engine = _engine(session, t, fake_client_factory, [])
    reminder = _approved_reminder(session, t, invoice)
    with pytest.raises(OptedOut):
        engine.send(reminder, customer.phone)


def test_run_reminders_salta_clientes_dados_de_baja(
    session, tenant, customer, invoice, fake_client_factory
):
    mark_opt_out(tenant, customer.phone)
    engine = _engine(session, tenant, fake_client_factory, [])
    assert engine.run_reminders(TODAY) == []  # ni siquiera se redacta


# ---------- ventana global del negocio (fallback de la aiudita) ----------

def test_ventana_envio_del_tenant_difiere_fuera_de_horario(
    session, tenant, customer, invoice, fake_client_factory
):
    tenant.config = {**(tenant.config or {}), "ventana_envio": "09:00-20:00"}
    sent: list = []
    engine = _engine(session, tenant, fake_client_factory, sent)
    reminder = _approved_reminder(session, tenant, invoice)
    with pytest.raises(OutsideSendWindow):
        engine.send(reminder, customer.phone, now=time(22, 30))
    assert sent == [] and reminder.status == "approved"  # espera a la ventana


def test_ventana_envio_del_tenant_envia_dentro_de_horario(
    session, tenant, customer, invoice, fake_client_factory
):
    tenant.config = {**(tenant.config or {}), "ventana_envio": "09:00-20:00"}
    sent: list = []
    engine = _engine(session, tenant, fake_client_factory, sent)
    reminder = _approved_reminder(session, tenant, invoice)
    engine.send(reminder, customer.phone, now=time(12, 0))
    assert len(sent) == 1 and reminder.status == "sent"
