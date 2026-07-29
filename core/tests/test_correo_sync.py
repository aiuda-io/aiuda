"""Ingesta de correo a la bandeja unificada (sync_correo): solo remitentes que cruzan
con un cliente por email, threading por References y por remitente+asunto, idempotencia
por Message-ID, siembra sin encolar propuestas, y estado del buzón en Tenant.config."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from aiuda_core.connectors.correo import CorreoEntrante, clave_hilo
from aiuda_core.engine.correo import (
    CORREO_ESTADO_KEY,
    CORREO_HILOS_KEY,
    CORREO_PENDIENTES_KEY,
    hilo_meta,
    hilo_para_envio,
    registrar_saliente,
    reply_headers,
    sync_correo,
)
from aiuda_core.engine.sync import sync_fuentes
from aiuda_core.models import Conversation, Customer, IntegrationCredential, Message

# ---------- infra: credencial + cliente fake ----------


@pytest.fixture()
def con_credencial(session, tenant, monkeypatch):
    """Credencial de correo del tenant SIN cifrado (vía legado tenant.config): la
    resolución real (fila cifrada → legado → settings) ya está probada en
    test_credentials_resolver; aquí interesa la ingesta."""
    tenant.config = {
        **(tenant.config or {}),
        "integrations": {
            "email": {
                "provider": "imap",
                "email": "cobranza@negocio.mx",
                "password": "app-pass",
                "imap_host": "imap.negocio.mx",
                "smtp_host": "smtp.negocio.mx",
            }
        },
    }
    session.add(tenant)
    session.flush()
    return tenant


class FakeCorreoClient:
    """Fake del CONECTOR (no de imaplib): entrega CorreoEntrante ya parseados.
    El protocolo IMAP/parseo se prueba en test_correo_connector."""

    def __init__(self, entrantes, sembrando=False, estado=None, error=None):
        self.entrantes = list(entrantes)
        self.sembrando = sembrando
        self.estado = estado or {"buzon": "INBOX", "uidvalidity": 3, "last_uid": 9}
        self.error = error

    def fetch_nuevos(self, estado=None, hoy=None, cap=100):
        if self.error is not None:
            raise self.error
        return list(self.entrantes), dict(self.estado), self.sembrando


def _correo(
    uid=1,
    mid="<m1@cliente.mx>",
    de="ana@cliente.mx",
    nombre="Ana López",
    asunto="Factura F-102",
    texto="¿Me reenvías la factura?",
    irt="",
    refs=(),
):
    return CorreoEntrante(
        uid=uid, message_id=mid, from_email=de, from_name=nombre,
        subject=asunto, text=texto, in_reply_to=irt, references=tuple(refs),
    )


@pytest.fixture()
def ana(session, tenant) -> Customer:
    c = Customer(tenant_id=tenant.id, name="Ana López", email="Ana@Cliente.mx")
    session.add(c)
    session.flush()
    return c


# ---------- ingesta ----------


def test_ingesta_solo_clientes_y_asienta_hilo(session, con_credencial, ana):
    tenant = con_credencial
    cliente = FakeCorreoClient([
        _correo(),  # de Ana (cliente, cruza aunque el email guardado tenga mayúsculas)
        _correo(uid=2, mid="<spam@x.mx>", de="promo@spam.mx", asunto="OFERTA"),
        _correo(uid=3, mid="<yo@n.mx>", de="cobranza@negocio.mx", asunto="enviado propio"),
    ])
    report = sync_correo(session, tenant, client=cliente)
    assert report.correos_importados == 1 and report.fuentes == ["email"]

    conv = session.scalar(select(Conversation).where(Conversation.tenant_id == tenant.id))
    assert conv.channel == "correo"
    assert conv.remote_phone == clave_hilo("ana@cliente.mx", "Factura F-102")
    [msg] = session.scalars(select(Message).where(Message.conversation_id == conv.id)).all()
    assert msg.direction == "in" and msg.wa_message_id == "<m1@cliente.mx>"
    assert "factura" in msg.body
    # Metadatos del hilo y estado del buzón quedan en tenant.config (sin migración).
    assert hilo_meta(tenant, conv.id) == {
        "de": "ana@cliente.mx", "nombre": "Ana López", "asunto": "Factura F-102",
    }
    assert tenant.config[CORREO_ESTADO_KEY]["last_uid"] == 9
    # No fue siembra: la respuesta propuesta queda encolada para el worker.
    assert tenant.config[CORREO_PENDIENTES_KEY] == [msg.id]


def test_ingesta_idempotente_por_message_id(session, con_credencial, ana):
    tenant = con_credencial
    cliente = FakeCorreoClient([_correo()])
    sync_correo(session, tenant, client=cliente)
    report = sync_correo(session, tenant, client=cliente)  # re-corrida: mismo correo
    assert report.correos_importados == 0
    assert session.scalar(select(Message).where(Message.tenant_id == tenant.id)) is not None
    assert len(session.scalars(select(Message)).all()) == 1
    assert len(tenant.config[CORREO_PENDIENTES_KEY]) == 1


def test_respuesta_enhebra_por_references_no_por_asunto(session, con_credencial, ana):
    tenant = con_credencial
    sync_correo(session, tenant, client=FakeCorreoClient([_correo()]))
    conv = session.scalar(select(Conversation).where(Conversation.tenant_id == tenant.id))
    # Ana contesta con OTRO asunto pero referenciando el Message-ID original.
    respuesta = _correo(
        uid=2, mid="<m2@cliente.mx>", asunto="(cambió el asunto)",
        irt="<m1@cliente.mx>", refs=("<m1@cliente.mx>",), texto="Va el comprobante",
    )
    sync_correo(session, tenant, client=FakeCorreoClient([respuesta]))
    msgs = session.scalars(select(Message).where(Message.conversation_id == conv.id)).all()
    assert len(msgs) == 2  # mismo hilo
    assert len(session.scalars(select(Conversation)).all()) == 1


def test_mismo_remitente_asunto_con_re_cae_al_mismo_hilo(session, con_credencial, ana):
    tenant = con_credencial
    sync_correo(session, tenant, client=FakeCorreoClient([_correo()]))
    # Sin References (cliente de correo pobre), pero mismo asunto con Re: → misma clave.
    respuesta = _correo(uid=2, mid="<m2@cliente.mx>", asunto="RE: Factura F-102")
    sync_correo(session, tenant, client=FakeCorreoClient([respuesta]))
    assert len(session.scalars(select(Conversation)).all()) == 1
    # Otro tema del mismo remitente → hilo nuevo.
    otro = _correo(uid=3, mid="<m3@cliente.mx>", asunto="Cotización nueva")
    sync_correo(session, tenant, client=FakeCorreoClient([otro]))
    assert len(session.scalars(select(Conversation)).all()) == 2


def test_siembra_puebla_bandeja_sin_encolar_propuestas(session, con_credencial, ana):
    tenant = con_credencial
    cliente = FakeCorreoClient([_correo()], sembrando=True)
    report = sync_correo(session, tenant, client=cliente)
    assert report.correos_importados == 1
    assert tenant.config.get(CORREO_PENDIENTES_KEY, []) == []


def test_sin_credencial_o_con_oauth_es_noop_honesto(session, tenant, con_credencial):
    # OAuth guardado pero no cableado: no se lee (la UI dice qué falta), sin fingir.
    cfg = dict(tenant.config)
    cfg["integrations"]["email"]["auth_method"] = "oauth"
    tenant.config = cfg
    llamado = FakeCorreoClient([_correo()])
    report = sync_correo(session, tenant, client=llamado)
    assert report.correos_importados == 0 and report.fuentes == []


def test_buzon_caido_deja_error_visible_sin_tumbar(session, con_credencial, ana):
    tenant = con_credencial
    cliente = FakeCorreoClient([], error=OSError("imap.negocio.mx: connection refused"))
    report = sync_correo(session, tenant, client=cliente)
    assert report.correos_importados == 0
    assert "connection refused" in tenant.config[CORREO_ESTADO_KEY]["ultimo_error"]
    # Se recupera en la siguiente corrida y el error se limpia.
    sync_correo(session, tenant, client=FakeCorreoClient([_correo()]))
    assert "ultimo_error" not in tenant.config[CORREO_ESTADO_KEY]


def test_sync_fuentes_incluye_el_lector_de_correo(session, con_credencial, ana, monkeypatch):
    """La corrida completa (sync_fuentes) corre sync_correo sin que truene el resto
    (las demás fuentes no tienen credenciales: no-op)."""
    from aiuda_core.connectors.correo import CorreoClient

    monkeypatch.setattr(
        CorreoClient, "fetch_nuevos",
        lambda self, estado=None, hoy=None, cap=100: (
            [_correo()], {"buzon": "INBOX", "uidvalidity": 1, "last_uid": 1}, False,
        ),
    )
    report = sync_fuentes(session, con_credencial)
    assert report.correos_importados == 1
    assert "email" in report.fuentes


# ---------- lado saliente: hilo para envío y headers de respuesta ----------


def test_hilo_para_envio_y_respuesta_del_cliente_cae_al_mismo(session, con_credencial, ana):
    tenant = con_credencial
    conv = hilo_para_envio(
        session, tenant, "ana@cliente.mx", "Ana López", "Recordatorio de pago · F-102"
    )
    registrar_saliente(session, tenant, conv, "Hola Ana, saldo pendiente.", "<r1@negocio.mx>")
    # Ana responde citando nuestro Message-ID: enhebra al MISMO hilo aunque el
    # asunto venga con Re:.
    respuesta = _correo(
        uid=7, mid="<m7@cliente.mx>", asunto="Re: Recordatorio de pago · F-102",
        irt="<r1@negocio.mx>", refs=("<r1@negocio.mx>",), texto="Pago el viernes",
    )
    sync_correo(session, tenant, client=FakeCorreoClient([respuesta]))
    msgs = session.scalars(select(Message).where(Message.conversation_id == conv.id)).all()
    assert [m.direction for m in msgs] == ["out", "in"]

    headers = reply_headers(session, tenant, conv)
    assert headers["para"] == "ana@cliente.mx"
    assert headers["asunto"] == "Re: Recordatorio de pago · F-102"
    assert headers["in_reply_to"] == "<m7@cliente.mx>"  # el último ENTRANTE
    assert headers["references"] == ["<r1@negocio.mx>", "<m7@cliente.mx>"]


def test_registrar_hilo_conserva_el_asunto_original(session, con_credencial, ana):
    tenant = con_credencial
    sync_correo(session, tenant, client=FakeCorreoClient([_correo()]))
    conv = session.scalar(select(Conversation).where(Conversation.tenant_id == tenant.id))
    respuesta = _correo(
        uid=2, mid="<m2@cliente.mx>", asunto="Re: Factura F-102",
        irt="<m1@cliente.mx>", refs=("<m1@cliente.mx>",),
    )
    sync_correo(session, tenant, client=FakeCorreoClient([respuesta]))
    assert hilo_meta(tenant, conv.id)["asunto"] == "Factura F-102"  # el Re: no lo pisa
    assert conv.id in tenant.config[CORREO_HILOS_KEY]


def test_credencial_cifrada_tambien_sirve(session, tenant, ana, monkeypatch):
    """La vía de producción: fila IntegrationCredential cifrada (no config legado)."""
    monkeypatch.setenv("AIUDA_ENCRYPTION_KEYS", "")
    from aiuda_core.connectors import credentials as cred
    from aiuda_core.security import crypto

    monkeypatch.setattr(crypto, "encrypt", lambda s: (s.encode(), 1))
    monkeypatch.setattr(crypto, "decrypt", lambda b, v: b.decode())
    cred.set_credential(
        session, tenant.id, "email",
        {
            "provider": "google", "email": "cobranza@negocio.mx",
            "imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com",
            "password": "app-pass",
        },
    )
    fila = session.scalar(select(IntegrationCredential))
    assert fila.provider == "email"
    report = sync_correo(session, tenant, client=FakeCorreoClient([_correo()]))
    assert report.correos_importados == 1
