"""Conector de correo: parseo RFC822, threading (asunto/clave de hilo), lectura IMAP
por UID (fake honesto a nivel cliente: imaplib está congelado en stdlib y montar un
IMAP4rev1 no aporta) y envío SMTP hablando el PROTOCOLO REAL: smtplib contra un
servidor SMTP mínimo en proceso (socket real, EHLO/AUTH/MAIL/RCPT/DATA)."""

from __future__ import annotations

import base64
import socketserver
import threading

import pytest

from aiuda_core.connectors.correo import (
    CorreoClient,
    CorreoNoDisponible,
    asunto_re,
    clave_hilo,
    normalizar_asunto,
    parse_correo,
)

# ---------- threading: asunto y clave de hilo ----------


@pytest.mark.parametrize(
    "sucio,limpio",
    [
        ("Re: Factura F-102", "factura f-102"),
        ("RE: RV: Factura F-102 ", "factura f-102"),
        ("Fwd: Re[2]: Pago  pendiente", "pago pendiente"),
        ("Factura F-102", "factura f-102"),
        ("", ""),
    ],
)
def test_normalizar_asunto_pela_prefijos(sucio, limpio):
    assert normalizar_asunto(sucio) == limpio


def test_clave_hilo_estable_y_cabe_en_32():
    a = clave_hilo("Cliente@Empresa.com", "Re: Factura F-102")
    b = clave_hilo("cliente@empresa.com ", "factura f-102")
    assert a == b and a.startswith("correo:") and len(a) <= 32
    # Otro asunto u otro remitente = otro hilo.
    assert clave_hilo("cliente@empresa.com", "Cotización") != a
    assert clave_hilo("otro@empresa.com", "Factura F-102") != a


def test_asunto_re_idempotente():
    assert asunto_re("Factura F-102") == "Re: Factura F-102"
    assert asunto_re("Re: Factura F-102") == "Re: Factura F-102"
    assert asunto_re("") == "Re: (sin asunto)"


# ---------- parseo ----------


def _raw(
    *,
    de='Ana López <ana@cliente.mx>',
    asunto="Factura F-102",
    mid="<m1@cliente.mx>",
    irt="",
    refs="",
    cuerpo="Hola, ¿me reenvías la factura?",
    content_type="text/plain; charset=utf-8",
) -> bytes:
    extra = ""
    if irt:
        extra += f"In-Reply-To: {irt}\r\n"
    if refs:
        extra += f"References: {refs}\r\n"
    texto = (
        f"From: {de}\r\nTo: cobranza@negocio.mx\r\nSubject: {asunto}\r\n"
        f"Message-ID: {mid}\r\n{extra}"
        f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n{cuerpo}\r\n"
    )
    return texto.encode()


def test_parse_correo_extrae_lo_esencial():
    c = parse_correo(_raw(), uid=7)
    assert c.uid == 7
    assert c.from_email == "ana@cliente.mx"
    assert c.from_name == "Ana López"
    assert c.subject == "Factura F-102"
    assert c.message_id == "<m1@cliente.mx>"
    assert "factura" in c.text


def test_parse_correo_threading_headers():
    c = parse_correo(
        _raw(irt="<m1@cliente.mx>", refs="<m0@negocio.mx> <m1@cliente.mx>"),
        uid=8,
    )
    assert c.in_reply_to == "<m1@cliente.mx>"
    assert c.references == ("<m0@negocio.mx>", "<m1@cliente.mx>")


def test_parse_correo_html_se_pela_a_texto():
    c = parse_correo(
        _raw(cuerpo="<html><body><p>Hola &amp; gracias</p></body></html>", content_type="text/html; charset=utf-8"),
        uid=9,
    )
    assert "<p>" not in c.text and "Hola & gracias" in c.text


def test_parse_correo_sin_message_id_no_truena():
    c = parse_correo(_raw(mid="sin-formato"), uid=1)
    assert c.message_id == ""


# ---------- lectura IMAP (fake honesto a nivel cliente) ----------


class FakeImap:
    """Contrato imaplib mínimo que usa el cliente: login/status/select/uid/logout,
    con las respuestas en el formato de alambre real de imaplib."""

    def __init__(self, correos: dict[int, bytes], uidvalidity: int = 3):
        self.correos = correos  # uid -> raw rfc822
        self.uidvalidity = uidvalidity
        self.readonly = None
        self.logins: list[tuple[str, str]] = []

    def login(self, user, password):
        self.logins.append((user, password))
        return "OK", [b"Logged in"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    def status(self, mailbox, what):
        uidnext = max(self.correos, default=0) + 1
        return "OK", [
            f'"{mailbox}" (UIDVALIDITY {self.uidvalidity} UIDNEXT {uidnext})'.encode()
        ]

    def select(self, mailbox, readonly=False):
        self.readonly = readonly
        return "OK", [str(len(self.correos)).encode()]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            criterio = args[-1]
            if "SINCE" in criterio:
                uids = sorted(self.correos)
            else:  # (UID n:*)
                inicio = int(criterio.split()[1].split(":")[0])
                uids = sorted(u for u in self.correos if u >= inicio)
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if cmd == "FETCH":
            uid = int(args[0])
            raw = self.correos.get(uid)
            if raw is None:
                return "OK", [None]
            return "OK", [(f"{uid} (RFC822 {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(f"comando no esperado: {cmd}")

    def logout(self):
        return "BYE", [b"bye"]


def _cliente(fake) -> CorreoClient:
    return CorreoClient(
        email="cobranza@negocio.mx",
        password="app-pass",
        imap_host="imap.negocio.mx",
        imap_factory=lambda host, port: fake,
    )


def test_fetch_siembra_y_luego_incremental_no_duplica():
    fake = FakeImap({1: _raw(mid="<m1@c.mx>"), 2: _raw(mid="<m2@c.mx>")})
    cli = _cliente(fake)
    # Siembra: baja lo reciente y ancla el cursor.
    entrantes, estado, sembrando = cli.fetch_nuevos(None)
    assert sembrando is True
    assert [c.uid for c in entrantes] == [1, 2]
    assert estado["last_uid"] == 2 and estado["uidvalidity"] == 3
    assert fake.readonly is True  # el buzón no se toca
    # Sin correo nuevo: incremental vacío, cursor quieto.
    entrantes, estado2, sembrando = cli.fetch_nuevos(estado)
    assert sembrando is False and entrantes == [] and estado2["last_uid"] == 2
    # Llega el 3: solo ese entra.
    fake.correos[3] = _raw(mid="<m3@c.mx>")
    entrantes, estado3, _ = cli.fetch_nuevos(estado2)
    assert [c.uid for c in entrantes] == [3] and estado3["last_uid"] == 3


def test_fetch_uidvalidity_cambiado_resiembra():
    fake = FakeImap({5: _raw(mid="<m5@c.mx>")}, uidvalidity=9)
    cli = _cliente(fake)
    _, estado, sembrando = cli.fetch_nuevos({"uidvalidity": 3, "last_uid": 99, "buzon": "INBOX"})
    assert sembrando is True and estado["uidvalidity"] == 9 and estado["last_uid"] == 5


def test_fetch_backlog_acotado_avanza_sin_saltar():
    fake = FakeImap({u: _raw(mid=f"<m{u}@c.mx>") for u in range(1, 8)})
    cli = _cliente(fake)
    # Incremental (ya sembrado) con tope 3: procesa LOS MÁS VIEJOS y el cursor queda ahí.
    entrantes, estado, _ = cli.fetch_nuevos(
        {"uidvalidity": 3, "last_uid": 0, "buzon": "INBOX"}, cap=3
    )
    assert [c.uid for c in entrantes] == [1, 2, 3]
    assert estado["last_uid"] == 3  # el 4..7 entra la próxima corrida
    entrantes, estado, _ = cli.fetch_nuevos(estado, cap=10)
    assert [c.uid for c in entrantes] == [4, 5, 6, 7]


def test_oauth_no_cableado_lanza_honesto():
    cli = CorreoClient(
        email="a@n.mx", password="", imap_host="h", auth_method="oauth",
        imap_factory=lambda *a: pytest.fail("no debe conectar"),
    )
    with pytest.raises(CorreoNoDisponible, match="contraseña de aplicación"):
        cli.fetch_nuevos(None)
    with pytest.raises(CorreoNoDisponible):
        cli.send("x@y.mx", "hola", "texto")


# ---------- envío SMTP: protocolo real contra servidor local en proceso ----------


class _SmtpHandler(socketserver.StreamRequestHandler):
    """SMTP mínimo (EHLO, AUTH PLAIN, MAIL, RCPT, DATA, QUIT) que graba lo recibido.
    Sin TLS: el test inyecta smtp_factory (la política de transporte es del cliente
    en producción: 465=SSL, otro=STARTTLS obligatorio)."""

    def _w(self, line: str):
        self.wfile.write((line + "\r\n").encode())

    def handle(self):
        server = self.server  # type: ignore[assignment]
        self._w("220 fake-smtp listo")
        buzon: dict = {"from": "", "to": [], "data": ""}
        while True:
            linea = self.rfile.readline().decode(errors="replace").rstrip("\r\n")
            if not linea:
                break
            verbo = linea.split(" ", 1)[0].upper()
            if verbo in ("EHLO", "HELO"):
                self._w("250-fake-smtp")
                self._w("250 AUTH PLAIN LOGIN")
            elif verbo == "AUTH":
                # AUTH PLAIN <b64(\0user\0pass)>
                token = linea.split()[-1]
                try:
                    _, user, password = base64.b64decode(token).decode().split("\0")
                    server.auths.append((user, password))
                except Exception:
                    pass
                self._w("235 autenticado")
            elif verbo == "MAIL":
                buzon["from"] = linea.split(":", 1)[1].strip()
                self._w("250 ok")
            elif verbo == "RCPT":
                buzon["to"].append(linea.split(":", 1)[1].strip())
                self._w("250 ok")
            elif verbo == "DATA":
                self._w("354 manda el cuerpo")
                lineas = []
                while True:
                    l2 = self.rfile.readline().decode(errors="replace")
                    if l2.rstrip("\r\n") == ".":
                        break
                    lineas.append(l2)
                buzon["data"] = "".join(lineas)
                server.mensajes.append(dict(buzon))
                buzon = {"from": "", "to": [], "data": ""}
                self._w("250 aceptado")
            elif verbo == "QUIT":
                self._w("221 adiós")
                break
            else:
                self._w("250 ok")


@pytest.fixture()
def smtp_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SmtpHandler)
    server.mensajes = []  # type: ignore[attr-defined]
    server.auths = []  # type: ignore[attr-defined]
    hilo = threading.Thread(target=server.serve_forever, daemon=True)
    hilo.start()
    yield server
    server.shutdown()
    server.server_close()


def _cliente_smtp(server) -> CorreoClient:
    import smtplib

    host, port = server.server_address
    return CorreoClient(
        email="cobranza@negocio.mx",
        password="app-pass",
        smtp_host=host,
        smtp_port=port,
        # El fake no habla TLS; el factory entrega la conexión ya lista (en producción
        # el default exige SSL/STARTTLS).
        smtp_factory=lambda h, p: smtplib.SMTP(h, p, timeout=5),
    )


def test_send_smtp_protocolo_real_con_auth(smtp_server):
    cli = _cliente_smtp(smtp_server)
    mid = cli.send("ana@cliente.mx", "Recordatorio de pago", "Hola Ana, saldo pendiente.")
    assert mid.startswith("<") and mid.endswith(">")
    assert smtp_server.auths == [("cobranza@negocio.mx", "app-pass")]
    [m] = smtp_server.mensajes
    assert "cobranza@negocio.mx" in m["from"] and any("ana@cliente.mx" in t for t in m["to"])
    assert "Subject: Recordatorio de pago" in m["data"]
    assert f"Message-ID: {mid}" in m["data"]
    assert "Hola Ana" in m["data"]


def test_send_respuesta_enhebra_re_in_reply_to_y_references(smtp_server):
    cli = _cliente_smtp(smtp_server)
    cli.send(
        "ana@cliente.mx",
        asunto_re("Factura F-102"),
        "Va de nuevo la factura.",
        in_reply_to="<m2@cliente.mx>",
        references=("<m1@negocio.mx>", "<m2@cliente.mx>"),
    )
    [m] = smtp_server.mensajes
    assert "Subject: Re: Factura F-102" in m["data"]
    assert "In-Reply-To: <m2@cliente.mx>" in m["data"]
    # References: cadena previa + el respondido, sin duplicar.
    assert "References: <m1@negocio.mx> <m2@cliente.mx>" in m["data"]


def test_verificar_imap_y_smtp_sin_enviar(smtp_server):
    import smtplib

    fake = FakeImap({1: _raw()})
    host, port = smtp_server.server_address
    cli = CorreoClient(
        email="cobranza@negocio.mx", password="app-pass",
        imap_host="imap.negocio.mx", smtp_host=host, smtp_port=port,
        imap_factory=lambda h, p: fake,
        smtp_factory=lambda h, p: smtplib.SMTP(h, p, timeout=5),
    )
    detalles = cli.verificar()
    assert detalles["smtp"] == "listo"
    assert smtp_server.mensajes == []  # verificar NUNCA envía
    assert fake.logins == [("cobranza@negocio.mx", "app-pass")]
