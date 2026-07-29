"""El SAT con la e.firma del dueño: validación de la credencial y Descarga
Masiva de CFDI (el web service oficial).

Por qué la e.firma (FIEL) y no el CSD: la Descarga Masiva EXIGE la e.firma; un
CSD (el sello con el que se timbran facturas) se rechaza aquí mismo con un
mensaje claro, antes de guardar nada.

Por qué `satcfdi`: licencia MIT (compatible con Apache-2.0) y firma las
peticiones SOAP del SAT (autenticación, solicitud, verificación, descarga) sin
reimplementar WS-Security a mano. Sus partes pesadas (weasyprint para PDF) son
de import perezoso y aiuda no las toca. El import de satcfdi aquí también es
perezoso: los tests y el resto del core no lo cargan.

Seguridad (regla de la casa): el certificado, la llave y la contraseña viven
CIFRADOS en la base (una fila por RFC) y se descifran SOLO en memoria por
corrida. Este módulo no escribe archivos temporales, no cachea la llave y no
loggea parámetros: recibe bytes, firma en memoria y suelta.
"""

from __future__ import annotations

import base64
import io
import zipfile
from datetime import datetime, timezone


class SatCredencialInvalida(ValueError):
    """La e.firma subida no sirve, con el motivo en palabras del dueño."""


ES_CSD = (
    "Estos archivos son un CSD (el sello con el que timbras facturas). "
    "El SAT solo entrega tus facturas con tu e.firma (FIEL): sube el .cer y "
    "la .key de tu e.firma, no los del sello."
)


def _satcfdi():
    """Import perezoso con error legible si el paquete no está instalado."""
    try:
        from satcfdi.exceptions import CFDIError
        from satcfdi.models import Signer
        from satcfdi.models.certificate import CertificateType

        return Signer, CertificateType, CFDIError
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "Falta la librería 'satcfdi' (la instala `uv sync`). Sin ella no se "
            "puede hablar con el SAT."
        ) from exc


def _cargar_signer(cer: bytes, key: bytes, password: str):
    """El firmante de la e.firma, con cada fallo traducido a palabras del dueño."""
    Signer, CertificateType, CFDIError = _satcfdi()
    try:
        return Signer.load(certificate=cer, key=key, password=password)
    except CFDIError as exc:
        raise SatCredencialInvalida(
            "El certificado (.cer) y la llave (.key) no son pareja. Revisa que "
            "los dos archivos sean de la MISMA e.firma."
        ) from exc
    except (ValueError, TypeError) as exc:
        raise SatCredencialInvalida(
            "La llave (.key) no abrió con esa contraseña. Revisa la contraseña "
            "de tu e.firma."
        ) from exc
    except Exception as exc:  # certificado ilegible, archivo equivocado
        raise SatCredencialInvalida(
            "No se pudieron leer los archivos. Sube el .cer y la .key de tu "
            "e.firma tal como te los entregó el SAT."
        ) from exc


def validar_efirma(cer: bytes, key: bytes, password: str) -> dict:
    """Valida una e.firma ANTES de guardarla: que abra, que sea FIEL (no CSD),
    que esté vigente y de quién es. Devuelve el resumen público (rfc, titular,
    vigencia) — lo único que la API puede enseñar después."""
    _, CertificateType, _ = _satcfdi()
    signer = _cargar_signer(cer, key, password)

    # CSD: el tipo formal del certificado o el nombre de sucursal (solo los CSD
    # lo traen). La e.firma de una persona o empresa no tiene sucursal.
    if signer.type == CertificateType.CSD or signer.branch_name:
        raise SatCredencialInvalida(ES_CSD)

    try:
        rfc = str(signer.rfc) if signer.rfc else ""
    except Exception:  # el RFC del subject no parseó
        rfc = ""
    if not rfc:
        raise SatCredencialInvalida(
            "El certificado no trae RFC: no parece una e.firma del SAT."
        )

    cert = signer.certificate.to_cryptography()
    ahora = datetime.now(timezone.utc)
    if ahora > cert.not_valid_after_utc:
        raise SatCredencialInvalida(
            f"Esta e.firma venció el {cert.not_valid_after_utc:%d-%m-%Y}. "
            "Renuévala en el SAT y vuelve a subirla."
        )
    if ahora < cert.not_valid_before_utc:
        raise SatCredencialInvalida(
            f"Esta e.firma es vigente hasta el {cert.not_valid_before_utc:%d-%m-%Y}; "
            "todavía no entra en vigor."
        )

    titular = signer.legal_name or ""
    return {
        "rfc": rfc.upper(),
        "titular": titular,
        "vigente_desde": cert.not_valid_before_utc.date().isoformat(),
        "vigente_hasta": cert.not_valid_after_utc.date().isoformat(),
    }


def extraer_xmls(zip_bytes: bytes) -> list[bytes]:
    """Los XML de un paquete ZIP del SAT, todo en memoria (cero temporales)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return [
            zf.read(info)
            for info in zf.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".xml")
        ]


class SatDescargaClient:
    """Cliente de la Descarga Masiva para UNA empresa (un RFC, su e.firma).

    El ciclo del web service es asíncrono del lado del SAT: se SOLICITA un
    periodo, el SAT lo prepara (minutos u horas), se VERIFICA la solicitud y,
    cuando está TERMINADA, se DESCARGAN sus paquetes ZIP. El token de
    autenticación lo administra satcfdi (lo renueva solo cuando caduca).

    `service` es inyectable para tests (cualquier objeto con la interfaz del
    SAT de satcfdi); en producción se construye el real."""

    def __init__(self, cer: bytes, key: bytes, password: str, service=None):
        self._signer = _cargar_signer(cer, key, password)
        self.rfc = str(self._signer.rfc).upper() if self._signer.rfc else ""
        if service is None:  # pragma: no cover - construcción real, se prueba en vivo
            from satcfdi.pacs.sat import SAT

            service = SAT(signer=self._signer)
        self._service = service

    def solicitar(self, scope: str, desde: datetime, hasta: datetime) -> dict:
        """Pide al SAT un periodo de CFDI ('emitidas' o 'recibidas'). Devuelve la
        respuesta cruda del SAT: IdSolicitud si la aceptó, CodEstatus/Mensaje si no."""
        if scope == "emitidas":
            r = self._service.recover_comprobante_emitted_request(
                fecha_inicial=desde, fecha_final=hasta
            )
        elif scope == "recibidas":
            r = self._service.recover_comprobante_received_request(
                fecha_inicial=desde, fecha_final=hasta
            )
        else:
            raise ValueError(f"scope desconocido: {scope}")
        return dict(r)

    def verificar(self, id_solicitud: str) -> dict:
        """El estado de una solicitud. EstadoSolicitud: 1 aceptada, 2 en proceso,
        3 terminada (trae IdsPaquetes), 4 error, 5 rechazada (el
        CodigoEstadoSolicitud dice por qué; 5002 = agotada de por vida para ese
        periodo exacto), 6 vencida."""
        return dict(self._service.recover_comprobante_status(id_solicitud=id_solicitud))

    def descargar(self, id_paquete: str) -> bytes:
        """Un paquete ZIP de la solicitud terminada, en memoria."""
        _header, paquete_b64 = self._service.recover_comprobante_download(
            id_paquete=id_paquete
        )
        return base64.b64decode(paquete_b64)

    def probar(self) -> dict:
        """Prueba real y ligera: autenticarse contra el SAT (obtener token) con
        la e.firma. No pide ni descarga nada."""
        # Método interno de satcfdi: es la única vía de autenticar sin solicitar.
        self._service._get_token_comprobante()  # noqa: SLF001
        return {
            "ok": True,
            "rfc": self.rfc,
            "mensaje": "El SAT aceptó la e.firma.",
        }
