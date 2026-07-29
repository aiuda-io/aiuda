from datetime import date

import pytest
from sqlalchemy import select

from aiuda_core.agents.cleo.prompt import build_system_prompt
from aiuda_core.engine.engine import CleoEngine
from aiuda_core.engine.llm import ClaudeRunner, strip_markdown
from aiuda_core.models import PaymentPromise, UsageEvent
from conftest import FakeResponse

TODAY = date(2026, 6, 9)


def make_engine(session, tenant, fake_client, send_log=None):
    runner = ClaudeRunner(client=fake_client, usage_callback=None)
    engine = CleoEngine(
        session,
        tenant,
        runner=runner,
        send_whatsapp=(lambda phone, text: send_log.append((phone, text)))
        if send_log is not None
        else None,
    )
    # conecta el callback de uso al engine ya construido
    runner._usage_callback = engine._record_usage
    return engine


def test_draft_reminder_queda_pendiente_de_aprobacion(
    session, tenant, customer, invoice, fake_client_factory
):
    fake = fake_client_factory(FakeResponse("Hola, su factura F-001 está pendiente."))
    engine = make_engine(session, tenant, fake)
    reminder = engine.draft_reminder(invoice, customer, TODAY)

    assert reminder.status == "pending_approval"
    assert reminder.bucket == "vencida_reciente"  # venció 2026-05-31, hoy es 06-09
    assert reminder.tone == "amable_directo"
    assert "F-001" in reminder.message
    # el prompt de redacción lleva el tono decidido por código
    prompt = fake.messages.requests[0]["messages"][0]["content"]
    assert "amable_directo" in prompt


def test_run_reminders_no_duplica_activos(session, tenant, customer, invoice, fake_client_factory):
    fake = fake_client_factory(FakeResponse("Mensaje 1"), FakeResponse("Mensaje 2"))
    engine = make_engine(session, tenant, fake)
    first = engine.run_reminders(TODAY)
    assert len(first) == 1
    second = engine.run_reminders(TODAY)
    assert second == []  # ya hay un recordatorio activo para esa factura


def test_auto_send_aprueba_solo_buckets_configurados(
    session, tenant, customer, invoice, fake_client_factory
):
    tenant.config = {"auto_send_buckets": ["vencida_reciente"]}
    fake = fake_client_factory(FakeResponse("Recordatorio"))
    engine = make_engine(session, tenant, fake)
    reminder = engine.draft_reminder(invoice, customer, TODAY)
    assert reminder.status == "approved"


def test_aprobar_y_enviar(session, tenant, customer, invoice, fake_client_factory):
    fake = fake_client_factory(FakeResponse("Recordatorio de pago"))
    sent = []
    engine = make_engine(session, tenant, fake, send_log=sent)
    reminder = engine.draft_reminder(invoice, customer, TODAY)
    engine.approve(reminder)
    engine.send(reminder, customer.phone)
    assert reminder.status == "sent"
    assert sent == [(customer.phone, "Recordatorio de pago")]


def test_send_evalua_la_ventana_en_hora_de_mexico(
    session, tenant, customer, invoice, fake_client_factory, monkeypatch
):
    # La ventana de no-molestar la configura el dueño en hora de México. El envío debe
    # pedir la hora en MX_TZ, no el UTC del servidor (que iría ~6h adelantado y podría
    # bloquear dentro de horario o mandar de madrugada).
    from aiuda_core.engine import engine as engine_mod
    from aiuda_core.models import Ayudante

    session.add(
        Ayudante(
            tenant_id=tenant.id,
            name="Mariana",
            aiuditas={"cobranza.enviar_whatsapp": {"ventana_horaria": "08:00-20:00"}},
        )
    )
    session.flush()

    captured: dict = {}
    real_dt = engine_mod.datetime

    class _DT:
        @staticmethod
        def now(tz=None):
            captured["tz"] = tz
            return real_dt(2026, 6, 9, 15, 0, tzinfo=tz)  # 15:00 en la tz pedida

    monkeypatch.setattr(engine_mod, "datetime", _DT)

    sent: list = []
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("Recordatorio")), sent)
    reminder = engine.draft_reminder(invoice, customer, TODAY)
    engine.approve(reminder)
    engine.send(reminder, customer.phone)

    assert captured["tz"] is engine_mod.MX_TZ  # se pidió la hora en México
    assert reminder.status == "sent"  # 15:00 MX cae dentro de 08:00-20:00


def test_modo_sombra_retiene_el_envio_de_recordatorios(
    session, tenant, customer, invoice, fake_client_factory
):
    from aiuda_core.engine.engine import ShadowHold

    tenant.config = {"modo_sombra": True}
    sent: list = []
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("Recordatorio")), sent)
    reminder = engine.draft_reminder(invoice, customer, TODAY)
    engine.approve(reminder)
    with pytest.raises(ShadowHold):
        engine.send(reminder, customer.phone)
    assert reminder.status == "approved"  # queda para revisar, NO se envió
    assert sent == []  # nada salió


def test_modo_sombra_no_manda_por_el_canal_directo(
    session, tenant, customer, invoice, fake_client_factory
):
    # Las respuestas del agente/dueño (send_whatsapp directo) también se retienen.
    tenant.config = {"modo_sombra": True}
    sent: list = []
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("x")), sent)
    engine.send_whatsapp("5215500000000", "hola")
    assert sent == []  # se registró en log, no se envió


def test_registro_de_uso_por_tenant(session, tenant, customer, invoice, fake_client_factory):
    fake = fake_client_factory(FakeResponse("Recordatorio"))
    engine = make_engine(session, tenant, fake)
    engine.draft_reminder(invoice, customer, TODAY)
    session.flush()
    events = session.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id)).all()
    assert len(events) == 1
    assert events[0].task == "redactar_recordatorio"
    assert events[0].input_tokens == 100


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input_, id_="toolu_01"):
        self.name = name
        self.input = input_
        self.id = id_


def test_handle_incoming_registra_promesa(session, tenant, customer, invoice, fake_client_factory):
    tool_call = FakeResponse(
        "",
        stop_reason="tool_use",
        content=[
            FakeToolUseBlock(
                "registrar_promesa_pago",
                {"folio": "F-001", "fecha_promesa": "2026-06-13", "nota": "paga el viernes"},
            )
        ],
    )
    final = FakeResponse("Perfecto, quedo al pendiente de su pago el viernes. ¡Gracias!")
    fake = fake_client_factory(tool_call, final)
    engine = make_engine(session, tenant, fake)

    reply = engine.handle_incoming(customer.phone, "te pago el viernes sin falta", TODAY)

    assert "viernes" in reply
    promises = session.scalars(
        select(PaymentPromise).where(PaymentPromise.tenant_id == tenant.id)
    ).all()
    assert len(promises) == 1
    assert promises[0].promised_date == date(2026, 6, 13)
    # el resultado del tool se devolvió al modelo
    second_request = fake.messages.requests[1]
    assert second_request["messages"][-1]["content"][0]["type"] == "tool_result"


def test_handle_incoming_quita_emojis(session, tenant, customer, invoice, fake_client_factory):
    """La regla dura (cero emojis) aplica también al chat con el deudor: la respuesta
    del tool-loop va directo al WhatsApp del cliente. Antes solo draft_reminder tenía
    la red; los evals con el modelo real (2026-07-07) destaparon que este camino no."""
    fake = fake_client_factory(
        FakeResponse("✅ Quedo al pendiente de su pago. Gracias por avisar. 🙏")
    )
    engine = make_engine(session, tenant, fake)
    reply = engine.handle_incoming(customer.phone, "mañana les deposito", TODAY)
    assert "✅" not in reply and "🙏" not in reply
    assert reply == "Quedo al pendiente de su pago. Gracias por avisar."


def test_handle_incoming_plancha_markdown(session, tenant, customer, invoice, fake_client_factory):
    """Los evals con el modelo real (2026-07-07) destaparon que haiku contesta el
    tool-loop con markdown de reporte (**negritas**, encabezados, ---) que iría
    DIRECTO al WhatsApp del cliente. La regla 9 del prompt lo prohíbe; esta red
    determinista plancha lo que se le escape al modelo."""
    fake = fake_client_factory(
        FakeResponse(
            "**Resumen:**\n---\nSu factura F-001 tiene saldo de $12,500.50.\n"
            "### Siguiente paso\nQuedo al pendiente de su pago."
        )
    )
    engine = make_engine(session, tenant, fake)
    reply = engine.handle_incoming(customer.phone, "cuánto debo?", TODAY)
    assert "**" not in reply and "---" not in reply and "#" not in reply
    assert reply == (
        "Resumen:\nSu factura F-001 tiene saldo de $12,500.50.\n"
        "Siguiente paso\nQuedo al pendiente de su pago."
    )


def test_draft_reminder_tambien_plancha_markdown(
    session, tenant, customer, invoice, fake_client_factory
):
    fake = fake_client_factory(
        FakeResponse("**Recordatorio:** su factura F-001 vence pronto.\n___\nGracias.")
    )
    engine = make_engine(session, tenant, fake)
    reminder = engine.draft_reminder(invoice, customer, TODAY)
    assert reminder.message == "Recordatorio: su factura F-001 vence pronto.\nGracias."


def test_strip_markdown_plancha_reporte():
    assert strip_markdown("**Total:** $100") == "Total: $100"
    assert strip_markdown("__ojo__ con la fecha") == "ojo con la fecha"
    assert strip_markdown("# Encabezado\ntexto") == "Encabezado\ntexto"
    assert strip_markdown("a\n\n---\n\nb") == "a\n\nb"  # separador fuera, sin triple salto
    assert strip_markdown("a\n- - -\nb") == "a\nb"


def test_strip_markdown_no_rompe_texto_legitimo():
    texto = (
        "Hola María - le escribo por su factura.\n"
        "- F-001: $1,200.00\n"
        "- F-002: $800.00\n"
        "Puede marcarnos al 555-1234. *Gracias* por su _preferencia_."
    )
    # Guiones de lista, teléfonos y *énfasis simple* (formato nativo de WhatsApp)
    # se quedan tal cual: la red solo plancha markdown de reporte.
    assert strip_markdown(texto) == texto


def test_prompt_exige_texto_plano_al_cliente():
    """La regla 9 (formato) es safeguard de fábrica: presente aunque el negocio
    no configure nada. El system prompt del chat y de la redacción es el mismo."""
    p = build_system_prompt("Hanova")
    assert "9. FORMATO" in p
    assert "Markdown" in p and "texto plano" in p


def test_build_system_prompt_identidad_desde_ayudante():
    """El builder arma la identidad desde el ayudante custom; sin él, neutral. En
    ningún caso aparece la persona hardcodeada 'Mariana' que había antes."""
    # Con ayudante: su nombre es la identidad y sus instrucciones son la persona base.
    named = build_system_prompt(
        "Hanova", ayudante_name="tavo de cobranza", persona="Puro norteño, sin rodeos."
    )
    assert named.startswith("Eres tavo de cobranza, ayudante de cobranza de Hanova")
    assert "Puro norteño, sin rodeos." in named
    assert named.index("Puro norteño") < named.index("REGLAS INQUEBRANTABLES")
    # Sin ayudante: identidad neutral, sin nombre propio.
    neutral = build_system_prompt("Hanova")
    assert neutral.startswith("Eres el ayudante de cobranza de Hanova")
    assert "Mariana" not in neutral and "Mariana" not in named
    # Las reglas duras se preservan idénticas en ambos casos.
    for p in (named, neutral):
        assert "REGLAS INQUEBRANTABLES" in p and "9. FORMATO" in p


def test_daily_summary_es_deterministico(session, tenant, customer, invoice, fake_client_factory):
    fake = fake_client_factory()  # el resumen no usa LLM
    engine = make_engine(session, tenant, fake)
    summary = engine.daily_summary(TODAY)
    assert "Vencidas 1–15 días: 1 facturas" in summary
    assert "$12,500.50" in summary


def test_instrucciones_del_ayudante_de_cobranza_gobiernan_el_prompt(
    session, tenant, customer, invoice, fake_client_factory
):
    # Las instrucciones libres que el dueño le escribió a SU ayudante de cobranza son la
    # PERSONA del system prompt: su nombre es la identidad y su texto es el estilo base,
    # ARRIBA de las reglas de fábrica (persona, no reglas de segunda clase). Las de un
    # ayudante de otra capacidad (ventas) no gobiernan la cobranza.
    from aiuda_core.models import Ayudante

    session.add(
        Ayudante(
            tenant_id=tenant.id,
            name="Vendedor",
            instructions="Ofrece 2x1 en todo.",
            aiuditas={"ventas.generar_cotizacion": {}},
        )
    )
    session.add(
        Ayudante(
            tenant_id=tenant.id,
            name="Cobrador",
            instructions="Nunca ofrezcas descuentos.",
            aiuditas={"cobranza.redactar_recordatorio": {}},
        )
    )
    session.flush()
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("x")))
    system = engine._system_prompt()
    assert "Eres Cobrador, ayudante de cobranza" in system  # su nombre es la identidad
    assert "Nunca ofrezcas descuentos." in system
    assert "Ofrece 2x1" not in system  # las de ventas no gobiernan la cobranza
    # La persona va ARRIBA de las reglas inquebrantables (es el carácter, no una regla más).
    assert system.index("Nunca ofrezcas descuentos.") < system.index("REGLAS INQUEBRANTABLES")


def test_persona_se_arma_desde_el_ayudante_custom(
    session, tenant, customer, invoice, fake_client_factory
):
    # (a) Con un ayudante custom, la identidad del prompt es SU nombre libre y sus
    # instrucciones aparecen como la persona/estilo base. "Mariana" no aparece en ningún lado.
    from aiuda_core.models import Ayudante

    session.add(
        Ayudante(
            tenant_id=tenant.id,
            name="tavo de cobranza",
            instructions="Habla golpeado pero respetuoso, puro norteño.",
            aiuditas={"cobranza.redactar_recordatorio": {}},
        )
    )
    session.flush()
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("x")))
    system = engine._system_prompt()
    assert "Eres tavo de cobranza, ayudante de cobranza de" in system
    assert "Habla golpeado pero respetuoso, puro norteño." in system
    assert "Mariana" not in system  # la persona hardcodeada desapareció del prompt


def test_persona_neutral_sin_ayudante(session, tenant, customer, invoice, fake_client_factory):
    # (b) Sin ayudante de cobranza, la persona es NEUTRAL: sin ningún nombre propio.
    engine = make_engine(session, tenant, fake_client_factory(FakeResponse("x")))
    system = engine._system_prompt()
    assert "Eres el ayudante de cobranza de" in system
    assert "Mariana" not in system
    assert "Eres tavo" not in system
    # Las reglas duras siguen intactas aunque no haya persona.
    assert "REGLAS INQUEBRANTABLES" in system
    assert "9. FORMATO" in system


def test_correr_como_ayudante_usa_su_nombre_no_el_mas_antiguo(
    session, tenant, customer, invoice, fake_client_factory
):
    # (c) Corriendo COMO un ayudante concreto (ayudante_id explícito), la persona es la de
    # ESE ayudante, aunque exista otro más antiguo que también redacta cobranza.
    from aiuda_core.models import Ayudante

    ana = Ayudante(
        tenant_id=tenant.id,
        name="Ana la cobradora",
        instructions="Trato muy formal.",
        aiuditas={"cobranza.redactar_recordatorio": {}},
    )
    session.add(ana)
    session.flush()  # ana queda más antigua (created_at menor)
    beto = Ayudante(
        tenant_id=tenant.id,
        name="Beto el cobrador",
        instructions="Trato cercano y directo.",
        aiuditas={"cobranza.redactar_recordatorio": {}},
    )
    session.add(beto)
    session.flush()

    runner = ClaudeRunner(client=fake_client_factory(FakeResponse("x")), usage_callback=None)
    engine = CleoEngine(session, tenant, runner=runner, ayudante_id=beto.id)
    runner._usage_callback = engine._record_usage
    system = engine._system_prompt()
    assert "Eres Beto el cobrador, ayudante de cobranza de" in system
    assert "Trato cercano y directo." in system  # su persona
    assert "Ana la cobradora" not in system and "Trato muy formal." not in system
