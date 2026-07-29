"""Canal de correo por tenant (channel.py): cada negocio envía por SU cuenta.

- resolve_correo: sin credencial completa (cuenta+contraseña+SMTP) → None (canal
  honesto: sin salida no se promete envío); OAuth guardado pero no cableado → None.
- live_channels: el correo aparece vivo SOLO para el tenant que lo conectó.
- get_channel_sender('correo'): entrega por SMTP con asunto/threading correctos y
  reporta el Message-ID generado (on_sent) para enhebrar el hilo.
"""


from aiuda_core.connectors.channel import (
    CorreoInstance,
    get_channel_sender,
    get_correo_sender,
    live_channels,
    resolve_correo,
)
from aiuda_core.connectors.correo import CorreoClient
from aiuda_core.models import Tenant


def _tenant(session, config=None, name="La Bonita") -> Tenant:
    t = Tenant(
        name=name, owner_phone="5215500000000",
        evolution_instance=f"inst-{name.lower().replace(' ', '-')}", config=config or {},
    )
    session.add(t)
    session.flush()
    return t


def _config_email(**extra) -> dict:
    base = {
        "email": "cobranza@negocio.mx", "password": "app-pass",
        "imap_host": "imap.negocio.mx", "smtp_host": "smtp.negocio.mx", "smtp_port": "465",
    }
    base.update(extra)
    return {"integrations": {"email": base}}


# ---------- resolve_correo ----------

def test_sin_conexion_no_hay_canal_de_correo(session):
    t = _tenant(session)
    assert resolve_correo(session, t) is None
    assert get_correo_sender(None, asunto="X") is None


def test_sin_smtp_no_hay_salida_honesto(session):
    cfg = _config_email()
    del cfg["integrations"]["email"]["smtp_host"]
    t = _tenant(session, cfg)
    assert resolve_correo(session, t) is None  # se puede LEER, pero no prometer envío


def test_oauth_guardado_pero_no_cableado_no_da_canal(session):
    t = _tenant(session, _config_email(auth_method="oauth"))
    assert resolve_correo(session, t) is None  # honesto: XOAUTH2 aún no existe


def test_correo_completo_da_instancia_con_nombre_del_negocio(session):
    t = _tenant(session, _config_email())
    correo = resolve_correo(session, t)
    assert isinstance(correo, CorreoInstance)
    assert correo.creds["email"] == "cobranza@negocio.mx"
    assert correo.nombre == "La Bonita"  # From amable: "La Bonita <cobranza@...>"
    cliente = correo.client()
    assert isinstance(cliente, CorreoClient) and cliente.smtp_port == 465


# ---------- live_channels ----------

def test_live_channels_por_tenant(session):
    con = _tenant(session, _config_email(), name="Con Correo")
    sin = _tenant(session, name="Sin Correo")
    assert live_channels(session, con) == {"whatsapp", "correo"}
    assert live_channels(session, sin) == {"whatsapp"}


# ---------- sender ----------

def test_get_channel_sender_correo_envia_con_threading(session, monkeypatch):
    t = _tenant(session, _config_email())
    enviados: list[dict] = []

    def fake_send(self, para, asunto, texto, in_reply_to="", references=(), de_nombre=""):
        enviados.append({
            "para": para, "asunto": asunto, "texto": texto,
            "irt": in_reply_to, "refs": tuple(references), "nombre": de_nombre,
        })
        return "<generado@negocio.mx>"

    monkeypatch.setattr(CorreoClient, "send", fake_send)
    reportados: list[str] = []
    sender = get_channel_sender(
        "correo", None,
        correo=resolve_correo(session, t),
        correo_opts={
            "asunto": "Re: Factura F-102",
            "in_reply_to": "<m1@cliente.mx>",
            "references": ["<m1@cliente.mx>"],
            "on_sent": reportados.append,
        },
    )
    sender("ana@cliente.mx", "Va de nuevo la factura.")
    [e] = enviados
    assert e["para"] == "ana@cliente.mx" and e["asunto"] == "Re: Factura F-102"
    assert e["irt"] == "<m1@cliente.mx>" and e["refs"] == ("<m1@cliente.mx>",)
    assert e["nombre"] == "La Bonita"
    assert reportados == ["<generado@negocio.mx>"]  # el caller enhebra el hilo con esto


def test_get_channel_sender_sin_canal_o_sms_devuelve_none(session):
    assert get_channel_sender("correo", None, correo=None) is None
    assert get_channel_sender("sms", None) is None
