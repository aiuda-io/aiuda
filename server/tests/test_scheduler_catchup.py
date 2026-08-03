"""La corrida horaria se pone al día cuando la laptop estuvo dormida.

El bucle solo disparaba con ``now.minute == 0``: si el hilo no despertaba en ese
minuto exacto —y una laptop que se cierra a las 7 y se abre a las 11 no despierta
en ninguno— esa hora se perdía y el resumen diario del dueño no salía. Esto le
pasa TODOS LOS DÍAS a la computadora de un changarro.

La decisión ("¿qué horas faltan por correr?") vive en una función pura, así que
se prueba sin hilos ni relojes falsos.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_server import scheduler
from aiuda_core.models import Base, Tenant


def _ahora(hora: int, minuto: int = 0, dia: int = 27) -> datetime:
    return datetime(2026, 7, dia, hora, minuto, tzinfo=scheduler.MX_TZ)


# --------------------------------------------------------------------------- #
# La decisión, en frío                                                          #
# --------------------------------------------------------------------------- #
def test_primera_corrida_solo_la_hora_actual():
    """Recién instalado no se inventa historia: corre la hora en curso y ya."""
    assert scheduler.horas_pendientes(None, _ahora(9, 40)) == [9]


def test_no_repite_la_hora_ya_corrida():
    assert scheduler.horas_pendientes("2026-07-27T09", _ahora(9, 40)) == []


def test_no_hace_falta_caer_en_el_minuto_cero():
    """El bug de origen: a las 9:07 el bucle viejo no disparaba nada."""
    assert scheduler.horas_pendientes("2026-07-27T08", _ahora(9, 7)) == [9]


def test_laptop_dormida_recupera_las_horas_perdidas():
    """Se cerró a las 7 y se abrió a las 11:15: las 8 (la hora del resumen) entra."""
    assert scheduler.horas_pendientes("2026-07-27T07", _ahora(11, 15)) == [8, 9, 10, 11]


def test_apagada_una_semana_no_dispara_cientos_de_horas():
    horas = scheduler.horas_pendientes("2026-07-20T10", _ahora(11, 5))
    assert len(horas) == 24 and horas[-1] == 11  # un día basta: cubre las 24 del reloj


def test_reloj_hacia_atras_no_corre():
    """Un ajuste de reloj no debe volver a mandar el resumen del día."""
    assert scheduler.horas_pendientes("2026-07-27T15", _ahora(11, 5)) == []


def test_marca_ilegible_arranca_como_si_fuera_la_primera():
    assert scheduler.horas_pendientes("cualquier cosa", _ahora(9, 40)) == [9]


# --------------------------------------------------------------------------- #
# El latido: corre, deja marca y no repite                                      #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def base_local(monkeypatch):
    """Base desechable con el session_scope REAL apuntando a ella."""
    from aiuda_core import db as core_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_sessionmaker", lambda: SessionLocal)
    return SessionLocal


def _negocio(SessionLocal) -> str:
    with SessionLocal() as s:
        t = Tenant(name="T", owner_phone="5215500000000", evolution_instance="i", config={})
        s.add(t)
        s.commit()
        return t.id


def test_el_latido_corre_deja_marca_y_no_repite(base_local, monkeypatch):
    SessionLocal = base_local
    tenant_id = _negocio(SessionLocal)
    corridas: list[tuple[int, list[int]]] = []
    monkeypatch.setattr(
        worker_main,
        "run_daily_blocking",
        lambda now, horas_cubiertas=None: corridas.append((now.hour, horas_cubiertas)),
    )

    assert scheduler.latido(_ahora(9, 7)) == [9]
    assert corridas == [(9, [9])]
    with SessionLocal() as s:
        assert s.get(Tenant, tenant_id).config["ultima_corrida_horaria"] == "2026-07-27T09"

    # Otro tick de 30 s dentro de la misma hora: no vuelve a correr.
    assert scheduler.latido(_ahora(9, 37)) == []
    assert len(corridas) == 1

    # La laptop durmió y despertó a las 12:20: se cobran las horas perdidas.
    assert scheduler.latido(_ahora(12, 20)) == [10, 11, 12]
    assert corridas[-1] == (12, [10, 11, 12])


def test_sin_negocio_todavia_el_latido_no_corre_nada(base_local, monkeypatch):
    """Antes del primer arranque de la consola no hay a quién cobrarle."""
    monkeypatch.setattr(
        worker_main, "run_daily_blocking", lambda *a, **k: pytest.fail("no debía correr")
    )
    assert scheduler.latido(_ahora(9, 7)) == []


# --------------------------------------------------------------------------- #
# Lo que de verdad se estaba perdiendo: el resumen del dueño                     #
# --------------------------------------------------------------------------- #
class _EngineResumenALas8:
    def __init__(self, enviados: list[str]):
        self.enviados = enviados

    def run_reminders(self, today):
        return []

    def summary_due(self, hour):
        return hour == 8

    def daily_summary(self, today):
        return "resumen de cartera"

    def send_whatsapp(self, phone, text):
        self.enviados.append(text)


def test_el_resumen_de_las_8_sale_cuando_la_laptop_desperto_a_las_11(base_local, monkeypatch):
    import aiuda_core.engine.sync as sync_mod

    _negocio(base_local)
    enviados: list[str] = []
    monkeypatch.setattr(sync_mod, "sync_fuentes", lambda *a, **k: None)
    monkeypatch.setattr(worker_main, "_process_writebacks", lambda s, t, run=None: None)
    monkeypatch.setattr(worker_main, "_build_engine", lambda s, t, run=None: _EngineResumenALas8(enviados))

    despierta = datetime(2026, 7, 27, 11, 5)
    # Sin decirle qué horas cubre, a las 11 el resumen de las 8 no existe.
    worker_main._run_daily_impl(now=despierta)
    assert enviados == []
    # Con las horas que se durmió la laptop, sale (tarde, pero sale).
    worker_main._run_daily_impl(now=despierta, horas_cubiertas=[8, 9, 10, 11])
    assert enviados == ["resumen de cartera"]
