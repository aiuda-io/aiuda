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


def test_learning_summary_separa_por_ayudante(session, tenant):
    """Cada ayudante ve SUS correcciones, no las del oficio.

    La consola pedía siempre el slug de runtime ("mariana"), así que la pestaña
    Aprendizaje de todos los ayudantes mostraba los mismos números. Dos ayudantes de
    cobranza comparten runtime; lo que los distingue es Reminder.meta["ayudante_id"],
    que es la atribución real de cada propuesta."""
    de_ana = _reminder(tenant, "propuesta de Ana")
    de_ana.meta = {"ayudante_id": "ay-ana", "ayudante_name": "Ana"}
    de_beto = _reminder(tenant, "propuesta de Beto")
    de_beto.meta = {"ayudante_id": "ay-beto", "ayudante_name": "Beto"}
    session.add_all([de_ana, de_beto])
    session.flush()

    record_feedback(session, tenant, de_ana, decision="edited",
                    draft_original="propuesta de Ana", final_text="corregida por el dueño")
    record_feedback(session, tenant, de_beto, decision="approved",
                    draft_original="propuesta de Beto", final_text="propuesta de Beto")

    ana = learning_summary(session, tenant, ayudante_id="ay-ana")
    assert ana["edited"] == 1 and ana["approved"] == 0
    assert [r["final"] for r in ana["recientes"]] == ["corregida por el dueño"]

    beto = learning_summary(session, tenant, ayudante_id="ay-beto")
    assert beto["approved"] == 1 and beto["edited"] == 0
    assert beto["recientes"] == []

    # Sin ayudante_id sigue el comportamiento legado: todo el oficio junto.
    assert learning_summary(session, tenant)["total"] == 2


def test_learning_summary_de_un_ayudante_sin_trabajo_no_toma_prestado_el_ajeno(session, tenant):
    r = _reminder(tenant, "propuesta de Ana")
    r.meta = {"ayudante_id": "ay-ana"}
    session.add(r)
    session.flush()
    record_feedback(session, tenant, r, decision="edited",
                    draft_original="propuesta de Ana", final_text="corregida")

    nuevo = learning_summary(session, tenant, ayudante_id="ay-recien-creado")
    assert nuevo["total"] == 0 and nuevo["tasaSinEditar"] is None and nuevo["recientes"] == []
