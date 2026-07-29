"""Correo del negocio (IMAP/SMTP): el canal de email de aiuda.

LECTURA (IMAP): baja los correos nuevos del buzón conectado para volverlos hilos
con clientes en la bandeja unificada (la ingesta vive en ``engine/correo.py``).
Se conecta con SSL, selecciona el buzón EN SOLO LECTURA (no marca nada como
leído: el buzón del negocio no se toca) y avanza por UID; el estado
``{uidvalidity, last_uid}`` lo guarda el caller en ``Tenant.config`` y hace la
lectura idempotente. La primera corrida SIEMBRA: solo la ventana reciente
(14 días, acotada), para no re-inyectar años de historial.

ENVÍO (SMTP): texto plano con Message-ID propio y, si es respuesta, asunto
"Re: …" + In-Reply-To/References correctos (el cliente de correo del destinatario
enhebra bien). Puerto 465 = SSL directo; cualquier otro = STARTTLS obligatorio
(sin TLS no viajan credenciales).

AUTENTICACIÓN, honesto:
- HOY la vía completa es contraseña (de aplicación en Gmail/Outlook): login IMAP
  y AUTH SMTP normales.
- OAuth (XOAUTH2) para Gmail/Outlook queda CONFIG-READY: la credencial ya tiene
  campos (``auth_method`` + ``oauth_client_id/oauth_client_secret/
  oauth_refresh_token``, cifrados los secretos) y el flujo está documentado
  abajo, pero el intercambio de tokens NO está cableado: usarlo lanza
  ``CorreoNoDisponible`` con instrucción clara, nunca finge conectarse.

Flujo OAuth documentado (para cablearlo después, sin inventar liveness hoy):
  Gmail: proyecto en Google Cloud → credencial OAuth (app de escritorio o web)
  → scope ``https://mail.google.com/`` → consentimiento del dueño → guardar el
  refresh_token cifrado; en runtime se cambia por access_token y se autentica
  con ``AUTHENTICATE XOAUTH2`` (IMAP) / ``AUTH XOAUTH2`` (SMTP).
  Outlook: app en Microsoft Entra ID → permisos delegados
  ``IMAP.AccessAsUser.All`` + ``SMTP.Send`` + ``offline_access`` → mismo baile
  de refresh/access token y XOAUTH2.

Los factories (``imap_factory`` / ``smtp_factory``) son inyectables: los tests
hablan el protocolo SMTP real (smtplib contra un servidor local en proceso) y
usan un fake honesto a nivel cliente para IMAP (montar un IMAP4rev1 completo no
aporta; el contrato imaplib está congelado en stdlib).
"""

from __future__ import annotations

import hashlib
import html
import imaplib
import re
import smtplib
from dataclasses import dataclass
from datetime import date, timedelta
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as _POLICY
from email.utils import formatdate, make_msgid, parseaddr

# Tope de correos procesados por corrida (backlog sobrevive: el cursor avanza solo
# hasta el último procesado) y ventana de la siembra inicial.
MAX_CORREOS_POR_CORRIDA = 100
DIAS_SIEMBRA = 14
# Tope del cuerpo que guardamos (la bandeja y el LLM no necesitan megas de HTML).
_MAX_CUERPO = 8000


class CorreoNoDisponible(Exception):
    """El modo de autenticación pedido aún no está cableado (OAuth). Error claro
    y accionable en vez de fingir una conexión."""


OAUTH_PENDIENTE = (
    "OAuth para Gmail/Outlook aún no está cableado. La vía completa hoy es la "
    "contraseña de aplicación (auth_method=password): genera una en tu proveedor "
    "y captúrala en la conexión de Correo."
)


# ---------- Threading: asunto y clave de hilo ----------

# Prefijos de respuesta/reenvío (es/en) que NO cambian el hilo: Re:, RE[2]:, Rv:,
# Fwd:, Fw:, Res: — encadenados ("Re: RV: x") se pelan completos.
_PREFIJOS = re.compile(r"^\s*(?:(?:re|rv|fw|fwd|res)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def normalizar_asunto(asunto: str) -> str:
    """Asunto canónico para agrupar hilo: sin prefijos Re:/Fwd:, minúsculas,
    espacios colapsados. 'RE: Factura F-102 ' y 'factura f-102' son el mismo hilo."""
    limpio = _PREFIJOS.sub("", str(asunto or ""))
    return " ".join(limpio.lower().split())


def clave_hilo(remitente: str, asunto: str) -> str:
    """Clave determinística del hilo de correo, apta para ``Conversation.remote_phone``
    (String(32) único por tenant): ``correo:`` + sha1(remitente|asunto normalizado)[:24].
    Mismo remitente + mismo asunto (pelado de Re:/Fwd:) = el mismo hilo, sin estado."""
    semilla = f"{(remitente or '').strip().lower()}|{normalizar_asunto(asunto)}"
    return "correo:" + hashlib.sha1(semilla.encode()).hexdigest()[:24]


def asunto_re(asunto: str) -> str:
    """Asunto de respuesta: antepone 'Re: ' una sola vez (idempotente)."""
    limpio = (asunto or "").strip()
    if not limpio:
        return "Re: (sin asunto)"
    return limpio if limpio.lower().startswith("re:") else f"Re: {limpio}"


# ---------- Parseo de un correo crudo ----------

_MSGID = re.compile(r"<[^<>\s]+>")
_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class CorreoEntrante:
    """Un correo bajado del buzón, ya parseado a lo que la ingesta necesita."""

    uid: int
    message_id: str
    from_email: str
    from_name: str
    subject: str
    text: str
    in_reply_to: str = ""
    references: tuple[str, ...] = ()


def _texto_plano(msg) -> str:
    """El cuerpo como texto plano: la parte text/plain si existe; si solo hay HTML,
    se pelan las etiquetas (suficiente para bandeja y agente; no somos un cliente
    de correo). Acotado a ``_MAX_CUERPO``."""
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    try:
        contenido = body.get_content()
    except (KeyError, LookupError, UnicodeDecodeError):
        return ""
    if body.get_content_type() == "text/html":
        sin_tags = _TAGS.sub(" ", contenido)
        contenido = html.unescape(sin_tags)
    lineas = [ln.strip() for ln in contenido.splitlines()]
    texto = "\n".join(ln for ln in lineas if ln is not None)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto[:_MAX_CUERPO]


def parse_correo(raw: bytes, uid: int) -> CorreoEntrante:
    """Parsea el RFC822 crudo a ``CorreoEntrante`` (headers decodificados por la
    policy moderna de stdlib; Message-ID/References normalizados a ``<...>``)."""
    msg = BytesParser(policy=_POLICY).parsebytes(raw)
    nombre, correo = parseaddr(str(msg.get("From") or ""))
    mid = _MSGID.search(str(msg.get("Message-ID") or ""))
    message_id = mid.group(0) if mid else ""
    irt = _MSGID.search(str(msg.get("In-Reply-To") or ""))
    references = tuple(_MSGID.findall(str(msg.get("References") or "")))
    return CorreoEntrante(
        uid=uid,
        message_id=message_id,
        from_email=(correo or "").strip().lower(),
        from_name=(nombre or "").strip(),
        subject=str(msg.get("Subject") or "").strip(),
        text=_texto_plano(msg),
        in_reply_to=irt.group(0) if irt else "",
        references=references,
    )


# ---------- Cliente ----------

_STATUS_RE = re.compile(rb"UIDVALIDITY\s+(\d+)(?:.*?UIDNEXT\s+(\d+))?", re.DOTALL)


class CorreoClient:
    """Cliente IMAP (lectura) + SMTP (envío) de la cuenta de correo del negocio."""

    def __init__(
        self,
        email: str,
        password: str = "",
        imap_host: str = "",
        imap_port: int | str = 993,
        smtp_host: str = "",
        smtp_port: int | str = 587,
        auth_method: str = "password",
        timeout: int = 20,
        imap_factory=None,
        smtp_factory=None,
    ) -> None:
        self.email = (email or "").strip()
        self.password = password or ""
        self.imap_host = (imap_host or "").strip()
        self.imap_port = int(imap_port or 993)
        self.smtp_host = (smtp_host or "").strip()
        self.smtp_port = int(smtp_port or 587)
        self.auth_method = (auth_method or "password").strip() or "password"
        self.timeout = timeout
        self.imap_factory = imap_factory
        self.smtp_factory = smtp_factory

    # -- lectura --

    def _imap(self):
        if self.auth_method != "password":
            raise CorreoNoDisponible(OAUTH_PENDIENTE)
        if self.imap_factory is not None:
            conn = self.imap_factory(self.imap_host, self.imap_port)
        else:
            conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=self.timeout)
        conn.login(self.email, self.password)
        return conn

    @staticmethod
    def _estado_buzon(conn, buzon: str) -> tuple[int, int]:
        """(UIDVALIDITY, UIDNEXT) del buzón. UIDNEXT 0 si el servidor no lo da."""
        typ, data = conn.status(buzon, "(UIDVALIDITY UIDNEXT)")
        if typ != "OK" or not data or not data[0]:
            return 0, 0
        crudo = data[0] if isinstance(data[0], bytes) else str(data[0]).encode()
        m = _STATUS_RE.search(crudo)
        if not m:
            return 0, 0
        return int(m.group(1)), int(m.group(2) or 0)

    def fetch_nuevos(
        self,
        estado: dict | None = None,
        hoy: date | None = None,
        cap: int = MAX_CORREOS_POR_CORRIDA,
    ) -> tuple[list[CorreoEntrante], dict, bool]:
        """Correos nuevos del buzón + estado actualizado + si fue siembra.

        ``estado`` = ``{"buzon", "uidvalidity", "last_uid"}`` (de la corrida previa;
        None/{} la primera vez). Siembra (primera vez o UIDVALIDITY cambió): solo los
        últimos ``DIAS_SIEMBRA`` días, los más recientes hasta ``cap``. Incremental:
        UIDs > last_uid, los MÁS VIEJOS primero hasta ``cap`` — si hay más, el cursor
        avanza solo hasta el último procesado y el resto entra la próxima corrida
        (ningún correo se salta). El buzón se abre en SOLO LECTURA."""
        estado = dict(estado or {})
        buzon = estado.get("buzon") or "INBOX"
        last_uid = int(estado.get("last_uid") or 0)
        conn = self._imap()
        try:
            uidvalidity, uidnext = self._estado_buzon(conn, buzon)
            sembrando = not estado.get("uidvalidity") or int(estado["uidvalidity"]) != uidvalidity
            conn.select(buzon, readonly=True)
            if sembrando:
                desde = (hoy or date.today()) - timedelta(days=DIAS_SIEMBRA)
                criterio = f"(SINCE {desde.strftime('%d-%b-%Y')})"
                piso = 0
            else:
                criterio = f"(UID {last_uid + 1}:*)"
                piso = last_uid
            typ, data = conn.uid("SEARCH", None, criterio)
            crudos = data[0].split() if typ == "OK" and data and data[0] else []
            uids = sorted({int(u) for u in crudos} - {0})
            uids = [u for u in uids if u > piso]
            truncado = len(uids) > cap
            uids = uids[-cap:] if sembrando else uids[:cap]

            entrantes: list[CorreoEntrante] = []
            for uid in uids:
                typ, msgdata = conn.uid("FETCH", str(uid), "(RFC822)")
                raw = next(
                    (p[1] for p in (msgdata or []) if isinstance(p, tuple) and len(p) > 1),
                    None,
                )
                if not raw:
                    continue
                entrantes.append(parse_correo(raw, uid))

            if sembrando:
                # La siembra ancla el cursor al presente: lo anterior no se replay-ea.
                nuevo_last = max([0, uidnext - 1, *uids])
            elif truncado:
                nuevo_last = max(uids) if uids else last_uid  # backlog: seguimos ahí
            else:
                nuevo_last = max([last_uid, uidnext - 1, *(u for u in uids)])
            nuevo_estado = {"buzon": buzon, "uidvalidity": uidvalidity, "last_uid": nuevo_last}
            return entrantes, nuevo_estado, sembrando
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 — cerrar sesión nunca debe tumbar la lectura
                pass

    # -- envío --

    def _smtp(self):
        if self.auth_method != "password":
            raise CorreoNoDisponible(OAUTH_PENDIENTE)
        if self.smtp_factory is not None:
            return self.smtp_factory(self.smtp_host, self.smtp_port)
        if self.smtp_port == 465:
            return smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout)
        conn = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout)
        conn.starttls()  # obligatorio: sin TLS no viajan credenciales
        return conn

    def send(
        self,
        para: str,
        asunto: str,
        texto: str,
        in_reply_to: str = "",
        references: tuple[str, ...] | list[str] = (),
        de_nombre: str = "",
    ) -> str:
        """Envía texto plano. Si es respuesta (``in_reply_to``), arma References
        (cadena previa + el respondido, acotada) para que el hilo enhebre bien.
        Devuelve el Message-ID generado (para enhebrar la respuesta del cliente)."""
        msg = EmailMessage()
        msg["From"] = f"{de_nombre} <{self.email}>" if de_nombre else self.email
        msg["To"] = para
        msg["Subject"] = asunto
        msg["Date"] = formatdate(localtime=True)
        message_id = make_msgid(domain=self.email.partition("@")[2] or None)
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            cadena: list[str] = []
            for ref in (*tuple(references), in_reply_to):
                if ref and ref not in cadena:
                    cadena.append(ref)
            msg["References"] = " ".join(cadena[-10:])
        msg.set_content(texto)

        conn = self._smtp()
        try:
            if self.password:
                conn.login(self.email, self.password)
            conn.send_message(msg)
        finally:
            try:
                conn.quit()
            except Exception:  # noqa: BLE001 — el QUIT fallido no invalida el envío
                pass
        return message_id

    # -- verificación (Probar conexión) --

    def verificar(self) -> dict:
        """Prueba real de la cuenta: login IMAP (cuenta los buzones) y, si hay SMTP
        configurado, conexión + AUTH SMTP sin enviar nada. Devuelve detalles crudos;
        el texto amable lo pone el API."""
        detalles: dict = {}
        conn = self._imap()
        try:
            typ, data = conn.list()
            detalles["buzones"] = len(data) if typ == "OK" and data else 0
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        if self.smtp_host:
            smtp = self._smtp()
            try:
                if self.password:
                    smtp.login(self.email, self.password)
                detalles["smtp"] = "listo"
            finally:
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001
                    pass
        return detalles
