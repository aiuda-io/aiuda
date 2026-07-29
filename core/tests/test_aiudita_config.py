"""La config por-ayudante (perillas de cobranza) cambia el comportamiento del motor."""

import pytest
from datetime import date, datetime, time, timedelta, timezone

from aiuda_core.engine.engine import CleoEngine, OutsideSendWindow
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Ayudante, PaymentPromise, Reminder
from conftest import FakeResponse

TODAY = date(2026, 6, 9)  # con invoice (vence 2026-05-31): bucket vencida_reciente, 9 días

# La factura de conftest es F-001 por $12,500.50, y el motor descarta el borrador
# que no las cita: un fake tiene que verse como algo que sí saldría al cliente.
RECORDATORIO = "Buen día, le recuerdo su factura F-001 por $12,500.50, ya vencida."


def make_engine(session, tenant, fake_client):
    return CleoEngine(session, tenant, runner=ClaudeRunner(client=fake_client))


def con_aiudita(session, tenant, aiudita_id: str, config: dict) -> Ayudante:
    a = Ayudante(tenant_id=tenant.id, name="abi", aiuditas={aiudita_id: config})
    session.add(a)
    session.flush()
    return a


def con_aiuditas(session, tenant, aiuditas: dict) -> Ayudante:
    a = Ayudante(tenant_id=tenant.id, name="abi", aiuditas=aiuditas)
    session.add(a)
    session.flush()
    return a


def test_tono_base_pone_piso_y_firma_y_reglas(
    session, tenant, customer, invoice, fake_client_factory
):
    con_aiudita(
        session,
        tenant,
        "cobranza.redactar_recordatorio",
        {"tono_base": "firme", "escalar_por_atraso": True, "firma": "Equipo Hanova",
         "reglas": "Nunca menciones recargos."},
    )
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    # el bucket pediría "amable_directo" (sev 2), pero el piso firme (sev 3) manda
    assert r.tone == "firme"
    assert r.message.startswith(RECORDATORIO)
    assert r.message.endswith("Equipo Hanova")  # firma anexada
    assert "Nunca menciones recargos." in fake.messages.requests[0]["system"]  # reglas al prompt


def test_escalar_apagado_usa_solo_el_tono_base(
    session, tenant, customer, invoice, fake_client_factory
):
    con_aiudita(
        session, tenant, "cobranza.redactar_recordatorio",
        {"tono_base": "amable", "escalar_por_atraso": False},
    )
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert r.tone == "amable"  # sin escalar, no sube a amable_directo


def test_autonomia_auto_bajo_umbral_aprueba_solo(
    session, tenant, customer, invoice, fake_client_factory
):
    con_aiudita(
        session, tenant, "cobranza.enviar_whatsapp",
        {"autonomia": "auto_bajo_umbral", "umbral_auto_dias": 15, "tope_critico_dias": 45,
         "cooldown_dias": 4},
    )
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert r.status == "approved"  # 9 días < umbral 15 -> auto


def test_autonomia_siempre_pedir_gana_sobre_tenant(
    session, tenant, customer, invoice, fake_client_factory
):
    # aunque el tenant tenga auto_send por bucket, la config del ayudante manda
    tenant.config = {"auto_send_buckets": ["vencida_reciente"]}
    con_aiudita(
        session, tenant, "cobranza.enviar_whatsapp",
        {"autonomia": "siempre_pedir", "umbral_auto_dias": 7, "tope_critico_dias": 45,
         "cooldown_dias": 4},
    )
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert r.status == "pending_approval"  # siempre pide tu OK


def test_cooldown_por_ayudante_se_respeta(
    session, tenant, customer, invoice, fake_client_factory
):
    con_aiudita(
        session, tenant, "cobranza.enviar_whatsapp",
        {"autonomia": "siempre_pedir", "umbral_auto_dias": 7, "tope_critico_dias": 45,
         "cooldown_dias": 10},
    )
    # se envió hace 5 días: con default (4) tocaría; con cooldown del ayudante (10) no
    session.add(Reminder(
        tenant_id=tenant.id, invoice_id=invoice.id, bucket="vencida_reciente",
        tone="amable_directo", message="previo", status="sent",
        sent_at=datetime.combine(TODAY - timedelta(days=5), time(9, 0), tzinfo=timezone.utc),
    ))
    session.flush()
    assert make_engine(session, tenant, fake_client_factory()).run_reminders(TODAY) == []


# --- Ventana horaria de envío (perilla viva) --------------------------------

def _approved(session, tenant, invoice) -> Reminder:
    r = Reminder(
        tenant_id=tenant.id, invoice_id=invoice.id, bucket="vencida_reciente",
        tone="amable_directo", message="hola", status="approved",
    )
    session.add(r)
    session.flush()
    return r


def test_envio_fuera_de_ventana_se_difiere(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(
        session, tenant, "cobranza.enviar_whatsapp",
        {"autonomia": "siempre_pedir", "cooldown_dias": 4, "umbral_auto_dias": 7,
         "tope_critico_dias": 45, "ventana_horaria": "09:00-19:00"},
    )
    engine = make_engine(session, tenant, fake_client_factory())
    r = _approved(session, tenant, invoice)
    enviados = []
    # 20:00 cae fuera de 09:00-19:00 -> se difiere, no se envía
    with pytest.raises(OutsideSendWindow):
        engine.send(r, "5215500000000", sender=lambda to, t: enviados.append(t), now=time(20, 0))
    assert enviados == [] and r.status == "approved"
    # 10:00 cae dentro -> envía
    engine.send(r, "5215500000000", sender=lambda to, t: enviados.append(t), now=time(10, 0))
    assert enviados == ["hola"] and r.status == "sent"


def test_sin_ayudante_no_aplica_ventana(session, tenant, customer, invoice, fake_client_factory):
    engine = make_engine(session, tenant, fake_client_factory())
    r = _approved(session, tenant, invoice)
    enviados = []
    engine.send(r, "5215500000000", sender=lambda to, t: enviados.append(t), now=time(3, 0))
    assert enviados == ["hola"]  # sin perilla configurada, no hay restricción


# --- Promesa: días de gracia + seguir si incumple (perillas vivas) ----------

def _promesa(session, tenant, invoice, dias_vencida: int):
    session.add(PaymentPromise(
        tenant_id=tenant.id, invoice_id=invoice.id,
        promised_date=TODAY - timedelta(days=dias_vencida),
    ))
    session.flush()


def test_dias_de_gracia_pospone_el_seguimiento(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(session, tenant, "cobranza.registrar_promesa_pago", {"dias_gracia": 5, "seguir_si_incumple": True})
    # se envió hace 2 días (dentro del cooldown), promesa vencida hace 3 días
    session.add(Reminder(
        tenant_id=tenant.id, invoice_id=invoice.id, bucket="vencida_reciente",
        tone="amable_directo", message="previo", status="sent",
        sent_at=datetime.combine(TODAY - timedelta(days=2), time(9, 0), tzinfo=timezone.utc),
    ))
    _promesa(session, tenant, invoice, dias_vencida=3)  # 3 < 5 de gracia: aún no incumple
    assert make_engine(session, tenant, fake_client_factory()).run_reminders(TODAY) == []


def test_promesa_fuera_de_gracia_si_dispara(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(session, tenant, "cobranza.registrar_promesa_pago", {"dias_gracia": 2, "seguir_si_incumple": True})
    _promesa(session, tenant, invoice, dias_vencida=5)  # 5 > 2 de gracia: incumple
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    drafted = make_engine(session, tenant, fake).run_reminders(TODAY)
    assert len(drafted) == 1
    assert "prometió pagar" in fake.messages.requests[0]["messages"][0]["content"]


def test_seguir_si_incumple_apagado_no_da_seguimiento(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(session, tenant, "cobranza.registrar_promesa_pago", {"dias_gracia": 0, "seguir_si_incumple": False})
    # promesa rota + envío reciente (dentro de cooldown): sin seguimiento, manda cooldown
    session.add(Reminder(
        tenant_id=tenant.id, invoice_id=invoice.id, bucket="vencida_reciente",
        tone="amable_directo", message="previo", status="sent",
        sent_at=datetime.combine(TODAY - timedelta(days=1), time(9, 0), tzinfo=timezone.utc),
    ))
    _promesa(session, tenant, invoice, dias_vencida=3)
    assert make_engine(session, tenant, fake_client_factory()).run_reminders(TODAY) == []


# --- Hora del resumen diario (perilla viva) ---------------------------------

def test_summary_due_por_hora_y_activo(session, tenant, customer, invoice, fake_client_factory):
    engine = make_engine(session, tenant, fake_client_factory())
    # sin ayudante: default histórico 8:00
    assert engine.summary_due(8) and not engine.summary_due(16)


def test_summary_due_respeta_hora_configurada(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(session, tenant, "cobranza.resumen_diario", {"activo": True, "hora": "16:00"})
    engine = make_engine(session, tenant, fake_client_factory())
    assert engine.summary_due(16) and not engine.summary_due(8)


def test_summary_apagado_nunca_envia(session, tenant, customer, invoice, fake_client_factory):
    con_aiudita(session, tenant, "cobranza.resumen_diario", {"activo": False, "hora": "08:00"})
    engine = make_engine(session, tenant, fake_client_factory())
    assert not engine.summary_due(8) and not engine.summary_due(16)


# --- Fuente elegida (de dónde lee): el core la preserva como string ---------

def test_validar_config_preserva_fuente_en_aiudita_de_lectura():
    from aiuda_core.aiuditas import aiudita_por_id, validar_config

    spec = aiudita_por_id("cobranza.consultar_cartera")  # tiene capacidad
    cfg = validar_config(spec, {"_fuente": "odoo"})
    assert cfg["_fuente"] == "odoo"


def test_validar_config_ignora_fuente_en_aiudita_sin_capacidad():
    from aiuda_core.aiuditas import aiudita_por_id, validar_config

    spec = aiudita_por_id("cobranza.enviar_whatsapp")  # no lee datos (capacidad="")
    cfg = validar_config(spec, {"_fuente": "odoo"})
    assert "_fuente" not in cfg


# --- Link de pago en el recordatorio (perilla opt-in, pasarela conectada) ----

class _FakePasarela:
    def __init__(self):
        self.args = None

    def crear_link_pago(self, monto, concepto="", referencia=""):
        self.args = (monto, concepto, referencia)
        return "https://mpago.la/PAGA123"


def test_incluir_link_pago_anexa_el_link(
    session, tenant, customer, invoice, fake_client_factory, monkeypatch
):
    con_aiudita(session, tenant, "cobranza.redactar_recordatorio", {"incluir_link_pago": True})
    fp = _FakePasarela()
    import aiuda_core.engine.cobro as cobro

    monkeypatch.setattr(cobro, "resolver_pasarela", lambda s, t: ("mercadopago", fp))
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert "Paga aquí: https://mpago.la/PAGA123" in r.message
    assert fp.args[0] == float(invoice.amount)  # el monto de la factura
    assert fp.args[2] == invoice.folio  # folio como referencia para casar el pago


def test_sin_perilla_ni_intenta_resolver_pasarela(
    session, tenant, customer, invoice, fake_client_factory, monkeypatch
):
    con_aiudita(session, tenant, "cobranza.redactar_recordatorio", {})
    import aiuda_core.engine.cobro as cobro

    llamadas = {"n": 0}

    def espia(s, t):
        llamadas["n"] += 1
        return (None, None)

    monkeypatch.setattr(cobro, "resolver_pasarela", espia)
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert "Paga aquí" not in r.message
    assert llamadas["n"] == 0  # apagado por defecto: cero costo


def test_link_pago_caido_no_rompe_el_recordatorio(
    session, tenant, customer, invoice, fake_client_factory, monkeypatch
):
    con_aiudita(session, tenant, "cobranza.redactar_recordatorio", {"incluir_link_pago": True})

    class _Boom:
        def crear_link_pago(self, *a, **k):
            raise RuntimeError("pasarela caída")

    import aiuda_core.engine.cobro as cobro

    monkeypatch.setattr(cobro, "resolver_pasarela", lambda s, t: ("mercadopago", _Boom()))
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    r = make_engine(session, tenant, fake).draft_reminder(invoice, customer, TODAY)
    assert r.status == "pending_approval"  # el recordatorio sale igual, sin link
    assert "Paga aquí" not in r.message
