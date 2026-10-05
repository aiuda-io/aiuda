"""Conector wacli — WhatsApp vía CLI (whatsmeow).

wacli es un proyecto de terceros, no afiliado a WhatsApp; el envío corre bajo
la sesión del propio negocio. El comando es configurable porque las flags
varían entre versiones: ajusta WACLI_SEND_TEMPLATE a tu instalación.
Placeholders: {bin} (de WACLI_BIN), {phone}, {message}.

Aislamiento por tenant: ``store_dir`` apunta el comando a un store propio con la
flag global ``--store`` (verificada en wacli 0.8.x: sesión, chats y mensajes viven
por directorio). Sin ``store_dir`` se usa el store default del host (self-host de
un solo número, el modo clásico).
"""

import json
import shlex
import subprocess

from aiuda_core.config import settings
from aiuda_core.connectors import wacli_bin
from aiuda_core.phones import normalize_mx


class WacliError(RuntimeError):
    pass


# Lo que wacli dice cuando falla (en inglés, para quien programa) y lo que se le
# dice al dueño. Se busca por fragmento, en orden: el primero que aparece gana.
# Los textos de wacli salen de su código (v0.20.0); "not authenticated" además se
# vio en vivo. El crudo va al log, nunca a la pantalla.
_SIN_VINCULAR = (
    "Tu WhatsApp no está vinculado. Ve a Integraciones, abre WhatsApp y escanea el código QR."
)
_SESION_CERRADA = (
    "WhatsApp cerró la sesión de esta computadora, casi siempre porque se quitó desde "
    "el teléfono en Dispositivos vinculados. Vuelve a escanear el código QR."
)
_OCUPADO = (
    "WhatsApp está ocupado en esta computadora con otra tarea. Intenta de nuevo en un minuto."
)
_NO_SUPIMOS = (
    "No supimos si el mensaje salió. Antes de reenviar, revisa en tu WhatsApp si le "
    "llegó al cliente."
)
_TARDO = "El mensaje no salió porque WhatsApp tardó demasiado. Intenta de nuevo."
_SIN_RED = (
    "No hay conexión con WhatsApp. Revisa el internet de esta computadora e intenta de nuevo."
)
_SIN_WHATSAPP = "Ese número no parece tener WhatsApp. Revisa el teléfono del cliente."
FALLO_GENERICO = (
    "WhatsApp no pudo enviar el mensaje. Intenta de nuevo; si sigue fallando, usa "
    "Probar conexión en Integraciones."
)
_FALLOS: tuple[tuple[str, str], ...] = (
    ("not authenticated", _SIN_VINCULAR),
    ("session was revoked", _SESION_CERRADA),
    ("login failed", _SESION_CERRADA),
    ("logged_out", _SESION_CERRADA),
    ("store is locked", _OCUPADO),
    ("waiting for store lock", _OCUPADO),
    ("no reply from the running sync process", _NO_SUPIMOS),
    ("request deadline passed before dispatch", _TARDO),
    ("send timed out", _TARDO),
    (
        "client outdated",
        "WhatsApp pidió una versión más nueva del conector. Ve a Integraciones y abre "
        "WhatsApp para ver cómo actualizarlo.",
    ),
    ("qr code timed out", "El código QR caducó. Genera uno nuevo y escanéalo."),
    (
        "multi-device is not enabled",
        "Tu WhatsApp no tiene activos los dispositivos vinculados. Actualiza WhatsApp en "
        "tu teléfono e intenta de nuevo.",
    ),
    (
        "passkey",
        "Tu WhatsApp pide una llave de acceso para vincular y esta conexión todavía no "
        "la soporta.",
    ),
    ("linked account itself", "No se puede enviar un mensaje a tu propio número."),
    ("no lid found", _SIN_WHATSAPP),
    ("file too large", "El archivo es demasiado grande para WhatsApp."),
    ("not connected", _SIN_RED),
    ("reconnect failed", _SIN_RED),
    ("websocket", _SIN_RED),
    ("dial tcp", _SIN_RED),
    ("no such host", _SIN_RED),
)


def explicar_fallo_wacli(fallo: BaseException | str) -> str:
    """Una falla de wacli, dicha en español llano para el dueño. Nunca devuelve el
    texto crudo: lo que no se reconoce sale como un aviso genérico con qué hacer."""
    if isinstance(fallo, subprocess.TimeoutExpired):
        return _NO_SUPIMOS  # se cortó a media espera: pudo haber salido
    if isinstance(fallo, FileNotFoundError):
        return wacli_bin.SIN_INSTALAR
    texto = str(fallo)
    if "Falta instalar el conector" in texto:
        return wacli_bin.SIN_INSTALAR  # ya venía traducido (WacliClient._run)
    bajo = texto.lower()
    for fragmento, mensaje in _FALLOS:
        if fragmento in bajo:
            return mensaje
    return FALLO_GENERICO


class WacliClient:
    def __init__(
        self,
        send_template: str | None = None,
        timeout: int = 60,
        store_dir: str | None = None,
    ):
        # Placeholders: {bin}, {phone}, {message}
        self.send_template = send_template or settings.wacli_send_template
        # Ruta absoluta (el PATH de la app de escritorio no trae Homebrew). Sin
        # ninguno instalado queda el nombre pelón y el envío falla con el aviso de
        # instalar, no con un error crudo.
        self.bin = wacli_bin.resolver() or settings.wacli_bin
        self.timeout = timeout
        # Store propio del workspace o None = store default del host.
        self.store_dir = store_dir

    def _store_args(self) -> list[str]:
        return ["--store", self.store_dir] if self.store_dir else []

    def _run(self, command: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError as exc:
            raise WacliError(wacli_bin.SIN_INSTALAR) from exc

    def _jid(self, phone: str) -> str:
        """JID de usuario explícito (<dígitos>@s.whatsapp.net), no el número pelón:
        wacli resuelve un número contra contactos/chats y puede ser AMBIGUO ("matches N
        recipients") o no hallarlo si no está sincronizado. El JID es exacto y entrega
        aunque el número no esté en el store local. (Verificado contra wacli 0.8.1.)"""
        digits = normalize_mx(phone)
        return f"{digits}@s.whatsapp.net" if digits else digits

    def _enviar(self, command: list[str], a_si_mismo: bool = False) -> None:
        """Corre un `send`. Va sin --lock-wait: con un sync vivo (el del server o
        el de otro programa) wacli le delega el envío por su socket y sale en 2 o
        3 segundos, sin que el sync suelte la conexión; con --lock-wait esperaría
        primero el plazo completo (visto con wacli 0.18.2: 32 s). Solo si el store
        está ocupado por algo que no es un sync (otro envío directo, por ejemplo)
        se repite, ahora sí esperando el candado.

        `a_si_mismo`: si wacli rechaza el texto porque el destinatario es el número
        vinculado (el resumen y las respuestas al dueño, cuando conectó su propio
        número), se repite con --allow-self. La bandera va solo en ese caso.

        Los dos rechazos son de antes de conectar: ese intento no mandó nada."""
        while True:
            result = self._run(command)
            if result.returncode == 0:
                return
            error = result.stderr.strip() or f"wacli salió con {result.returncode}"
            bajo = error.lower()
            if "store is locked" in bajo and "--lock-wait" not in command:
                command = [*command, "--lock-wait", "30s"]
            elif a_si_mismo and "linked account itself" in bajo and "--allow-self" not in command:
                command = [*command, "--allow-self"]
            else:
                raise WacliError(error)

    def send_text(self, phone: str, text: str) -> None:
        recipient = self._jid(phone)
        # Sustitución por token DESPUÉS de shlex.split: {message} es un solo token, así
        # se preservan los espacios del texto y nada del texto se re-interpreta.
        command = [
            part.replace("{bin}", self.bin).replace("{phone}", recipient).replace("{message}", text)
            for part in shlex.split(self.send_template)
        ] + self._store_args()
        self._enviar(command, a_si_mismo=True)

    def send_file(self, phone: str, file_path: str, caption: str = "", filename: str | None = None) -> None:
        """Envía un archivo (PDF, imagen, etc.) por `wacli send file`. El archivo debe
        existir en disco. Flags fijas (verificadas en 0.8.1): wacli detecta el tipo."""
        command = [self.bin, "send", "file", "--to", self._jid(phone), "--file", file_path,
                   *self._store_args()]
        if caption:
            command += ["--caption", caption]
        if filename:
            command += ["--filename", filename]
        self._enviar(command)

    def _read_data(self, args: list[str]):
        """Corre un subcomando de lectura con --json y devuelve el campo `data` crudo.

        El shape varía por comando: `chats list` da data=[...]; `messages list` da
        data={fts, messages:[...]}. Cada método normaliza. Las lecturas no compiten
        con el sync por el candado; van directo.
        """
        result = self._run([self.bin, *args, *self._store_args(), "--json"])
        if result.returncode != 0:
            raise WacliError(result.stderr.strip() or f"wacli salió con {result.returncode}")
        return json.loads(result.stdout or "{}").get("data")

    def list_chats(self, limit: int = 100) -> list[dict]:
        """Conversaciones: jid, kind ('dm'|'group'), name, last_message_ts, unread."""
        data = self._read_data(["chats", "list", "--limit", str(limit)])
        return data if isinstance(data, list) else []

    def list_messages(self, jid: str, limit: int = 50) -> list[dict]:
        """Mensajes de una conversación (más recientes primero). Campos: SenderName,
        FromMe, Timestamp, Text/DisplayText, MediaType."""
        data = self._read_data(["messages", "list", "--chat", jid, "--limit", str(limit)])
        if isinstance(data, dict):
            msgs = data.get("messages")
            return msgs if isinstance(msgs, list) else []
        return data if isinstance(data, list) else []
