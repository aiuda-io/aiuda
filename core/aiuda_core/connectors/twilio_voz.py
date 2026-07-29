"""Conector de LLAMADAS DE VOZ (Twilio) — canal de recordatorios de cobranza.

Para qué lo usa aiuda: en vez de (o además de) un mensaje, aiuda LLAMA al cliente
y le dice el recordatorio con voz sintetizada (TwiML `<Say>` en es-MX). Es el mismo
texto aprobado del recordatorio, dicho por teléfono. Útil cuando el cliente no lee
WhatsApp/correo pero sí contesta llamadas.

Cómo funciona (REST puro, SIN el paquete `twilio`):
  - Crear llamada: POST /Accounts/{sid}/Calls.json con auth básica (account_sid:
    auth_token). El cuerpo de la llamada es TwiML INLINE en el parámetro `Twiml`:
    `<Response><Say language="es-MX" voice="alice">…</Say></Response>`. Twilio marca
    al `To`, contesta el cliente y escucha el recordatorio. Devuelve el Call SID.
  - Estado de la llamada: Twilio avisa el resultado (completed/no-answer/busy/failed)
    a un `StatusCallback` — ver `parse_status_webhook` y la ruta del webhook en cloud.
  - Probar conexión: lee la cuenta y sus números entrantes (no llama a nadie).

Credenciales por tenant (cifradas, ver connectors/credentials.py, provider
`twilio_voz`): auth_token (secreto), account_sid y from_number (públicos).

Estado honesto: implementado contra el contrato documentado de la API REST de Twilio
(2010-04-01) con pruebas de contrato sobre transporte fake. PENDIENTE de verificar en
vivo con una cuenta real de Twilio y un número comprado. Costo: Twilio cobra por
minuto de llamada saliente (no es gratis, a diferencia de un mensaje).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape as _xml_escape

import httpx

BASE_URL = "https://api.twilio.com"
API_VERSION = "2010-04-01"

# Estados de la llamada que Twilio reporta en el StatusCallback. `completed` es el
# único éxito; el resto son fallas honestas (nadie contestó, ocupado, error).
STATUS_OK = "completed"
STATUS_FALLA = {"no-answer": "no contestó", "busy": "ocupado", "failed": "la llamada falló", "canceled": "cancelada"}


class TwilioVozError(RuntimeError):
    """Fallo al crear la llamada o leer la cuenta, con el código de Twilio si vino."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def e164_mx(value) -> str:
    """Teléfono en formato E.164 para una llamada de VOZ. México usa +52 + los 10
    dígitos locales: OJO, la voz NO lleva el '1' móvil que sí exige WhatsApp (521), así
    que un número guardado en forma de WhatsApp (521+10) se corrige a +52+10. Acepta 10
    dígitos sueltos, 52+10 y 521+10; un número no mexicano se deja con '+' y sus dígitos."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) == 10:
        return f"+52{digits}"
    if len(digits) == 13 and digits.startswith("521"):
        return f"+52{digits[-10:]}"  # forma de WhatsApp: se quita el '1' para la voz
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    return f"+{digits}"


def twiml_say(mensaje: str) -> str:
    """TwiML mínimo que DICE el recordatorio con voz en español de México. El texto va
    XML-escapado (un '&' o '<' en el mensaje rompería el TwiML si no)."""
    return f'<Response><Say language="es-MX" voice="alice">{_xml_escape(mensaje or "")}</Say></Response>'


@dataclass
class LlamadaEstado:
    """Estado de una llamada normalizado desde el StatusCallback de Twilio."""

    call_sid: str
    status: str  # completed | no-answer | busy | failed | canceled | ...
    account_sid: str = ""
    to: str = ""
    from_number: str = ""
    duration: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def motivo_falla(self) -> str | None:
        """Texto honesto de por qué no se entregó, o None si fue completada."""
        if self.ok:
            return None
        return STATUS_FALLA.get(self.status, self.status or "sin estado")


def parse_status_webhook(form: dict) -> LlamadaEstado | None:
    """Normaliza el POST del StatusCallback de la llamada (form-urlencoded de Twilio).

    Devuelve None si no trae CallSid ni CallStatus (payload que no es de estado)."""
    call_sid = str(form.get("CallSid") or "").strip()
    status = str(form.get("CallStatus") or "").strip()
    if not call_sid or not status:
        return None
    return LlamadaEstado(
        call_sid=call_sid,
        status=status,
        account_sid=str(form.get("AccountSid") or "").strip(),
        to=str(form.get("To") or ""),
        from_number=str(form.get("From") or ""),
        duration=str(form.get("CallDuration") or ""),
    )


class TwilioVozClient:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: int = 30,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout
        # Auth básica account_sid:auth_token — la misma que Twilio documenta para REST.
        self._http = httpx.Client(
            base_url=self.base_url,
            auth=(account_sid, auth_token),
            timeout=timeout,
            transport=transport,
        )

    def _accounts_path(self, suffix: str = "") -> str:
        return f"/{API_VERSION}/Accounts/{self.account_sid}{suffix}"

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _error(data: dict, status: int) -> TwilioVozError:
        # Twilio devuelve {"code": 21211, "message": "...", "status": 400, ...} en fallas.
        code = data.get("code")
        detail = data.get("message") or f"Twilio respondió {status}"
        return TwilioVozError(f"Twilio respondió {status}: {detail}", code=code)

    def llamar_recordatorio(
        self,
        to: str,
        mensaje: str,
        from_number: str,
        status_callback: str | None = None,
    ) -> str:
        """Crea una llamada saliente que DICE el recordatorio con voz. Devuelve el Call
        SID (identificador único que luego liga el StatusCallback al recordatorio).

        `status_callback` (opcional): URL a la que Twilio avisa el resultado de la
        llamada. Sin ella la llamada igual se hace; solo no recibimos el veredicto."""
        if not self.account_sid or not self.auth_token:
            raise TwilioVozError("Faltan credenciales de Twilio (account SID o auth token).")
        destino = e164_mx(to)
        origen = (from_number or "").strip()
        if not destino:
            raise TwilioVozError("Falta el teléfono del cliente para llamar.")
        if not origen:
            raise TwilioVozError("Falta el número Twilio de origen (from).")
        data = {"To": destino, "From": origen, "Twiml": twiml_say(mensaje)}
        if status_callback:
            data["StatusCallback"] = status_callback
            data["StatusCallbackEvent"] = "completed"
            data["StatusCallbackMethod"] = "POST"
        response = self._http.post(self._accounts_path("/Calls.json"), data=data)
        body = self._json(response)
        if response.status_code >= 400:
            raise self._error(body, response.status_code)
        sid = str(body.get("sid") or "")
        if not sid:
            raise TwilioVozError("Twilio no devolvió el SID de la llamada.")
        return sid

    def test_connection(self) -> dict:
        """Prueba real de credenciales: lee la cuenta (nombre y estado) y cuántos
        números entrantes tiene comprados. NO llama a nadie."""
        if not self.account_sid or not self.auth_token:
            raise TwilioVozError("Faltan credenciales de Twilio (account SID o auth token).")
        acct = self._http.get(self._accounts_path(".json"))
        acct_data = self._json(acct)
        if acct.status_code >= 400:
            raise self._error(acct_data, acct.status_code)
        nums = self._http.get(self._accounts_path("/IncomingPhoneNumbers.json"))
        nums_data = self._json(nums)
        if nums.status_code >= 400:
            raise self._error(nums_data, nums.status_code)
        numeros = nums_data.get("incoming_phone_numbers") or []
        return {
            "friendly_name": acct_data.get("friendly_name") or "",
            "status": acct_data.get("status") or "",
            "numeros": len(numeros),
            "primer_numero": (numeros[0].get("phone_number") if numeros else ""),
        }


def test_connection(creds: dict) -> dict:
    """Prueba de conexión para la UI (shape {ok, message, details}): pega DE VERDAD a
    la API de Twilio con las credenciales del negocio. Convierte el estado 'pendiente
    de verificar en vivo' en 'Conectado' verificable, sin llamar a ningún cliente."""
    missing = [
        label
        for field, label in (("account_sid", "Account SID"), ("auth_token", "Auth Token"))
        if not creds.get(field)
    ]
    if missing:
        return {"ok": False, "message": f"Faltan datos: {', '.join(missing)}."}
    try:
        info = TwilioVozClient(
            account_sid=creds["account_sid"], auth_token=creds["auth_token"]
        ).test_connection()
    except Exception as exc:  # red, credenciales inválidas, cuenta suspendida, etc.
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}
    numeros = info.get("numeros", 0)
    details = {
        "Cuenta": info.get("friendly_name") or "(sin nombre)",
        "Estado": info.get("status") or "",
        "Números comprados": numeros,
    }
    if not numeros:
        details["Aviso"] = "No hay número de origen: compra uno en Twilio para poder llamar."
    elif not creds.get("from_number"):
        details["Aviso"] = f"Captura tu número de origen (tienes {info.get('primer_numero')})."
    return {
        "ok": True,
        "message": f"Conectado a Twilio como {info.get('friendly_name') or 'tu cuenta'}.",
        "details": details,
    }
