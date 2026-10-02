"""Grabar qué hizo un ayudante, sin romper lo que estaba grabando."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from aiuda_core.models import Customer, Run, RunLink, RunTurn
from aiuda_core.observabilidad import abrir_run, envolver, redactar
from aiuda_core.observabilidad.tracer import _TracedRunner


class _Runner:
    """Un ProviderRunner mínimo, con los atributos que el motor asigna DESDE FUERA."""

    def __init__(self):
        self.budget_check = None
        self._usage_callback = None
        self.llamadas: list[tuple] = []

    def model_for(self, role):
        return "modelo-de-prueba"

    def complete(self, system, user, **kw):
        if self.budget_check is not None:
            self.budget_check()
        self.llamadas.append(("complete", system, user))
        return "listo"

    def classify(self, system, user, **kw):
        return "etiqueta"

    def run_tool_loop(self, *, system, user_message, tools, execute_tool, **kw):
        execute_tool("consultar_cartera", {"telefono_cliente": "5215512345678"})
        return "respuesta final"


# --- El peligro del wrapper -------------------------------------------------

def test_asignar_budget_check_llega_al_runner_de_adentro(session, tenant):
    """LA prueba que justifica el proxy.

    `tenant_runner` asigna `budget_check` DESPUÉS de envolver, y el worker hace lo mismo
    (`worker/main.py:141`). Un wrapper normal se quedaría con la asignación y el runner
    interno nunca vería el tope: se apagaría el corte de presupuesto en silencio, que es
    peor que no tener trazas."""
    interno = _Runner()
    with abrir_run(session, tenant) as run:
        envuelto = envolver(interno, run, session, tenant)
        cortes: list[int] = []
        envuelto.budget_check = lambda: cortes.append(1)

        assert interno.budget_check is not None, "la asignación NO llegó al runner interno"
        envuelto.complete("s", "u", task="t")
        assert cortes == [1], "el tope no se evaluó: el gasto quedó sin control"


def test_el_wrapper_delega_lo_que_no_sabe_hacer(session, tenant):
    interno = _Runner()
    with abrir_run(session, tenant) as run:
        envuelto = envolver(interno, run, session, tenant)
        assert envuelto.model_for("redaccion") == "modelo-de-prueba"
        assert isinstance(envuelto, _TracedRunner)


def test_sin_run_devuelve_el_runner_tal_cual(session, tenant):
    interno = _Runner()
    assert envolver(interno, None, session, tenant) is interno


def test_grabar_nunca_tumba_el_trabajo_real(session, tenant):
    """Si el runner no sabe decir su modelo, se anota vacío y se sigue. La traza es
    secundaria: jamás debe romper la corrida que está observando."""

    class SinModelFor(_Runner):
        def model_for(self, role):
            raise RuntimeError("no implementado")

    with abrir_run(session, tenant) as run:
        envuelto = envolver(SinModelFor(), run, session, tenant)
        assert envuelto.complete("s", "u", task="t") == "listo"


# --- Lo que queda grabado ---------------------------------------------------

def test_un_run_guarda_su_narrativa_y_sus_conteos(session, tenant):
    with abrir_run(session, tenant, aiudita="cobranza.redactar_recordatorio") as run:
        run.contar(leidos=12, propuestos=4)
        run.contar(omitidos=8)
        run.motivo("sin_whatsapp", "Ferretería sin teléfono")
        run.motivo("sin_whatsapp")

    fila = session.scalar(select(Run).where(Run.tenant_id == tenant.id))
    assert fila.status == "done" and fila.finished_at is not None
    assert fila.conteos == {"leidos": 12, "propuestos": 4, "omitidos": 8}
    assert fila.motivos == [{"codigo": "sin_whatsapp", "n": 2, "detalle": "Ferretería sin teléfono"}]
    # La frase la escribe CÓDIGO: si el modelo narrara su trabajo, dejaría de ser evidencia.
    assert fila.resumen == "Leyó 12 facturas, propuso 4, omitió 8."


def test_un_run_que_truena_queda_marcado_y_relanza(session, tenant):
    with pytest.raises(RuntimeError):
        with abrir_run(session, tenant):
            raise RuntimeError("se cayó Odoo")

    fila = session.scalar(select(Run).where(Run.tenant_id == tenant.id))
    assert fila.status == "failed" and "se cayó Odoo" in (fila.error or "")
    assert fila.finished_at is not None, "aunque truene, el run se cierra"


def test_cortado_es_distinto_de_fallido(session, tenant):
    """Terminó sin error pero sin hacer el trabajo. Antes se perdía."""
    with abrir_run(session, tenant) as run:
        run.cortar("Se acabó el tope de IA del mes.")

    fila = session.scalar(select(Run).where(Run.tenant_id == tenant.id))
    assert fila.status == "cortado"
    assert fila.resumen == "Se detuvo: Se acabó el tope de IA del mes."


def test_los_turnos_guardan_las_tools_con_sus_tiempos(session, tenant):
    with abrir_run(session, tenant) as run:
        envuelto = envolver(_Runner(), run, session, tenant)
        envuelto.run_tool_loop(
            system="s", user_message="cuánto debe", tools=[], execute_tool=lambda n, a: "1 factura"
        )

    turno = session.scalar(select(RunTurn))
    assert turno.tools and turno.tools[0]["nombre"] == "consultar_cartera"
    assert turno.tools[0]["error"] is None
    assert "ms" in turno.tools[0]


def test_las_ligas_llevan_al_trabajo_real(session, tenant):
    with abrir_run(session, tenant) as run:
        run.liga("reminder", "r-1", rol="propuso")
        run.liga("invoice", "i-1", rol="leyo")
        run.liga("", "vacio")  # se ignora

    ligas = session.scalars(select(RunLink)).all()
    assert {(x.entity_type, x.rol) for x in ligas} == {("reminder", "propuso"), ("invoice", "leyo")}


# --- Redacción --------------------------------------------------------------

def test_redacta_los_datos_del_cliente_pero_no_el_dinero(session, tenant):
    """El dueño abre la transcripción para juzgar el mensaje. Sin monto ni folio no
    puede, así que esos NO se redactan."""
    texto = (
        "Hola, la factura INV/2026/00179 por $29,123.84 vence hoy. "
        "Escríbenos al 5215512345678 o a pagos@ferreteria.mx. RFC FER950101ABC."
    )
    out = redactar(texto)

    assert "INV/2026/00179" in out and "29,123.84" in out
    assert "5215512345678" not in out and "pagos@ferreteria.mx" not in out
    assert "FER950101ABC" not in out
    assert "[tel:" in out and "[correo:" in out and "[rfc:" in out


def test_el_marcador_es_estable_para_el_mismo_valor():
    """Dos menciones del mismo teléfono dan el mismo marcador: el dueño ve que es la
    misma persona sin que el dato esté ahí. Un [tel] genérico perdería eso."""
    import re

    out = redactar("Le escribí al 5512345678 y volví a marcarle al 55 1234 5678.")
    marcadores = set(re.findall(r"\[tel:[0-9a-f]+\]", out))
    assert len(marcadores) == 1, out
    assert out.count(next(iter(marcadores))) == 2, out


def test_los_nombres_de_cliente_se_sustituyen_por_diccionario():
    """Por regex es imposible; con los Customer.name del tenant, sí."""
    out = redactar(
        "Ferretería Ruiz SA de CV no ha pagado.",
        nombres=["Ferretería Ruiz SA de CV", "Ferretería Ruiz"],
    )
    assert "Ruiz" not in out and "[cliente:Ferretería]" in out


def test_una_tarjeta_se_redacta_pero_un_folio_largo_no():
    """Sin el check de Luhn, cualquier cadena larga de dígitos (una referencia bancaria)
    se confundiría con una tarjeta."""
    assert "[tarjeta:" in redactar("Pagó con 4111111111111111.")
    assert "12345678901234567" in redactar("Referencia 12345678901234567 del depósito.")


def test_sin_guardar_prompts_no_se_escribe_ni_uno(session, tenant):
    """El modo para un despacho contable: la narrativa y las tools siguen, el texto no."""
    tenant.config = {**(tenant.config or {}), "observabilidad": {"guardar_prompts": "no"}}
    session.add(tenant)
    session.flush()

    with abrir_run(session, tenant) as run:
        envolver(_Runner(), run, session, tenant).complete("secreto", "del cliente", task="t")

    turno = session.scalar(select(RunTurn))
    assert turno is not None, "el turno se registra igual"
    assert turno.system_prompt is None and turno.user_prompt is None and turno.output_text is None


def test_los_nombres_del_tenant_alimentan_la_redaccion(session, tenant):
    session.add(Customer(tenant_id=tenant.id, name="Aceros del Bajío", phone="5215599990000"))
    session.flush()

    with abrir_run(session, tenant) as run:
        envolver(_Runner(), run, session, tenant).complete(
            "s", "Aceros del Bajío debe 500", task="t"
        )

    turno = session.scalar(select(RunTurn))
    assert "Aceros del Bajío" not in (turno.user_prompt or "")
    assert "[cliente:Aceros]" in (turno.user_prompt or "")


def test_los_tokens_se_atribuyen_al_turno_que_los_gasto(session, tenant):
    """El uso NO vuelve por el valor de retorno: el runner lo reporta por su
    usage_callback, DURANTE la llamada, mientras el turno se escribe DESPUÉS. Si no se
    acumulan, la actividad muestra 0 tokens en todo y la pantalla de consumo miente."""

    class ConUso(_Runner):
        def complete(self, system, user, **kw):
            self._usage_callback("modelo-x", kw.get("task", ""), 120, 40)
            return "listo"

    interno = ConUso()
    interno._usage_callback = lambda *a: None  # el engine siempre engancha uno
    with abrir_run(session, tenant) as run:
        envolver(interno, run, session, tenant).complete("s", "u", task="draft_reminder")

    turno = session.scalar(select(RunTurn))
    assert (turno.input_tokens, turno.output_tokens) == (120, 40)
    # El modelo que el runner declara gana sobre el que reporta el uso: es el que de
    # verdad corrió. El del uso solo entra si el runner no supo decirlo.
    assert turno.model == "modelo-de-prueba"

    fila = session.scalar(select(Run).where(Run.tenant_id == tenant.id))
    assert (fila.input_tokens, fila.output_tokens) == (120, 40), "el run suma sus turnos"


def test_reemplazar_el_callback_despues_no_pierde_los_tokens(session, tenant):
    """El engine reemplaza el callback si le inyectan un runner sin uno. Sin re-envolver,
    los tokens de ese runner dejarían de contarse en silencio."""

    class ConUso(_Runner):
        def complete(self, system, user, **kw):
            self._usage_callback("m", "t", 7, 3)
            return "ok"

    interno = ConUso()
    interno._usage_callback = lambda *a: None
    with abrir_run(session, tenant) as run:
        envuelto = envolver(interno, run, session, tenant)
        envuelto._usage_callback = lambda *a: None  # el engine hace justo esto
        envuelto.complete("s", "u", task="t")

    turno = session.scalar(select(RunTurn))
    assert (turno.input_tokens, turno.output_tokens) == (7, 3)


def test_un_chat_no_dice_que_no_habia_nada_que_hacer(session, tenant):
    """Contestarte ES el trabajo. Decir "no había nada que hacer" después de responderte
    sería mentir en la única frase que el dueño lee."""
    with abrir_run(session, tenant, disparo="chat") as run:
        run.contar(respuestas=1)

    fila = session.scalar(select(Run).where(Run.tenant_id == tenant.id))
    assert fila.resumen == "Te contestó."
