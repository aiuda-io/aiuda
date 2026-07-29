"""Conector a la API OFICIAL de WhatsApp Business (Cloud API de Meta).

Esta es la vía soportada de producción del canal WhatsApp: dentro de los Términos
de Meta, sin riesgo de baneo del número. Reglas del modelo oficial que este
conector respeta (y que wacli/Evolution ignoran):

- **Ventana de 24 horas**: texto libre solo si el cliente escribió en las últimas
  24 h. Fuera de la ventana, únicamente PLANTILLAS aprobadas por Meta.
- **Plantillas**: se registran y aprueban en el WhatsApp Manager del negocio;
  aquí solo se referencian por nombre + idioma + parámetros.

Credenciales por tenant (cifradas, ver connectors/credentials.py):
  access_token (secreto), phone_number_id, y opcionalmente la plantilla de
  cobranza aprobada (template_cobranza + template_idioma).

Estado honesto: implementado contra el contrato documentado de la Graph API
(v23.0) con pruebas de contrato sobre respuestas grabadas de la documentación.
PENDIENTE de verificar en vivo con una cuenta real de Meta (WABA + número).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from aiuda_core.config import settings
from aiuda_core.phones import normalize_mx


class WabaError(RuntimeError):
    """Fallo del envío/lectura contra la Cloud API, con el código de Meta si vino."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# Código de error de Meta cuando se intenta texto libre fuera de la ventana de 24 h
# ("re-engagement message"). Se traduce a un mensaje accionable.
REENGAGEMENT_CODE = 131047


@dataclass
class WabaIncoming:
    """Mensaje entrante normalizado del webhook de la Cloud API."""

    phone_number_id: str  # el número del NEGOCIO que lo recibió (rutea al tenant)
    remote_phone: str  # el cliente que escribió (wa_id, dígitos país+número)
    body: str
    wa_message_id: str
    profile_name: str = ""


def parse_webhook(payload: dict) -> list[WabaIncoming]:
    """Normaliza el POST del webhook oficial (object=whatsapp_business_account).

    Devuelve solo mensajes de TEXTO procesables; statuses (sent/delivered/read) y
    otros tipos se ignoran sin error. Un payload puede traer varios mensajes."""
    out: list[WabaIncoming] = []
    if payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            names = {
                c.get("wa_id"): ((c.get("profile") or {}).get("name") or "")
                for c in value.get("contacts") or []
            }
            for msg in value.get("messages") or []:
                if msg.get("type") != "text":
                    continue  # media/reacciones/etc.: fuera de alcance v1
                body = str((msg.get("text") or {}).get("body") or "").strip()
                sender = str(msg.get("from") or "")
                if not body or not sender or not phone_number_id:
                    continue
                out.append(
                    WabaIncoming(
                        phone_number_id=phone_number_id,
                        remote_phone=sender,
                        body=body,
                        wa_message_id=str(msg.get("id") or ""),
                        profile_name=names.get(sender, ""),
                    )
                )
    return out


class WabaClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        base_url: str | None = None,
        timeout: int = 30,
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = (base_url or settings.waba_base_url).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _post_messages(self, payload: dict) -> dict:
        if not self.access_token or not self.phone_number_id:
            raise WabaError("Faltan credenciales de WhatsApp Business (token o número).")
        response = httpx.post(
            f"{self.base_url}/{self.phone_number_id}/messages",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        data = self._json(response)
        if response.status_code >= 400:
            raise self._error(data, response.status_code)
        return data

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _error(data: dict, status: int) -> WabaError:
        err = data.get("error") or {}
        code = err.get("code")
        detail = ((err.get("error_data") or {}).get("details")) or err.get("message") or ""
        if code == REENGAGEMENT_CODE:
            return WabaError(
                "Fuera de la ventana de 24 horas: WhatsApp solo permite plantillas "
                "aprobadas hasta que el cliente vuelva a escribir.",
                code=code,
            )
        return WabaError(f"WhatsApp Cloud API respondió {status}: {detail}", code=code)

    def send_text(self, phone: str, text: str) -> dict:
        """Texto libre. Solo entrega dentro de la ventana de 24 h de servicio; fuera
        de ella Meta responde el error 131047 (se traduce a mensaje accionable)."""
        return self._post_messages(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalize_mx(phone),
                "type": "text",
                "text": {"preview_url": False, "body": text},
            }
        )

    def send_template(
        self,
        phone: str,
        template: str,
        lang: str = "es_MX",
        body_params: tuple[str, ...] | list[str] = (),
    ) -> dict:
        """Plantilla APROBADA en el WhatsApp Manager del negocio, con sus parámetros
        de cuerpo en orden ({{1}}, {{2}}…). Es la única vía fuera de la ventana."""
        components = []
        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in body_params],
                }
            )
        return self._post_messages(
            {
                "messaging_product": "whatsapp",
                "to": normalize_mx(phone),
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": lang},
                    **({"components": components} if components else {}),
                },
            }
        )

    def check_credentials(self) -> dict:
        """Prueba real de credenciales: lee los datos del número (nombre verificado y
        número visible). No envía nada."""
        if not self.access_token or not self.phone_number_id:
            raise WabaError("Faltan credenciales de WhatsApp Business (token o número).")
        response = httpx.get(
            f"{self.base_url}/{self.phone_number_id}",
            params={"fields": "display_phone_number,verified_name"},
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json(response)
        if response.status_code >= 400:
            raise self._error(data, response.status_code)
        return data


def test_connection(creds: dict) -> dict:
    """Prueba de conexión para la UI (shape {ok, message, details}): pega DE VERDAD
    a la Graph API con las credenciales del negocio. Es lo que convierte el estado
    'pendiente de verificar en vivo' en 'Conectado' verificable."""
    missing = [
        label
        for field, label in (("access_token", "token de acceso"), ("phone_number_id", "ID del número"))
        if not creds.get(field)
    ]
    if missing:
        return {"ok": False, "message": f"Faltan datos: {', '.join(missing)}."}
    try:
        info = WabaClient(
            access_token=creds["access_token"], phone_number_id=creds["phone_number_id"]
        ).check_credentials()
        return {
            "ok": True,
            "message": f"Conectado como {info.get('verified_name') or 'número verificado'}.",
            "details": {"Número": info.get("display_phone_number", "")},
        }
    except Exception as exc:  # red, token inválido, número ajeno, etc.
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}
