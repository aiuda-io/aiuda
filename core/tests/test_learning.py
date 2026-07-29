"""El loop de aprendizaje: capturar correcciones y reinyectarlas al prompt."""

from aiuda_core.agents.cleo.prompt import build_system_prompt
from aiuda_core.learning import learning_summary, recent_corrections, record_feedback
from aiuda_core.models import Reminder


def _reminder(tenant, message, agent="mariana", bucket="reciente", tone="amable"):
    return Reminder(
        tenant_id=tenant.id, agent=agent, bucket=bucket, tone=tone,
        message=message, status="pending_approval", channel="whatsapp",
    )


def test_recent_corrections_devuelve_solo_ediciones(session, tenant):
    r = _reminder(tenant, "Hola, debe 500.")
    session.add(r)
    session.flush()
    record_feedback(
        session, tenant, r,
        decision="edited", draft_original="Hola, debe 500.",
        final_text="Qué tal, su saldo es de 500, ¿cómo le apoyo?",
    )
    assert recent_corrections(session, tenant, agent="mariana") == [
        ("Hola, debe 500.", "Qué tal, su saldo es de 500, ¿cómo le apoyo?")
    ]


def test_recent_corrections_ignora_aprobados_sin_editar(session, tenant):
    r = _reminder(tenant, "x")
    session.add(r)
    session.flush()
    record_feedback(session, tenant, r, decision="approved", draft_original="x", final_text="x")
    assert recent_corrections(session, tenant) == []


def test_learning_summary_cuenta_y_tasa(session, tenant):
    for dec, orig, final in [("approved", "a", "a"), ("edited", "b", "B"), ("rejected", "c", None)]:
        r = _reminder(tenant, orig)
        session.add(r)
        session.flush()
        record_feedback(session, tenant, r, decision=dec, draft_original=orig, final_text=final)
    s = learning_summary(session, tenant)
    assert s["approved"] == 1 and s["edited"] == 1 and s["rejected"] == 1
    assert s["tasaSinEditar"] == 0.5  # 1 sin editar de 2 enviados
    assert len(s["recientes"]) == 1 and s["recientes"][0]["final"] == "B"


def test_prompt_inyecta_correcciones_bajo_las_reglas():
    p = build_system_prompt(
        "Hanova",
        correcciones=[("Debe pagar ya.", "¿Le ayudo a ponerse al corriente?")],
    )
    assert "REGLAS INQUEBRANTABLES" in p  # los safeguards siguen arriba
    assert "CÓMO CORRIGE EL DUEÑO" in p
    assert "¿Le ayudo a ponerse al corriente?" in p


def test_prompt_sin_correcciones_no_agrega_seccion():
    assert "CÓMO CORRIGE EL DUEÑO" not in build_system_prompt("Hanova")
