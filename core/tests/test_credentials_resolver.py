"""Resolver de credenciales por tenant (cifrado + fallback).

La lógica de fallback (settings / tenant.config) se prueba sin cripto. El
round-trip cifrado (set_credential -> get_credential) usa cryptography, así que
se salta con importorskip donde no esté (corre en CI y local con la librería).
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.models import Base, IntegrationCredential, Tenant


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture()
def tenant(session):
    t = Tenant(name="N", owner_phone="1", evolution_instance="inst-cred")
    session.add(t)
    session.flush()
    return t


def test_none_cuando_no_hay_nada(session, tenant):
    assert cred.get_credential(session, tenant.id, "shopify") is None


def test_fallback_a_settings_globales(session, tenant, monkeypatch):
    monkeypatch.setattr(settings, "shopify_store_domain", "mi.myshopify.com")
    monkeypatch.setattr(settings, "shopify_access_token", "shpat_x")
    creds = cred.get_credential(session, tenant.id, "shopify")
    assert creds == {"store_domain": "mi.myshopify.com", "access_token": "shpat_x"}


def test_tenant_config_pisa_a_settings(session, tenant, monkeypatch):
    monkeypatch.setattr(settings, "hubspot_token", "global-token")
    tenant.config = {"integrations": {"hubspot": {"token": "del-tenant"}}}
    session.add(tenant)
    session.flush()
    creds = cred.get_credential(session, tenant.id, "hubspot")
    assert creds == {"token": "del-tenant"}


def test_config_legado_por_clave_directa(session, tenant):
    # Odoo legado vive en tenant.config['odoo'] (no en ['integrations']).
    tenant.config = {"odoo": {"url": "https://o", "db": "d", "username": "u", "api_key": "k"}}
    session.add(tenant)
    session.flush()
    creds = cred.get_credential(session, tenant.id, "odoo")
    assert creds == {"url": "https://o", "db": "d", "username": "u", "api_key": "k"}


# --- Round-trip cifrado (requiere cryptography) ----------------------------- #
@pytest.fixture()
def encryption_key(monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("AIUDA_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    from aiuda_core.security import crypto

    crypto.reset_cache()
    yield
    crypto.reset_cache()


def test_set_then_get_roundtrip(session, tenant, encryption_key):
    cred.set_credential(
        session, tenant.id, "shopify",
        {"store_domain": "mi.myshopify.com", "access_token": "shpat_secreto"},
    )
    creds = cred.get_credential(session, tenant.id, "shopify")
    assert creds == {"store_domain": "mi.myshopify.com", "access_token": "shpat_secreto"}


def test_secreto_no_se_guarda_en_claro(session, tenant, encryption_key):
    cred.set_credential(
        session, tenant.id, "shopify",
        {"store_domain": "mi.myshopify.com", "access_token": "shpat_secreto"},
    )
    row = session.scalars(
        select(IntegrationCredential).where(IntegrationCredential.tenant_id == tenant.id)
    ).first()
    # public_config solo lo no-secreto; el secreto va cifrado, nunca en claro.
    assert row.public_config == {"store_domain": "mi.myshopify.com"}
    assert b"shpat_secreto" not in (row.secret_ciphertext or b"")
    assert row.secret_ciphertext


def test_email_cifra_password_deja_publico_lo_demas(session, tenant, encryption_key):
    # Correo: la contraseña se cifra; provider/correo/servidores quedan en claro (no son
    # secreto). Confirma que el proveedor 'email' quedó bien cableado a la maquinaria.
    cred.set_credential(
        session, tenant.id, "email",
        {
            "provider": "google", "email": "cobranza@n.com",
            "imap_host": "imap.gmail.com", "imap_port": "993",
            "password": "app-pass-secreta",
        },
    )
    row = session.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == "email",
        )
    ).first()
    assert row.public_config == {
        "provider": "google", "email": "cobranza@n.com",
        "imap_host": "imap.gmail.com", "imap_port": "993",
    }
    assert b"app-pass-secreta" not in (row.secret_ciphertext or b"")
    creds = cred.get_credential(session, tenant.id, "email")
    assert creds["password"] == "app-pass-secreta" and creds["provider"] == "google"


def test_cifrado_pisa_al_fallback(session, tenant, encryption_key, monkeypatch):
    monkeypatch.setattr(settings, "stripe_api_key", "sk_global")
    cred.set_credential(session, tenant.id, "stripe", {"api_key": "sk_del_tenant"})
    creds = cred.get_credential(session, tenant.id, "stripe")
    assert creds == {"api_key": "sk_del_tenant"}


def test_precedencia_fila_sobre_config_y_settings(session, tenant, encryption_key, monkeypatch):
    # Las tres vías presentes: gana la fila cifrada.
    monkeypatch.setattr(settings, "hubspot_token", "global")
    tenant.config = {"integrations": {"hubspot": {"token": "del-config"}}}
    session.add(tenant)
    session.flush()
    cred.set_credential(session, tenant.id, "hubspot", {"token": "de-la-fila"})
    assert cred.get_credential(session, tenant.id, "hubspot") == {"token": "de-la-fila"}


def test_propaga_error_de_descifrado(session, tenant, encryption_key, monkeypatch):
    # Fila cifrada que no descifra (clave retirada): propaga, NO cae a settings —
    # no enmascaramos un fallo de seguridad con la credencial global.
    from aiuda_core.security import crypto

    monkeypatch.setattr(settings, "stripe_api_key", "sk_global")
    row = cred.set_credential(session, tenant.id, "stripe", {"api_key": "sk_tenant"})
    row.key_version = 99  # versión inexistente en el keyring
    session.add(row)
    session.flush()
    with pytest.raises(crypto.EncryptionError):
        cred.get_credential(session, tenant.id, "stripe")


def test_aislamiento_cross_tenant(session, encryption_key):
    a = Tenant(name="A", owner_phone="1", evolution_instance="a")
    b = Tenant(name="B", owner_phone="2", evolution_instance="b")
    session.add_all([a, b])
    session.flush()
    cred.set_credential(session, a.id, "stripe", {"api_key": "sk_A"})
    assert cred.get_credential(session, a.id, "stripe") == {"api_key": "sk_A"}
    # B no tiene fila ni settings: no hereda la de A.
    assert cred.get_credential(session, b.id, "stripe") is None


def test_belvo_link_id_se_mezcla_y_ctor_lo_excluye(session, tenant, monkeypatch):
    # Secreto desde settings (global), belvo_link_id desde tenant.config top-level:
    # el resolver los une; ctor_kwargs deja fuera belvo_link_id (no es arg del ctor).
    monkeypatch.setattr(settings, "belvo_secret_id", "id-global")
    monkeypatch.setattr(settings, "belvo_secret_password", "pw-global")
    monkeypatch.setattr(settings, "belvo_base_url", "https://belvo")
    tenant.config = {"belvo_link_id": "link-xyz"}
    session.add(tenant)
    session.flush()
    creds = cred.get_credential(session, tenant.id, "belvo")
    assert creds["secret_id"] == "id-global"
    assert creds["belvo_link_id"] == "link-xyz"
    assert "belvo_link_id" not in cred.ctor_kwargs("belvo", creds)
    assert cred.ctor_kwargs("belvo", creds) == {
        "base_url": "https://belvo",
        "secret_id": "id-global",
        "secret_password": "pw-global",
    }


def test_belvo_sin_secreto_no_da_credencial(session, tenant):
    # Solo belvo_link_id en config, sin secreto por ningún lado: no hay cliente.
    tenant.config = {"belvo_link_id": "link-xyz"}
    session.add(tenant)
    session.flush()
    assert cred.get_credential(session, tenant.id, "belvo") is None


def test_has_credential(session, tenant, encryption_key):
    assert cred.has_credential(session, tenant.id, "stripe") is False
    cred.set_credential(session, tenant.id, "stripe", {"api_key": "sk"})
    assert cred.has_credential(session, tenant.id, "stripe") is True


def test_read_stored_solo_lee_la_fila(session, tenant, encryption_key, monkeypatch):
    # read_stored devuelve lo guardado en la fila, sin fallback a settings/config.
    monkeypatch.setattr(settings, "stripe_api_key", "sk_global")
    assert cred.read_stored(session, tenant.id, "stripe") is None
    cred.set_credential(session, tenant.id, "stripe", {"api_key": "sk_fila"})
    assert cred.read_stored(session, tenant.id, "stripe") == {"api_key": "sk_fila"}


def test_provider_desconocido_da_none(session, tenant):
    assert cred.get_credential(session, tenant.id, "inexistente") is None
