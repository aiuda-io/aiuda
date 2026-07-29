"""Los índices de las dos consultas calientes, y que lleguen a quien ya usaba aiuda.

Dos consultas se degradan solas con el uso:

- el dedupe de WhatsApp entrante (``inbound.ingresar_entrante``) busca por
  ``wa_message_id`` cada 20 segundos, contra una tabla de mensajes que solo crece;
- el tope de IA (``costs.tokens_this_month``) re-suma los eventos de uso del mes
  ANTES de cada llamada al LLM.

La trampa: ``Base.metadata.create_all`` hace su checkfirst POR TABLA. Sobre una
instalación que ya venía usando aiuda las tablas existen, así que un índice nuevo
nunca se crearía: solo lo tendría quien instala de cero. Sin Alembic, esto es lo
único que hay para materializarlo.
"""

from sqlalchemy import create_engine, inspect, text

from aiuda_core.db import create_all
from aiuda_core.models import Base

IX_MENSAJES = "ix_messages_tenant_wa_id"
IX_USO = "ix_usage_events_tenant_created"


def _indices(engine, tabla: str) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes(tabla)}


def _base_vieja(tmp_path, *, sin_indices=()):
    """Una instalación que ya existía: tablas creadas y sin los índices nuevos."""
    engine = create_engine(f"sqlite:///{tmp_path / 'aiuda.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for nombre in sin_indices:
            conn.execute(text(f"DROP INDEX {nombre}"))
    return engine


def test_las_consultas_calientes_tienen_su_indice_declarado():
    mensajes = {ix.name for ix in Base.metadata.tables["messages"].indexes}
    uso = {ix.name for ix in Base.metadata.tables["usage_events"].indexes}
    assert IX_MENSAJES in mensajes
    assert IX_USO in uso


def test_create_all_agrega_los_indices_a_una_base_que_ya_existia(tmp_path):
    engine = _base_vieja(tmp_path, sin_indices=(IX_MENSAJES, IX_USO))
    assert IX_MENSAJES not in _indices(engine, "messages")
    assert IX_USO not in _indices(engine, "usage_events")

    create_all(engine)

    assert IX_MENSAJES in _indices(engine, "messages")
    assert IX_USO in _indices(engine, "usage_events")


def test_create_all_se_puede_correr_muchas_veces(tmp_path):
    """Corre en cada arranque: repetirlo no puede tronar ni duplicar nada."""
    engine = _base_vieja(tmp_path)
    create_all(engine)
    create_all(engine)
    assert IX_MENSAJES in _indices(engine, "messages")
