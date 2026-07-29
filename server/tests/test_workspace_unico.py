"""El primer arranque crea UN solo workspace, aunque lleguen varias peticiones
a la vez. Sin esto el dueño terminaba con "Mi negocio" repetido y sus datos
repartidos entre negocios fantasma (pasó de verdad en el primer .app).

La base es un ARCHIVO y cada hilo trae su propia conexión, como en la vida
real. Con una sola conexión compartida (StaticPool) el test medía otra cosa y
fallaba solo a veces en CI.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from aiuda_core.config import settings
from aiuda_core.models import Base, Tenant
from aiuda_server.api.deps import get_workspace


@pytest.fixture()
def sessionmaker_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'aiuda.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_peticiones_concurrentes_crean_un_solo_workspace(sessionmaker_local, monkeypatch):
    monkeypatch.setattr(settings, "workspace_id", "")

    def pedir():
        db = sessionmaker_local()
        try:
            tenant = get_workspace(db)
            db.commit()
            return tenant.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: pedir(), range(8)))

    db = sessionmaker_local()
    total = db.scalar(select(func.count()).select_from(Tenant))
    db.close()
    assert total == 1
    assert len(set(ids)) == 1


def test_la_sesion_que_ya_leyo_no_crea_un_segundo(sessionmaker_local, monkeypatch):
    """El caso feo: una sesión lee la base vacía, otra crea el workspace, y la
    primera llega tarde al candado. Debe encontrar el que ya existe."""
    monkeypatch.setattr(settings, "workspace_id", "")
    tarde = sessionmaker_local()
    tarde.scalars(select(Tenant)).first()  # ya leyó: base vacía

    temprano = sessionmaker_local()
    creado = get_workspace(temprano)
    temprano.commit()

    encontrado = get_workspace(tarde)
    tarde.commit()

    db = sessionmaker_local()
    total = db.scalar(select(func.count()).select_from(Tenant))
    db.close()
    assert encontrado.id == creado.id and total == 1


def test_workspace_existente_no_se_duplica(sessionmaker_local, monkeypatch):
    monkeypatch.setattr(settings, "workspace_id", "")
    db = sessionmaker_local()
    primero = get_workspace(db)
    db.commit()
    segundo = get_workspace(db)
    db.commit()
    total = db.scalar(select(func.count()).select_from(Tenant))
    db.close()
    assert primero.id == segundo.id and total == 1
