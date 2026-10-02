"""El write-back del worker construye sus conectores con las credenciales DEL
TENANT (vía el resolver), no con tenant.config['odoo'] ni settings globales."""

import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Tenant


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


class _Rec:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_writeback_arma_odoo_del_tenant_y_omite_lo_no_configurado(session, monkeypatch):
    from aiuda_server.worker.main import _process_writebacks

    odoo_mod = importlib.import_module("aiuda_core.connectors.odoo")
    monkeypatch.setattr(odoo_mod, "OdooConnector", lambda **kw: _Rec(**kw))

    captured = {}

    def fake_process_outbox(s, t, odoo_client=None, shopify_client=None, gcal_client=None):
        captured["odoo"] = odoo_client
        captured["shopify"] = shopify_client

    wb_mod = importlib.import_module("aiuda_core.engine.writeback")
    monkeypatch.setattr(wb_mod, "process_outbox", fake_process_outbox)

    tenant = Tenant(
        name="N", owner_phone="1", evolution_instance="i",
        config={"odoo": {"url": "https://o", "db": "d", "username": "u", "api_key": "k"}},
    )
    session.add(tenant)
    session.flush()

    _process_writebacks(session, tenant)

    assert isinstance(captured["odoo"], _Rec)
    assert captured["odoo"].kwargs == {
        "url": "https://o", "db": "d", "username": "u", "api_key": "k",
    }
    # Shopify no está configurado para este tenant (ni settings): no se construye.
    assert captured["shopify"] is None


def test_corrida_diaria_aisla_un_tenant_que_falla(session, monkeypatch):
    """Un tenant que revienta en la sincronización no aborta la corrida del resto."""
    from aiuda_server.worker import main as worker

    bueno = Tenant(name="Bueno", owner_phone="1", evolution_instance="b", config={})
    malo = Tenant(name="Malo", owner_phone="2", evolution_instance="m", config={})
    session.add_all([bueno, malo])
    session.flush()

    # session_scope del worker -> nuestra sesión de prueba.
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(worker, "session_scope", fake_scope)
    monkeypatch.setattr(worker, "_build_engine", lambda s, t, run=None: _Engine())

    def fake_sync(s, t, today=None, fuente_prefs=None):
        if t.name == "Malo":
            raise RuntimeError("credencial ilegible")

    # run_daily_blocking importa sync_fuentes localmente: se parchea en su origen.
    import aiuda_core.engine.sync as sync_mod

    monkeypatch.setattr(sync_mod, "sync_fuentes", fake_sync)
    monkeypatch.setattr(worker, "_process_writebacks", lambda s, t, run=None: None)

    report = worker.run_daily_blocking()
    # El bueno se procesó pese a que el malo falló.
    assert report["tenants"] == 1


class _Engine:
    def run_reminders(self, today):
        return []

    def summary_due(self, hour):
        return False


def test_run_daily_omite_si_ya_hay_una_corriendo(monkeypatch):
    import aiuda_server.worker.main as worker

    # Otra corrida tiene el lock: la segunda se omite sin ejecutar la corrida real.
    assert worker._daily_lock.acquire(blocking=False)
    try:
        called: list = []
        monkeypatch.setattr(worker, "_run_daily_impl", lambda now=None: called.append(1))
        assert worker.run_daily_blocking() == {"skipped": True}
        assert called == []  # no se disparó la corrida duplicada
    finally:
        worker._daily_lock.release()


def test_run_daily_libera_el_lock_al_terminar(monkeypatch):
    import aiuda_server.worker.main as worker

    monkeypatch.setattr(
        worker, "_run_daily_impl", lambda now=None, horas_cubiertas=None: {"ok": True}
    )
    assert worker.run_daily_blocking() == {"ok": True}
    # el lock quedó libre para la siguiente corrida
    assert worker._daily_lock.acquire(blocking=False)
    worker._daily_lock.release()
