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
from aiuda_core.phones import normalize_mx


class WacliError(RuntimeError):
    pass


class WacliClient:
    def __init__(
        self,
        send_template: str | None = None,
        timeout: int = 60,
        store_dir: str | None = None,
    ):
        # Placeholders: {bin}, {phone}, {message}
        self.send_template = send_template or settings.wacli_send_template
        self.bin = settings.wacli_bin
        self.timeout = timeout
        # Store propio del workspace o None = store default del host.
        self.store_dir = store_dir

    def _store_args(self) -> list[str]:
        return ["--store", self.store_dir] if self.store_dir else []

    def _jid(self, phone: str) -> str:
        """JID de usuario explícito (<dígitos>@s.whatsapp.net), no el número pelón:
        wacli resuelve un número contra contactos/chats y puede ser AMBIGUO ("matches N
        recipients") o no hallarlo si no está sincronizado. El JID es exacto y entrega
        aunque el número no esté en el store local. (Verificado contra wacli 0.8.1.)"""
        digits = normalize_mx(phone)
        return f"{digits}@s.whatsapp.net" if digits else digits

    def send_text(self, phone: str, text: str) -> None:
        recipient = self._jid(phone)
        # Sustitución por token DESPUÉS de shlex.split: {message} es un solo token, así
        # se preservan los espacios del texto y nada del texto se re-interpreta.
        command = [
            part.replace("{bin}", self.bin).replace("{phone}", recipient).replace("{message}", text)
            for part in shlex.split(self.send_template)
        ] + self._store_args()
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=self.timeout
        )
        if result.returncode != 0:
            raise WacliError(result.stderr.strip() or f"wacli salió con {result.returncode}")

    def send_file(self, phone: str, file_path: str, caption: str = "", filename: str | None = None) -> None:
        """Envía un archivo (PDF, imagen, etc.) por `wacli send file`. El archivo debe
        existir en disco. Flags fijas (verificadas en 0.8.1): wacli detecta el tipo."""
        command = [self.bin, "send", "file", "--to", self._jid(phone), "--file", file_path,
                   "--lock-wait", "30s", *self._store_args()]
        if caption:
            command += ["--caption", caption]
        if filename:
            command += ["--filename", filename]
        result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            raise WacliError(result.stderr.strip() or f"wacli salió con {result.returncode}")

    def _read_data(self, args: list[str]):
        """Corre un subcomando de lectura con --json y devuelve el campo `data` crudo.

        El shape varía por comando: `chats list` da data=[...]; `messages list` da
        data={fts, messages:[...]}. Cada método normaliza. Las lecturas no compiten
        con el sync por el lock; van directo.
        """
        result = subprocess.run(
            [self.bin, *args, *self._store_args(), "--json"],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
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
