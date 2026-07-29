"""Fallback a CUA: el dueño elige CUA como fuente de una capacidad sin conector API y el
motor de sync enruta al Computer Use Agent. Con navegador+credencial corre; sin ellos o
sin la URL del portal, no-op honesto. Aquí se prueba con un runner mockeado (el loop real
con Playwright vive en test_cua_portales.py)."""

from datetime import date

import pytest
from sqlalchemy import select

from aiuda_core.cua.fallback import CUA_PORTALES_KEY, sync_cua
from aiuda_core.cua.mission import MissionResult
from aiuda_core.models import Payment


@pytest.fixture()
def tenant_con_portal(session, tenant):
    """El dueño ya configuró la URL de su banca (sin ella, el recado corta honesto)."""
    tenant.config = {
        **(tenant.config or {}),
        CUA_PORTALES_KEY: {"confirmacion_pago": "https://banca.example/acceso"},
    }
    session.flush()
    return tenant


class FakeCuaOK:
    """Runner CUA que 'ejecutó' y devolvió datos (simula el portal ya operado)."""

    def __init__(self, data, evidence=None):
        self._data = data
        self._evidence = evidence or []
        self.misiones = []  # las misiones que recibió, para asserts

    async def run(self, mission):
        self.misiones.append(mission)
        return MissionResult(success=True, data=self._data, evidence=self._evidence)


class FakeCuaSinBackend:
    """Un servidor sin el extra `cua`: el runner responde 'no instalado'."""

    async def run(self, mission):
        return MissionResult(
            success=False, error="El navegador del asistente no está instalado (extra `cua`)."
        )


def test_sync_cua_mapea_depositos_a_pagos_pendientes(session, tenant_con_portal):
    tenant = tenant_con_portal
    runner = FakeCuaOK(
        {
            "depositos": [
                {"fecha": "2026-07-01", "monto": 1500, "concepto": "SPEI Aurora"},
                {"fecha": "2026-07-02", "monto": 800, "concepto": "deposito"},
            ]
        },
        evidence=["/cap/captura1.png"],
    )
    report = sync_cua(session, tenant, "confirmacion_pago", runner=runner, today=date(2026, 7, 3))
    assert report.pagos_por_conciliar == 2
    assert any(f.startswith("cua:") for f in report.fuentes)  # procedencia CUA
    pagos = session.scalars(select(Payment).where(Payment.tenant_id == tenant.id)).all()
    assert {float(p.amount) for p in pagos} == {1500.0, 800.0}
    p = next(p for p in pagos if float(p.amount) == 1500.0)
    assert p.source == "cua:banca" and p.status == "pendiente"  # Diego propone, no cierra
    assert p.meta["origen"] == "cua" and "evidencia_capturas" in p.meta


def test_run_cua_mission_registra_recado_done(session, tenant_con_portal):
    tenant = tenant_con_portal
    from aiuda_core.cua.fallback import run_cua_mission

    runner = FakeCuaOK({"depositos": [{"fecha": "2026-07-01", "monto": 1500}]})
    recado = run_cua_mission(session, tenant, "confirmacion_pago", runner=runner)
    assert recado.id and recado.status == "done"
    assert recado.capacidad == "confirmacion_pago" and recado.sistema  # portal nombrado
    assert recado.data == {"depositos": [{"fecha": "2026-07-01", "monto": 1500}]}
    assert recado.started_at is not None and recado.finished_at is not None


def test_run_cua_mission_failed_sin_backend(session, tenant_con_portal):
    tenant = tenant_con_portal
    from aiuda_core.cua.fallback import run_cua_mission

    recado = run_cua_mission(session, tenant, "confirmacion_pago", runner=FakeCuaSinBackend())
    assert recado.status == "failed" and recado.error  # dice por que, no inventa datos


def test_sync_cua_no_duplica_en_recorridas(session, tenant_con_portal):
    tenant = tenant_con_portal
    runner = FakeCuaOK({"depositos": [{"fecha": "2026-07-01", "monto": 1500, "concepto": "x"}]})
    sync_cua(session, tenant, "confirmacion_pago", runner=runner)
    segunda = sync_cua(session, tenant, "confirmacion_pago", runner=runner)
    assert segunda.pagos_por_conciliar == 0  # mismo monto+fuente: no duplica


def test_sync_cua_sin_backend_es_noop_honesto(session, tenant_con_portal):
    tenant = tenant_con_portal
    report = sync_cua(session, tenant, "confirmacion_pago", runner=FakeCuaSinBackend())
    assert report.pagos_por_conciliar == 0
    assert report.fuentes == []  # no inventa procedencia
    assert session.scalars(select(Payment).where(Payment.tenant_id == tenant.id)).all() == []


def test_recado_sin_url_de_portal_corta_honesto(session, tenant):
    """Banca y tribunal no traen URL en la plantilla (cada negocio tiene la suya): sin
    configurarla, el recado falla con la razon exacta SIN abrir navegador ni gastar IA."""
    from aiuda_core.cua.fallback import run_cua_mission

    runner = FakeCuaOK({"depositos": []})
    recado = run_cua_mission(session, tenant, "confirmacion_pago", runner=runner)
    assert recado.status == "failed"
    assert "dirección configurada" in (recado.error or "")
    assert CUA_PORTALES_KEY in (recado.error or "")  # dice DONDE configurarla
    assert runner.misiones == []  # nunca llego al runner


def test_url_del_portal_del_tenant_llega_a_la_mision(session, tenant_con_portal):
    from aiuda_core.cua.fallback import run_cua_mission

    runner = FakeCuaOK({"depositos": []})
    run_cua_mission(session, tenant_con_portal, "confirmacion_pago", runner=runner)
    assert runner.misiones[0].url_inicio == "https://banca.example/acceso"


def test_instruccion_del_dueno_llega_a_las_notas_de_la_mision(session, tenant_con_portal):
    """El ciclo de la indicación: Mission.objetivo + data._instruccion -> notas de la
    misión -> prompt del agente (build_mission_prompt lee las notas)."""
    from aiuda_core.cua.fallback import ejecutar_recado, enqueue_cua_mission
    from aiuda_core.cua.mission import build_mission_prompt

    runner = FakeCuaOK({"depositos": []})
    recado = enqueue_cua_mission(
        session, tenant_con_portal, "confirmacion_pago",
        instruccion="Solo los depositos mayores a $5,000",
    )
    ejecutar_recado(session, recado, runner=runner)
    mission = runner.misiones[0]
    assert "Solo los depositos mayores a $5,000" in mission.notas
    assert "Instrucción específica del dueño" in mission.notas
    assert "Solo los depositos mayores a $5,000" in build_mission_prompt(mission)
    # y la instrucción se preserva en el log del recado
    assert recado.data.get("_instruccion") == "Solo los depositos mayores a $5,000"


def test_sync_cua_capacidad_sin_plantilla_no_hace_nada(session, tenant):
    # cuentas_por_cobrar tiene conectores API: no hay plantilla CUA -> no-op sin runner
    report = sync_cua(session, tenant, "cuentas_por_cobrar")
    assert report.fuentes == [] and report.pagos_por_conciliar == 0


def test_cua_usa_la_ia_del_tenant_suscripcion_o_apikey(session, tenant, monkeypatch):
    """CUA corre con la PROPIA IA del tenant. Con suscripcion combina la beta OAuth con la
    de computer-use en un solo header; con API key, solo computer-use."""
    import aiuda_core.engine.provider as prov
    from aiuda_core.cua import fallback as fb
    from aiuda_core.engine.provider import OAUTH_BETA, ProviderCredential

    COMPUTER_BETA = "computer-use-2025-01-24"

    from aiuda_core.config import settings
    from aiuda_core.engine.provider import CLAUDE_CODE_IDENTITY

    monkeypatch.setattr(prov, "resolve_credential", lambda **kw: ProviderCredential("claude", "subscription", "tok"))
    r = fb._runner_para_tenant(session, tenant)
    assert r.betas == [OAUTH_BETA, COMPUTER_BETA]  # ambas betas
    assert r._client is not None  # cliente async armado con el token de suscripcion
    assert r.model == settings.model_redaccion_suscripcion  # haiku: la suscripcion no aguanta sonnet
    assert r._system == CLAUDE_CODE_IDENTITY  # OAuth exige la identidad en system

    monkeypatch.setattr(prov, "resolve_credential", lambda **kw: ProviderCredential("claude", "api_key", "sk-x"))
    api = fb._runner_para_tenant(session, tenant)
    assert api.betas == [COMPUTER_BETA]
    assert api._system is None  # api_key no lleva el prefijo de identidad

    monkeypatch.setattr(prov, "resolve_credential", lambda **kw: None)
    assert fb._runner_para_tenant(session, tenant) is not None  # cae al runner por defecto


def test_sync_fuentes_enruta_a_cua_cuando_el_dueno_lo_elige(session, tenant, monkeypatch):
    import aiuda_core.cua.fallback as fb
    from aiuda_core.engine.sync import SyncReport, sync_fuentes

    visto = {}

    def fake_sync_cua(s, t, cap, today=None):
        visto["cap"] = cap
        r = SyncReport()
        r.fuentes.append("cua:test")
        return r

    monkeypatch.setattr(fb, "sync_cua", fake_sync_cua)
    r = sync_fuentes(session, tenant, fuente_prefs={"cfdi": "cua"})
    assert visto.get("cap") == "cfdi"  # se enrutó al lector CUA de esa capacidad
    assert "cua:test" in r.fuentes
