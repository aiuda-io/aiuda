from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aiuda_core.models import Base, Customer, Invoice, Tenant


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture()
def tenant(session) -> Tenant:
    t = Tenant(
        name="Hanova Consulting",
        owner_phone="5215512345678",
        evolution_instance="labonita",
        config={},
    )
    session.add(t)
    session.flush()
    return t


@pytest.fixture()
def customer(session, tenant) -> Customer:
    c = Customer(tenant_id=tenant.id, name="Cliente Demo", phone="5215587654321")
    session.add(c)
    session.flush()
    return c


@pytest.fixture()
def invoice(session, tenant, customer) -> Invoice:
    inv = Invoice(
        tenant_id=tenant.id,
        customer_id=customer.id,
        folio="F-001",
        amount=12500.50,
        issued_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
    )
    session.add(inv)
    session.flush()
    return inv


class FakeUsage:
    input_tokens = 100
    output_tokens = 50


class FakeTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn", content=None):
        self.content = content or [FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeMessages:
    """Devuelve respuestas en orden; registra cada request para asserts."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture()
def fake_client_factory():
    def factory(*responses):
        return FakeAnthropicClient(responses)

    return factory
