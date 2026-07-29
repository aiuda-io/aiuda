"""Canales: por dónde aiuda le habla al cliente.

Un CONECTOR tiene un rol; el rol "canal" entrega mensajes al cliente. Cada canal
sabe a qué dato del cliente entrega (teléfono o correo) y cómo enviar. Vivos hoy:
WhatsApp (siempre declarado; la instancia es por tenant) y CORREO (por tenant:
vivo solo si el negocio conectó su cuenta con SMTP — ``resolve_correo``). SMS
queda declarado (sin sender) hasta tener conector.

Instancia POR TENANT: cada negocio tiene su propia identidad de canal
(``resolve_whatsapp``). La vía la decide ``Tenant.config["integrations"]["whatsapp"]["via"]``:

  via=wacli           → wacli (CLI de terceros; solo dev/piloto). Con
                        WACLI_STORE_ROOT definido cada tenant usa su PROPIO store
                        (sesión/número aislados vía ``--store``); sin definir, el
                        store default del host (self-host de un solo número).
  via=whatsapp_cloud  → API OFICIAL de WhatsApp Business (Cloud API de Meta), la
                        vía de producción. Credenciales CIFRADAS por tenant.
  via=evolution       → Evolution API (multi-instancia, protocolo no oficial).

Un tenant SIN conexión de WhatsApp no tiene sender: no puede salir por el número
de otro negocio (ese era el riesgo cross-tenant de la instancia única).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aiuda_core.config import settings

Sender = Callable[[str, str], None]  # (destinatario, texto) -> None

# NOTA HONESTA, sin alarmismo: wacli y Evolution hablan con WhatsApp por el
# protocolo de WhatsApp Web — tu número, en tu computadora, como una sesión más
# de WhatsApp Web. No es la API oficial, así que técnicamente queda fuera de
# los Términos de WhatsApp Business. En el uso local del día a día (responder a
# tus clientes, recordatorios aprobados uno a uno) el riesgo es bajo; lo que sí
# atrae restricciones de Meta es el volumen de mensajes no solicitados. Para
# enviar a volumen existe la vía oficial (Cloud API, conector "whatsapp_cloud"),
# que a cambio necesita una URL pública para recibir webhooks.
UNOFFICIAL_WHATSAPP_WARNING = (
    "WhatsApp conectado con tu propio número por el protocolo de WhatsApp Web "
    "(como una sesión más de WhatsApp Web, no la API oficial). Para el uso normal "
    "el riesgo es bajo; enviar volumen de mensajes no solicitados sí puede hacer "
    "que Meta restrinja el número. Si algún día envías a volumen, la vía oficial "
    "(WhatsApp Business / Cloud API) es el camino — requiere un servidor con URL "
    "pública."
)

# Categorización por rol "canal": etiqueta + a qué dato del cliente entrega.
CHANNELS: dict[str, dict] = {
    "whatsapp": {"label": "WhatsApp", "recipient_field": "phone"},
    "correo": {"label": "Correo", "recipient_field": "email"},
    "voz": {"label": "Llamada de voz", "recipient_field": "phone"},
    "sms": {"label": "SMS", "recipient_field": "phone"},
}

# Canales con sender real SIEMPRE declarado (WhatsApp). El correo y la voz también
# tienen sender real, pero POR TENANT: solo si el negocio conectó su cuenta (correo con
# SMTP; voz con credenciales de Twilio); usa ``live_channels(session, tenant)`` para la
# señal completa. SMS: por conectar.
LIVE_CHANNELS = {"whatsapp"}


def live_channels(session, tenant) -> set[str]:
    """Canales vivos PARA ESTE tenant: WhatsApp (el flujo existe siempre; si no está
    emparejado el envío falla honesto) + correo solo si su cuenta está conectada con
    SMTP + voz solo si conectó Twilio. Es la señal que la UI usa para ofrecer
    'Enviar por…'."""
    vivos = set(LIVE_CHANNELS)
    if resolve_correo(session, tenant) is not None:
        vivos.add("correo")
    if resolve_voz(session, tenant) is not None:
        vivos.add("voz")
    return vivos


@dataclass(frozen=True)
class WhatsAppInstance:
    """La identidad de canal WhatsApp de UN tenant: por dónde y como quién envía."""

    provider: str  # wacli | whatsapp_cloud | evolution
    instance: str  # id único del tenant (Tenant.evolution_instance)
    store_dir: str | None = None  # wacli: store propio (None = default del host)
    creds: dict | None = None  # whatsapp_cloud: credenciales resueltas (cifradas)


def wacli_store_dir(instance: str) -> str | None:
    """Store de wacli para esta instancia. Con WACLI_STORE_ROOT cada tenant aísla
    sesión y datos en su propio directorio; sin definir (self-host de un solo
    número) se usa el store default del host."""
    root = (settings.wacli_store_root or "").strip()
    if not root or not instance:
        return None
    return str(Path(root) / instance)


def whatsapp_config(tenant) -> dict | None:
    """La conexión de WhatsApp del tenant (config.integrations.whatsapp) o None."""
    wa = ((tenant.config or {}).get("integrations") or {}).get("whatsapp")
    return wa if isinstance(wa, dict) else None


def resolve_whatsapp(session, tenant) -> WhatsAppInstance | None:
    """La instancia de WhatsApp DE ESTE tenant, o None si no tiene el canal
    conectado (en cuyo caso nada suyo se envía: sin canal no hay envío, y jamás
    por el número de otro negocio)."""
    wa = whatsapp_config(tenant)
    if wa is None:
        return None
    via = wa.get("via") or settings.whatsapp_provider
    instance = wa.get("instance") or tenant.evolution_instance
    if via == "whatsapp_cloud":
        from aiuda_core.connectors.credentials import get_credential

        creds = get_credential(session, tenant.id, "whatsapp_cloud")
        if not creds or not creds.get("access_token") or not creds.get("phone_number_id"):
            return None  # honesto: sin credenciales completas no hay canal oficial
        return WhatsAppInstance(provider="whatsapp_cloud", instance=instance, creds=creds)
    if via == "evolution":
        return WhatsAppInstance(provider="evolution", instance=instance)
    return WhatsAppInstance(
        provider="wacli", instance=instance, store_dir=wacli_store_dir(instance)
    )


def get_whatsapp_sender(
    wa: WhatsAppInstance | None,
    service_window: Callable[[str], bool] | None = None,
) -> Sender | None:
    """Sender de WhatsApp para UNA instancia (la del tenant dueño del envío).

    ``service_window(phone)`` — solo Cloud API — dice si el cliente escribió en las
    últimas 24 h (ventana de servicio). Dentro: texto libre. Fuera: la plantilla
    aprobada configurada, o error accionable si no hay. Sin el callable se asume
    FUERA de ventana (conservador: nunca prometemos entrega que Meta rechazaría)."""
    if wa is None:
        return None

    if wa.provider == "whatsapp_cloud":
        from aiuda_core.connectors.waba import WabaClient, WabaError

        creds = wa.creds or {}
        client = WabaClient(
            access_token=creds.get("access_token", ""),
            phone_number_id=creds.get("phone_number_id", ""),
        )
        template = (creds.get("template_cobranza") or "").strip()
        lang = (creds.get("template_idioma") or "es_MX").strip() or "es_MX"

        def _send_cloud(phone: str, text: str) -> None:
            if service_window is not None and service_window(phone):
                client.send_text(phone, text)
                return
            if template:
                client.send_template(phone, template, lang=lang, body_params=(text,))
                return
            raise WabaError(
                "Fuera de la ventana de 24 horas y sin plantilla aprobada configurada. "
                "Registra una plantilla en el WhatsApp Manager y captúrala en la "
                "conexión de WhatsApp Business."
            )

        return _send_cloud

    if wa.provider == "evolution":
        from aiuda_core.connectors.evolution import EvolutionClient

        client = EvolutionClient()
        return lambda phone, text: client.send_text(wa.instance, phone, text)

    from aiuda_core.connectors.wacli import WacliClient

    wacli = WacliClient(store_dir=wa.store_dir)
    return lambda phone, text: wacli.send_text(phone, text)


@dataclass(frozen=True)
class CorreoInstance:
    """La identidad de correo de UN tenant: su cuenta (remitente) y servidores."""

    creds: dict  # email, password, imap/smtp host+port, auth_method, provider
    nombre: str = ""  # nombre del negocio como From amable ("Negocio <cuenta@...>")

    def client(self):
        from aiuda_core.connectors.correo import CorreoClient

        c = self.creds
        return CorreoClient(
            email=c.get("email", ""),
            password=c.get("password", ""),
            imap_host=c.get("imap_host", ""),
            imap_port=c.get("imap_port") or 993,
            smtp_host=c.get("smtp_host", ""),
            smtp_port=c.get("smtp_port") or 587,
            auth_method=c.get("auth_method") or "password",
        )


def resolve_correo(session, tenant) -> CorreoInstance | None:
    """La cuenta de correo DE ESTE tenant para ENVIAR, o None si el canal no está
    completo (sin cuenta, sin contraseña o sin SMTP no hay salida — honesto). La
    credencial vive cifrada por tenant (``get_credential('email')``). OAuth guardado
    pero no cableado también da None como canal: no prometemos un envío que
    lanzaría CorreoNoDisponible."""
    from aiuda_core.connectors.credentials import get_credential

    creds = get_credential(session, tenant.id, "email")
    if not creds:
        return None
    completo = creds.get("email") and creds.get("password") and creds.get("smtp_host")
    if not completo or (creds.get("auth_method") or "password") != "password":
        return None
    return CorreoInstance(creds=creds, nombre=(tenant.name or "").strip())


def get_correo_sender(
    correo: CorreoInstance | None,
    asunto: str,
    in_reply_to: str = "",
    references: tuple[str, ...] | list[str] = (),
    on_sent: Callable[[str], None] | None = None,
) -> Sender | None:
    """Sender de correo para UNA cuenta (la del tenant dueño del envío), con el
    asunto ya decidido y, si es respuesta, los headers de threading correctos.
    ``on_sent(message_id)`` recibe el Message-ID generado — con él el caller enhebra
    el saliente al hilo (la respuesta futura del cliente cae en la misma conversación)."""
    if correo is None:
        return None
    client = correo.client()

    def _send(destinatario: str, texto: str) -> None:
        message_id = client.send(
            destinatario,
            asunto,
            texto,
            in_reply_to=in_reply_to,
            references=tuple(references),
            de_nombre=correo.nombre,
        )
        if on_sent is not None:
            on_sent(message_id)

    return _send


@dataclass(frozen=True)
class TwilioVozInstance:
    """La identidad de VOZ de UN tenant: su cuenta de Twilio y su número de origen."""

    creds: dict  # account_sid, auth_token, from_number

    @property
    def from_number(self) -> str:
        return (self.creds.get("from_number") or "").strip()

    def client(self, transport=None):
        from aiuda_core.connectors.twilio_voz import TwilioVozClient

        return TwilioVozClient(
            account_sid=self.creds.get("account_sid", ""),
            auth_token=self.creds.get("auth_token", ""),
            transport=transport,
        )


def resolve_voz(session, tenant) -> TwilioVozInstance | None:
    """La cuenta de Twilio DE ESTE tenant para LLAMAR, o None si el canal no está
    completo (sin account_sid, sin auth_token o sin número de origen no hay salida —
    honesto). La credencial vive cifrada por tenant (``get_credential('twilio_voz')``)."""
    from aiuda_core.connectors.credentials import get_credential

    creds = get_credential(session, tenant.id, "twilio_voz")
    if not creds:
        return None
    completo = creds.get("account_sid") and creds.get("auth_token") and creds.get("from_number")
    if not completo:
        return None
    return TwilioVozInstance(creds=creds)


def get_voz_sender(
    voz: TwilioVozInstance | None,
    status_callback: str | None = None,
    on_call: Callable[[str], None] | None = None,
) -> Sender | None:
    """Sender de VOZ para UNA cuenta (la del tenant dueño del envío). El 'envío' es una
    LLAMADA que dice el texto con voz. ``status_callback`` es la URL donde Twilio avisa
    el resultado (completed/no-answer/…); ``on_call(call_sid)`` recibe el Call SID de la
    llamada creada — con él el caller liga el veredicto futuro al recordatorio."""
    if voz is None:
        return None
    client = voz.client()
    from_number = voz.from_number

    def _send(destinatario: str, texto: str) -> None:
        call_sid = client.llamar_recordatorio(
            destinatario, texto, from_number, status_callback=status_callback
        )
        if on_call is not None:
            on_call(call_sid)

    return _send


def get_channel_sender(
    channel: str,
    wa: WhatsAppInstance | None,
    service_window: Callable[[str], bool] | None = None,
    correo: CorreoInstance | None = None,
    correo_opts: dict | None = None,
    voz: TwilioVozInstance | None = None,
    voz_opts: dict | None = None,
) -> Sender | None:
    """Sender del canal para este tenant, o None si el canal aún no está vivo.
    Para correo, ``correo_opts`` trae el asunto y, si es respuesta, los headers
    de threading (asunto, in_reply_to, references, on_sent). Para voz, ``voz_opts``
    trae el status_callback y ``on_call`` (para ligar el Call SID al recordatorio)."""
    if channel == "whatsapp":
        return get_whatsapp_sender(wa, service_window=service_window)
    if channel == "correo":
        opts = dict(correo_opts or {})
        opts.setdefault("asunto", "Mensaje de tu proveedor")
        return get_correo_sender(correo, **opts)
    if channel == "voz":
        return get_voz_sender(voz, **dict(voz_opts or {}))
    return None  # sms: conector pendiente ("por conectar")
