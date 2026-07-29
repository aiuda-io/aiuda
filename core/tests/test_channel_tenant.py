"""Canal WhatsApp por tenant: cada negocio envía por SU instancia, nunca por la de otro.

- resolve_whatsapp: sin conexión → None (sin canal no hay envío); wacli en modo mono
  (store default) y multi (store propio por instancia); Cloud API exige credenciales
  cifradas completas.
- Senders: dos tenants wacli usan stores DISTINTOS en el argv (no se cruzan);
  el sender oficial respeta la ventana de 24 h (texto dentro, plantilla fuera,
  error accionable sin plantilla).
"""

import pytest

from aiuda_core.config import settings
from aiuda_core.connectors import channel as channel_mod
from aiuda_core.connectors import wacli as wacli_mod
from aiuda_core.connectors.channel import (
    WhatsAppInstance,
    get_channel_sender,
    get_whatsapp_sender,
    resolve_whatsapp,
    wacli_store_dir,
)
from aiuda_core.connectors.credentials import set_credential
from aiuda_core.models import Tenant


def _tenant(session, name, instance, config=None) -> Tenant:
    t = Tenant(
        name=name, owner_phone="5215500000000", evolution_instance=instance,
        config=config or {},
    )
    session.add(t)
    session.flush()
    return t


# ---------- resolve_whatsapp ----------

def test_sin_conexion_no_hay_instancia_ni_sender(session):
    t = _tenant(session, "Sin canal", "inst-a")
    assert resolve_whatsapp(session, t) is None
    assert get_whatsapp_sender(None) is None


def test_wacli_modo_mono_usa_store_default(session, monkeypatch):
    monkeypatch.setattr(settings, "wacli_store_root", "")
    t = _tenant(session, "Mono", "inst-a",
                {"integrations": {"whatsapp": {"via": "wacli"}}})
    wa = resolve_whatsapp(session, t)
    assert wa == WhatsAppInstance(provider="wacli", instance="inst-a", store_dir=None)


def test_wacli_multi_aisla_store_por_instancia(session, monkeypatch):
    monkeypatch.setattr(settings, "wacli_store_root", "/var/lib/aiuda/wacli")
    a = _tenant(session, "A", "inst-a", {"integrations": {"whatsapp": {"via": "wacli"}}})
    b = _tenant(session, "B", "inst-b", {"integrations": {"whatsapp": {"via": "wacli"}}})
    wa_a = resolve_whatsapp(session, a)
    wa_b = resolve_whatsapp(session, b)
    assert wa_a.store_dir == "/var/lib/aiuda/wacli/inst-a"
    assert wa_b.store_dir == "/var/lib/aiuda/wacli/inst-b"
    assert wa_a.store_dir != wa_b.store_dir  # sesiones/números aislados de verdad


def test_cloud_exige_credenciales_completas(session):
    t = _tenant(session, "Oficial", "inst-c",
                {"integrations": {"whatsapp": {"via": "whatsapp_cloud"}}})
    # Sin credenciales guardadas: canal honesto en None (no cae a wacli de nadie).
    assert resolve_whatsapp(session, t) is None
    set_credential(session, t.id, "whatsapp_cloud",
                   {"access_token": "EAAG-token", "phone_number_id": "111222333"})
    wa = resolve_whatsapp(session, t)
    assert wa.provider == "whatsapp_cloud"
    assert wa.creds["access_token"] == "EAAG-token"
    assert wa.creds["phone_number_id"] == "111222333"


def test_wacli_store_dir_sin_root_es_none(monkeypatch):
    monkeypatch.setattr(settings, "wacli_store_root", "")
    assert wacli_store_dir("inst-a") is None


# ---------- dos tenants wacli no se cruzan (argv con --store distinto) ----------

class _Result:
    returncode = 0
    stderr = ""
    stdout = ""


def test_dos_tenants_wacli_envian_por_stores_distintos(session, monkeypatch):
    monkeypatch.setattr(settings, "wacli_store_root", "/stores")
    a = _tenant(session, "A", "inst-a", {"integrations": {"whatsapp": {"via": "wacli"}}})
    b = _tenant(session, "B", "inst-b", {"integrations": {"whatsapp": {"via": "wacli"}}})
    commands: list[list[str]] = []
    monkeypatch.setattr(
        wacli_mod.subprocess, "run",
        lambda command, **kw: commands.append(command) or _Result(),
    )
    get_whatsapp_sender(resolve_whatsapp(session, a))("5215511110001", "hola A")
    get_whatsapp_sender(resolve_whatsapp(session, b))("5215522220002", "hola B")
    stores = [cmd[cmd.index("--store") + 1] for cmd in commands]
    assert stores == ["/stores/inst-a", "/stores/inst-b"]


# ---------- sender oficial: ventana de 24 h ----------

def _cloud_instance(template: str = "") -> WhatsAppInstance:
    creds = {"access_token": "tok", "phone_number_id": "111"}
    if template:
        creds["template_cobranza"] = template
        creds["template_idioma"] = "es_MX"
    return WhatsAppInstance(provider="whatsapp_cloud", instance="inst-c", creds=creds)


def test_cloud_dentro_de_ventana_envia_texto_libre(monkeypatch):
    from aiuda_core.connectors import waba as waba_mod

    sent: list = []
    monkeypatch.setattr(
        waba_mod.WabaClient, "send_text", lambda self, phone, text: sent.append(("text", phone))
    )
    sender = get_whatsapp_sender(_cloud_instance(), lambda phone: True)
    sender("5215587654321", "Hola")
    assert sent == [("text", "5215587654321")]


def test_cloud_fuera_de_ventana_usa_plantilla_aprobada(monkeypatch):
    from aiuda_core.connectors import waba as waba_mod

    sent: list = []
    monkeypatch.setattr(
        waba_mod.WabaClient, "send_template",
        lambda self, phone, template, lang="es_MX", body_params=(): sent.append(
            (template, lang, tuple(body_params))
        ),
    )
    sender = get_whatsapp_sender(_cloud_instance("recordatorio_pago"), lambda phone: False)
    sender("5215587654321", "Su factura vence mañana")
    assert sent == [("recordatorio_pago", "es_MX", ("Su factura vence mañana",))]


def test_cloud_fuera_de_ventana_sin_plantilla_error_accionable():
    from aiuda_core.connectors.waba import WabaError

    sender = get_whatsapp_sender(_cloud_instance(), lambda phone: False)
    with pytest.raises(WabaError, match="plantilla"):
        sender("5215587654321", "Hola")


def test_cloud_sin_callable_de_ventana_asume_fuera(monkeypatch):
    """Conservador: sin información de ventana NO se promete texto libre (Meta lo
    rechazaría); se va por plantilla."""
    from aiuda_core.connectors import waba as waba_mod

    sent: list = []
    monkeypatch.setattr(
        waba_mod.WabaClient, "send_template",
        lambda self, phone, template, lang="es_MX", body_params=(): sent.append(template),
    )
    sender = get_whatsapp_sender(_cloud_instance("recordatorio_pago"))
    sender("5215587654321", "Hola")
    assert sent == ["recordatorio_pago"]


def test_get_channel_sender_canales_no_vivos_devuelve_none(session):
    t = _tenant(session, "T", "inst-z", {"integrations": {"whatsapp": {"via": "wacli"}}})
    wa = resolve_whatsapp(session, t)
    assert get_channel_sender("correo", wa) is None
    assert get_channel_sender("sms", wa) is None
    assert get_channel_sender("whatsapp", wa) is not None


def test_advertencia_no_oficial_es_honesta_sin_alarmismo():
    aviso = channel_mod.UNOFFICIAL_WHATSAPP_WARNING
    # Dice la verdad (no es la API oficial, el volumen atrae restricciones)...
    assert "no la API oficial" in aviso
    assert "volumen" in aviso
    # ...sin regañar al uso local normal.
    assert "riesgo es bajo" in aviso
