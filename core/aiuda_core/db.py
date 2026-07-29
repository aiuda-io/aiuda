import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from aiuda_core.config import settings
from aiuda_core.models.base import Base

log = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def default_data_dir() -> Path:
    """Carpeta de datos local (~/.aiuda). Se crea al primer uso."""
    path = Path.home() / ".aiuda"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolved_database_url() -> str:
    """La URL efectiva: la del entorno si está puesta; si no, SQLite local."""
    if settings.database_url:
        return settings.database_url
    return f"sqlite:///{default_data_dir() / 'aiuda.db'}"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine():
    global _engine
    if _engine is None:
        url = resolved_database_url()
        if _is_sqlite(url):
            # check_same_thread=False: FastAPI atiende cada request en su hilo y
            # los jobs del scheduler corren en otro; SQLAlchemy serializa el
            # acceso por conexión. WAL: lecturas no bloquean escrituras.
            _engine = create_engine(
                url, connect_args={"check_same_thread": False}, pool_pre_ping=True
            )

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
        else:
            _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _crear_indices_faltantes(engine) -> None:
    """Crea los índices que falten sobre tablas que YA existían.

    ``metadata.create_all`` hace su checkfirst POR TABLA: si la tabla existe, ni
    la mira, y un índice agregado después nunca se crea. El resultado sería que
    el índice solo lo tienen las instalaciones nuevas, y quien lleva meses usando
    aiuda —el único que ya tiene datos suficientes para notarlo— se queda sin él.
    Sin Alembic, este es el lugar.

    Un índice que no se puede crear no es motivo para no arrancar: es velocidad,
    no corrección. Se registra y se sigue.
    """
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            try:
                with engine.begin() as conn:
                    index.create(bind=conn, checkfirst=True)
            except Exception:  # noqa: BLE001 — sin el índice aiuda sirve, más lento
                log.warning("no se pudo crear el índice %s", index.name, exc_info=True)


def create_all(engine=None) -> None:
    """Crea las tablas y los índices que falten. Es el único 'migrador' local: el
    esquema se declara en los modelos y aquí se materializa de forma idempotente."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    _crear_indices_faltantes(engine)
