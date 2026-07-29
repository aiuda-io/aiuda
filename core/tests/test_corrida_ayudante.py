"""Corrida del motor COMO un ayudante del dueño: su config gobierna y el trabajo
queda atribuido a él (meta.ayudante_id) — la señal que alimenta su plan de carrera."""

from datetime import date

from aiuda_core.engine.engine import CleoEngine
from aiuda_core.engine.llm import ClaudeRunner
from aiuda_core.models import Ayudante
from conftest import FakeResponse

TODAY = date(2026, 6, 9)

# La factura de conftest: F-001 por $12,500.50. El motor no guarda el borrador que
# no las cita, así que ni como fake sirve un "Recordatorio." pelón.
RECORDATORIO = "Buen día, le recuerdo su factura F-001 por $12,500.50, ya vencida."


def _engine(session, tenant, fake_client, ayudante_id=None):
    runner = ClaudeRunner(client=fake_client, usage_callback=None)
    engine = CleoEngine(session, tenant, runner=runner, ayudante_id=ayudante_id)
    runner._usage_callback = engine._record_usage
    return engine


def _ayudante(session, tenant, name, aiuditas, instructions=None):
    a = Ayudante(tenant_id=tenant.id, name=name, aiuditas=aiuditas, instructions=instructions)
    session.add(a)
    session.flush()
    return a


def test_corrida_como_ayudante_usa_su_config_y_atribuye(
    session, tenant, customer, invoice, fake_client_factory
):
    # Dos ayudantes con cobranza: el viejo (amable) y el nuevo (firme, con firma).
    _ayudante(session, tenant, "abi", {"cobranza.redactar_recordatorio": {"tono_base": "amable"}})
    nuevo = _ayudante(
        session,
        tenant,
        "gio",
        {
            "cobranza.redactar_recordatorio": {
                "tono_base": "firme",
                "escalar_por_atraso": False,
                "firma": "Equipo Gio",
                "reglas": "ofrece pago en OXXO",
            }
        },
        instructions="Habla de tú, sé breve.",
    )

    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    drafted = _engine(session, tenant, fake, ayudante_id=nuevo.id).run_reminders(TODAY)

    assert len(drafted) == 1
    r = drafted[0]
    # Atribución REAL: la propuesta es de gio, no del primero por antigüedad.
    assert r.meta["ayudante_id"] == nuevo.id
    assert r.meta["ayudante_name"] == "gio"
    # Su config gobernó: tono firme (sin escalar) y su firma al final.
    assert r.tone == "firme"
    assert r.message.endswith("Equipo Gio")
    # Sus reglas e instrucciones entraron al prompt del sistema.
    system = fake.messages.requests[0]["system"]
    assert "ofrece pago en OXXO" in system
    assert "Habla de tú" in system


def test_corrida_tenant_atribuye_al_que_gobierna(
    session, tenant, customer, invoice, fake_client_factory
):
    """Sin ayudante explícito (la corrida diaria), la propuesta se atribuye al primero
    con la aiudita de redacción: SU config es la que corre."""
    dueno = _ayudante(
        session, tenant, "abi", {"cobranza.redactar_recordatorio": {"tono_base": "amable"}}
    )
    _ayudante(session, tenant, "gio", {"cobranza.redactar_recordatorio": {"tono_base": "firme"}})

    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    drafted = _engine(session, tenant, fake).run_reminders(TODAY)

    assert len(drafted) == 1
    assert drafted[0].meta["ayudante_id"] == dueno.id


def test_sin_ayudantes_no_finge_atribucion(
    session, tenant, customer, invoice, fake_client_factory
):
    """Sin ayudantes creados, el motor corre como siempre y NO inventa un autor."""
    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    drafted = _engine(session, tenant, fake).run_reminders(TODAY)

    assert len(drafted) == 1
    assert "ayudante_id" not in (drafted[0].meta or {})


def test_corrida_como_ayudante_sin_la_aiudita_usa_defaults(
    session, tenant, customer, invoice, fake_client_factory
):
    """Correr como un ayudante que NO tiene una aiudita no hereda la config de otro:
    esa perilla cae a los defaults del motor (solo lo suyo cuenta)."""
    _ayudante(
        session, tenant, "abi", {"cobranza.redactar_recordatorio": {"tono_base": "firme"}}
    )
    solo_envio = _ayudante(
        session, tenant, "gio", {"cobranza.redactar_recordatorio": {}}
    )

    fake = fake_client_factory(FakeResponse(RECORDATORIO))
    engine = _engine(session, tenant, fake, ayudante_id=solo_envio.id)
    drafted = engine.run_reminders(TODAY)

    # gio no configuró tono: bucket manda (vencida_reciente → amable_directo), no
    # el "firme" de abi.
    assert drafted[0].tone == "amable_directo"
    assert drafted[0].meta["ayudante_id"] == solo_envio.id
