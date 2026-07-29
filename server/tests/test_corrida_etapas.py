"""La corrida diaria va por etapas, cada una con su transacción.

Antes era UNA sola transacción por tenant que envolvía el sync, el write-back y
todas las llamadas al LLM: un error de red de la IA hacía rollback de TODO (lo
sincronizado se perdía, y peor: el outbox 'done' volvía a 'pending' con el pago
ya asentado en Odoo), y la base quedaba retenida minutos mientras el proveedor
contestaba.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aiuda_server.worker.main as worker_main
from aiuda_core.models import Base, Customer, Invoice, Tenant


@pytest.fixture()
def base_local(monkeypatch):
    """Base in-memory con el session_scope REAL del worker apuntando a ella:
    aquí importan los commits y rollbacks de verdad, no un scope fingido."""
    from aiuda_core import db as core_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(core_db, "get_sessionmaker", lambda: SessionLocal)
    return SessionLocal


class _EngineIACaida:
    def run_reminders(self, today):
        raise ConnectionError("la IA sin red")

    def summary_due(self, hour):
        return False


def test_un_fallo_de_ia_no_revierte_lo_sincronizado(base_local, monkeypatch):
    """El sync mete una factura nueva y DESPUÉS la IA truena con un error de red
    no atrapado. La factura debe sobrevivir: se commiteó en su propia etapa."""
    import aiuda_core.engine.sync as sync_mod

    SessionLocal = base_local
    with SessionLocal() as s:
        t = Tenant(name="T", owner_phone="1", evolution_instance="inst", config={})
        s.add(t)
        s.commit()

    def fake_sync(session, tenant, today=None, fuente_prefs=None):
        c = Customer(tenant_id=tenant.id, name="Nuevo", phone="5215500000001")
        session.add(c)
        session.flush()
        session.add(Invoice(
            tenant_id=tenant.id, customer_id=c.id, folio="F-SYNC", amount=1000,
            currency="MXN", issued_date=date(2026, 7, 1), due_date=date(2026, 7, 31),
            status="open",
        ))

    monkeypatch.setattr(sync_mod, "sync_fuentes", fake_sync)
    monkeypatch.setattr(worker_main, "_process_writebacks", lambda s, t: None)
    monkeypatch.setattr(worker_main, "_build_engine", lambda s, t: _EngineIACaida())

    report = worker_main._run_daily_impl(now=datetime(2026, 7, 27, 10, 5))

    with SessionLocal() as s:
        factura = s.scalar(select(Invoice).where(Invoice.folio == "F-SYNC"))
        assert factura is not None, "el rollback de la IA se llevó lo sincronizado"
    # El tenant falló en su etapa de redacción: no cuenta como procesado completo.
    assert report["tenants"] == 0
