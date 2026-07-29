"""El motor construye cada conector con las credenciales DEL TENANT (vía el
resolver), no con settings globales. Probamos que:
  - el cliente se arma con las credenciales del tenant (config legado o fila),
  - los argumentos del ctor son los correctos (belvo_link_id queda fuera del ctor),
  - un tenant sin credenciales no usa las de otro (aislamiento cross-tenant).

Se reemplaza la clase del conector por una grabadora que captura los kwargs del
constructor y no toca la red.
"""

import pytest

from aiuda_core.engine import sync


class _Recorder:
    """Conector falso: guarda los kwargs del ctor y responde vacío a los listados."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inflow_args = None

    # comercio / directorio / catálogo
    def list_unpaid_orders(self):
        return []

    def list_customers(self):
        return []

    def list_products(self):
        return []

    def fetch_open_invoices(self):
        return []

    def fetch_partners(self):
        return []

    def fetch_products(self):
        return []

    def fetch_purchase_orders(self):
        return []

    # crm / prospección / agenda / cfdi
    def list_contacts(self):
        return []

    def list_open_deals(self):
        return []

    def list_events(self):
        return []

    def list_cfdis(self):
        return []

    def list_invoices(self):
        return []

    # banca / pagos
    def list_inflows(self, link_id, since, until):
        self.inflow_args = (link_id, since, until)
        return []

    def match_payment(self, *_):
        return None

    def list_recent_charges(self):
        return []


def _patch(monkeypatch, module_path: str, cls_name: str) -> list:
    """Reemplaza ``module.cls_name`` por la grabadora; devuelve la lista de
    instancias creadas para inspeccionar sus kwargs."""
    import importlib

    made: list[_Recorder] = []

    def factory(**kwargs):
        rec = _Recorder(**kwargs)
        made.append(rec)
        return rec

    module = importlib.import_module(module_path)
    monkeypatch.setattr(module, cls_name, factory)
    return made


def test_sync_pedidos_usa_credenciales_del_tenant(session, tenant, monkeypatch):
    made = _patch(monkeypatch, "aiuda_core.connectors.shopify", "ShopifyClient")
    tenant.config = {
        "integrations": {"shopify": {"store_domain": "mi.myshopify.com", "access_token": "shpat_x"}}
    }
    session.add(tenant)
    session.flush()
    sync.sync_pedidos(session, tenant)
    assert len(made) == 1
    assert made[0].kwargs == {"store_domain": "mi.myshopify.com", "access_token": "shpat_x"}


def test_sync_pedidos_sin_credenciales_no_construye(session, tenant, monkeypatch):
    made = _patch(monkeypatch, "aiuda_core.connectors.shopify", "ShopifyClient")
    sync.sync_pedidos(session, tenant)  # config vacía, sin settings
    assert made == []


def test_aislamiento_cross_tenant_en_el_motor(session, tenant, monkeypatch):
    """Un segundo tenant SIN credenciales no hereda las del primero."""
    from aiuda_core.models import Tenant

    made = _patch(monkeypatch, "aiuda_core.connectors.shopify", "ShopifyClient")
    tenant.config = {
        "integrations": {"shopify": {"store_domain": "a.myshopify.com", "access_token": "tok_a"}}
    }
    session.add(tenant)
    otro = Tenant(name="Otro", owner_phone="9", evolution_instance="otro", config={})
    session.add(otro)
    session.flush()

    sync.sync_pedidos(session, otro)  # otro no tiene credenciales
    assert made == []
    sync.sync_pedidos(session, tenant)
    assert len(made) == 1 and made[0].kwargs["access_token"] == "tok_a"


def test_sync_odoo_usa_credenciales_del_tenant(session, tenant, monkeypatch):
    made = _patch(monkeypatch, "aiuda_core.connectors.odoo", "OdooConnector")
    tenant.config = {
        "odoo": {"url": "https://o", "db": "d", "username": "u", "api_key": "k"}
    }
    session.add(tenant)
    session.flush()
    sync.sync_odoo(session, tenant)
    assert len(made) == 1
    assert made[0].kwargs == {"url": "https://o", "db": "d", "username": "u", "api_key": "k"}


def test_detectar_pagos_belvo_excluye_link_id_del_ctor(session, tenant, monkeypatch):
    made = _patch(monkeypatch, "aiuda_core.connectors.belvo", "BelvoClient")
    tenant.config = {
        "integrations": {
            "belvo": {"base_url": "https://belvo", "secret_id": "sid", "secret_password": "pw"}
        },
        "belvo_link_id": "link-1",
    }
    session.add(tenant)
    session.flush()
    sync.detectar_pagos(session, tenant)
    assert len(made) == 1
    # belvo_link_id NO va al constructor...
    assert "belvo_link_id" not in made[0].kwargs
    assert made[0].kwargs == {
        "base_url": "https://belvo",
        "secret_id": "sid",
        "secret_password": "pw",
    }
    # ...sino al método de consulta.
    assert made[0].inflow_args is not None and made[0].inflow_args[0] == "link-1"


def test_sync_directorio_arma_cada_fuente(session, tenant, monkeypatch):
    odoo = _patch(monkeypatch, "aiuda_core.connectors.odoo", "OdooConnector")
    hub = _patch(monkeypatch, "aiuda_core.connectors.hubspot", "HubSpotClient")
    shop = _patch(monkeypatch, "aiuda_core.connectors.shopify", "ShopifyClient")
    tenant.config = {
        "odoo": {"url": "https://o", "db": "d", "username": "u", "api_key": "k"},
        "integrations": {
            "hubspot": {"token": "hub-tok"},
            "shopify": {"store_domain": "s.myshopify.com", "access_token": "shp"},
        },
    }
    session.add(tenant)
    session.flush()
    sync.sync_directorio(session, tenant)
    assert odoo and hub and shop
    assert hub[0].kwargs == {"token": "hub-tok"}
    assert shop[0].kwargs == {"store_domain": "s.myshopify.com", "access_token": "shp"}


def test_motor_lee_credencial_cifrada(session, tenant, monkeypatch):
    """La fila cifrada (no config en claro) también llega al motor."""
    pytest.importorskip("cryptography")
    from aiuda_core.connectors import credentials as cred

    made = _patch(monkeypatch, "aiuda_core.connectors.stripe_pagos", "StripeClient")
    cred.set_credential(session, tenant.id, "stripe", {"api_key": "sk_cifrada"})
    sync.detectar_pagos(session, tenant)
    assert len(made) == 1 and made[0].kwargs == {"api_key": "sk_cifrada"}
