"""Tope de gasto de IA y metering, versión local.

En local no hay planes ni suscripciones: el tope es del dueño
(``config["ia_tope_tokens_mes"]``), pero NO empieza en infinito — hay un tope de
fábrica para que una corrida atorada no le deje una factura sorpresa con su
proveedor el día 1. Se prueba el corte HONESTO: con el tope agotado la llamada
al proveedor NO sale — ni a media corrida — y el metering registra un UsageEvent
por llamada.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_server import costs, metering
from aiuda_core.config import settings
from aiuda_core.engine.llm import BudgetExceeded, ClaudeRunner
from aiuda_core.models import Base, Tenant, UsageEvent


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


# --------------------------------------------------------------------------- #
# Fakes del cliente Anthropic (mismo contrato que core/tests/conftest.py)      #
# --------------------------------------------------------------------------- #
class _Usage:
    input_tokens = 100
    output_tokens = 50


class _TextBlock:
    type = "text"
    text = "hola"


class _Response:
    content = [_TextBlock()]
    stop_reason = "end_turn"
    usage = _Usage()


class _FakeMessages:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return _Response()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _tenant(db, *, config=None) -> Tenant:
    t = Tenant(
        name="Demo",
        owner_phone="52155",
        evolution_instance="demo",
        config={"demo": True, **(config or {})},
    )
    db.add(t)
    db.flush()
    return t


def _gastar(db, tenant_id: str, tokens: int) -> None:
    db.add(
        UsageEvent(
            tenant_id=tenant_id, model="claude-haiku-4-5", task="corrida",
            input_tokens=tokens, output_tokens=0,
        )
    )
    db.flush()


def _runner(db, tenant) -> tuple[ClaudeRunner, _FakeClient]:
    """Runner como el de metering.tenant_runner pero con cliente falso (sin red)."""
    fake = _FakeClient()
    runner = ClaudeRunner(
        client=fake,
        usage_callback=metering.usage_recorder(db, tenant.id),
        budget_check=metering.budget_check(db, tenant),
    )
    return runner, fake


# --------------------------------------------------------------------------- #
# Metering: cada llamada deja UsageEvent                                        #
# --------------------------------------------------------------------------- #
def test_metering_registra_usage_event_por_llamada(db_session):
    t = _tenant(db_session)
    runner, fake = _runner(db_session, t)
    runner.complete(system="s", user="u", task="prueba")
    db_session.flush()
    events = db_session.scalars(
        select(UsageEvent).where(UsageEvent.tenant_id == t.id)
    ).all()
    assert len(events) == 1
    assert events[0].task == "prueba"
    assert events[0].input_tokens == 100 and events[0].output_tokens == 50
    assert len(fake.messages.requests) == 1


def test_usage_mensual_solo_cuenta_el_mes(db_session):
    t = _tenant(db_session)
    _gastar(db_session, t.id, 400)
    viejo = UsageEvent(
        tenant_id=t.id, model="claude-haiku-4-5", task="corrida",
        input_tokens=999_999, output_tokens=0,
    )
    viejo.created_at = datetime.now(timezone.utc) - timedelta(days=62)
    db_session.add(viejo)
    db_session.flush()
    assert costs.tokens_this_month(db_session, t.id) == 400


# --------------------------------------------------------------------------- #
# Tope de fábrica: protege desde el día 1, sin que el dueño configure nada       #
# --------------------------------------------------------------------------- #
def test_sin_configurar_hay_tope_de_fabrica(db_session):
    """El dueño que no puso tope NO queda sin freno: el default lo cubre."""
    t = _tenant(db_session)
    verdict = costs.ia_budget(db_session, t)
    assert verdict["limite"] == costs.DEFAULT_TOPE_TOKENS_MES
    assert verdict["fuente"] == "default" and not verdict["agotado"]


def test_tope_de_fabrica_corta_la_factura_sorpresa(db_session):
    """Una corrida atorada quema tokens sin parar: sin tope propio, el de fábrica
    corta igual (este es el día 1 de un negocio que nunca abrió los ajustes)."""
    t = _tenant(db_session)
    _gastar(db_session, t.id, costs.DEFAULT_TOPE_TOKENS_MES)
    runner, fake = _runner(db_session, t)
    with pytest.raises(BudgetExceeded) as exc:
        runner.complete(system="s", user="u", task="corte")
    assert "tope de fábrica" in str(exc.value)
    assert fake.messages.requests == []


def test_tope_en_cero_es_sin_tope_explicito(db_session):
    """Quien de verdad no quiere tope lo dice con un 0, y entonces nada corta."""
    t = _tenant(db_session, config={"ia_tope_tokens_mes": 0})
    _gastar(db_session, t.id, 10_000_000)
    verdict = costs.ia_budget(db_session, t)
    assert verdict["limite"] is None and verdict["fuente"] is None
    assert not verdict["agotado"]
    runner, fake = _runner(db_session, t)
    runner.complete(system="s", user="u", task="ok")
    assert len(fake.messages.requests) == 1


def test_tope_propio_agotado_corta_sin_llamar(db_session):
    t = _tenant(db_session, config={"ia_tope_tokens_mes": 1000})
    _gastar(db_session, t.id, 1000)
    runner, fake = _runner(db_session, t)
    with pytest.raises(BudgetExceeded) as exc:
        runner.complete(system="s", user="u", task="corte")
    assert "tope personal" in str(exc.value)
    # La llamada NUNCA salió y no se registró consumo nuevo.
    assert fake.messages.requests == []
    events = db_session.scalars(
        select(UsageEvent).where(UsageEvent.tenant_id == t.id, UsageEvent.task == "corte")
    ).all()
    assert events == []


def test_tope_se_agota_a_media_corrida(db_session):
    t = _tenant(db_session, config={"ia_tope_tokens_mes": 120})
    runner, fake = _runner(db_session, t)
    # 1a llamada pasa (0 < 120); registra 150 tokens → la 2a ya no sale.
    runner.complete(system="s", user="u", task="paso1")
    with pytest.raises(BudgetExceeded):
        runner.complete(system="s", user="u", task="paso2")
    assert len(fake.messages.requests) == 1
