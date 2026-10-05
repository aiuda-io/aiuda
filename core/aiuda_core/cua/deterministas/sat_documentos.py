"""Baja del portal del SAT la Opinión de cumplimiento (32-D) y la Constancia de
situación fiscal, con un guion FIJO de Playwright. Sin IA: aquí nadie "ve" la pantalla
ni decide nada; cada paso está escrito y, si el portal se sale del guion, se detiene.

Entra con la e.firma del dueño. La firma del acceso se hace DENTRO del navegador (así
funciona el login del SAT): el `.cer` y el `.key` se entregan en memoria a los campos
de archivo de la página y la contraseña se teclea únicamente en el campo de contraseña
del SAT. Ninguno de los tres se escribe a disco, a la bitácora, a una captura ni a un
mensaje de error (todo texto que sale de aquí pasa por `_Corrida.limpio`).

Solo consulta y descarga. Los únicos clics que da son: el botón que cambia al
formulario de e.firma, "Enviar" del login y "Generar Constancia". Ante un captcha, un
aviso que pida aceptar o firmar algo, un error del portal o una e.firma rechazada, se
detiene con una captura y el motivo en palabras del dueño.

Hechos del portal en los que se apoya (verificados en vivo en octubre de 2026):
- El login se muestra en dos tiempos: la entrada se reenvía sola a una dirección con
  `option=credential`; ahí `#buttonFiel` cambia al formulario de e.firma
  (`#fileCertificate`, `#filePrivateKey`, `#privateKeyPassword`, `#rfc`, `#submit`).
  En modo e.firma no hay captcha. Una contraseña equivocada la detecta la propia
  página (`#divError`), sin mandar nada.
- 32-D: después del login la página pide sola
  `POST /RespuestaCompleta/ObtenerRespuestaCompletaPdf`, que contesta un JSON con el
  PDF en base64 y el sentido, el folio y el estatus.
- Constancia: es otro proveedor de identidad (otro login). "Generar Constancia" hace
  una llamada y luego abre una ventana con el PDF. Aquí se anula la ventana y el PDF
  se pide desde la misma página (el servidor usa un TLS que solo el navegador acepta).
"""

from __future__ import annotations

import base64
import io
import re
import time
import unicodedata
from dataclasses import dataclass, field

OPINION_32D = "opinion_32d"
CONSTANCIA = "constancia"

# Lo que el PDF tiene que decir para ser ESE documento (sin acentos, en minúsculas).
_FRASE = {
    OPINION_32D: "cumplimiento de obligaciones fiscales",
    CONSTANCIA: "constancia de situacion fiscal",
}
_NOMBRE = {
    OPINION_32D: "la opinión de cumplimiento",
    CONSTANCIA: "la constancia de situación fiscal",
}

MSG_SIN_NAVEGADOR = (
    "Esta instalación de aiuda no trae el navegador que hace falta para entrar al "
    "portal del SAT. La app de escritorio todavía no lo incluye."
)


@dataclass(frozen=True)
class PortalSat:
    """Direcciones y esperas del portal. Las pruebas lo cambian por un portal falso
    local; en producción no se toca."""

    url_32d: str = "https://ptsc32d.clouda.sat.gob.mx/?/reporteOpinion32DContribuyente"
    login_32d: str = "loginda.siat.sat.gob.mx"
    url_constancia: str = (
        "https://rfcampc.siat.sat.gob.mx/app/seg/SessionBroker?url=/PTSC/IdcSiat/autc/"
        "ReimpresionTramite/ConsultaTramite.jsf&parametro=c&idSessionBit=&idSessionBit=null"
    )
    login_constancia: str = "login.siat.sat.gob.mx"
    espera_login_s: float = 25  # cuánto se espera a que aparezca el login
    pausa_reintento_s: float = 15  # antes del único reintento de la entrada
    espera_acceso_s: float = 60  # cuánto se espera a que el SAT acepte la e.firma
    espera_documento_s: float = 90  # cuánto se espera el documento ya adentro


PORTAL = PortalSat()


@dataclass
class DocumentoSat:
    """Lo que trae una corrida: el PDF y sus datos, o por qué se detuvo. Siempre con
    la bitácora de pasos y las capturas (PNG)."""

    ok: bool
    documento: str
    pdf: bytes | None = None
    meta: dict = field(default_factory=dict)  # sentido, folio, estatus (si el SAT los da)
    pasos: list[str] = field(default_factory=list)
    capturas: list[bytes] = field(default_factory=list)
    error: str | None = None


class Alto(Exception):
    """El guion se detuvo. El mensaje es para el dueño, en sus palabras."""


def _sin_acentos(texto: str) -> str:
    plano = unicodedata.normalize("NFD", texto)
    return "".join(c for c in plano if unicodedata.category(c) != "Mn").lower()


def validar_pdf(pdf: bytes, rfc: str, documento: str) -> None:
    """Que lo descargado sea un PDF de verdad, de ESE RFC y del documento pedido.
    Lanza `Alto` si no."""
    if not pdf.startswith(b"%PDF"):
        raise Alto("Lo que entregó el SAT no es un PDF. No se guardó nada.")
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            texto = " ".join((p.extract_text() or "") for p in doc.pages)
    except Exception:
        raise Alto("El PDF que entregó el SAT no se pudo leer. No se guardó nada.") from None
    plano = re.sub(r"\s+", " ", texto)
    if rfc.upper() not in plano.upper():
        raise Alto(f"El PDF que entregó el SAT no menciona el RFC {rfc}. No se guardó nada.")
    if _FRASE[documento] not in _sin_acentos(plano):
        raise Alto(
            f"El PDF que entregó el SAT no es {_NOMBRE[documento]}. No se guardó nada."
        )


def _motivo_rechazo(texto: str) -> str:
    """El error del formulario de acceso del SAT, dicho para el dueño."""
    plano = _sin_acentos(texto)
    if "revocad" in plano:
        return (
            "El SAT dice que tu e.firma está revocada. Tramita una nueva en el SAT y "
            "vuelve a cargarla en SAT · Bóveda fiscal."
        )
    if "vigente" in plano or "caduc" in plano or "vencid" in plano:
        return (
            "El SAT dice que tu e.firma ya no está vigente. Renuévala en el SAT y "
            "vuelve a cargarla en SAT · Bóveda fiscal."
        )
    if "invalid" in plano or "contrasena" in plano:
        return (
            "El portal del SAT no aceptó la e.firma guardada: el certificado, la llave "
            "o la contraseña no coinciden. Vuelve a cargarla en SAT · Bóveda fiscal."
        )
    return f"El SAT rechazó el acceso con la e.firma: {texto.strip()[:200]}"


# Botones visibles que piden aceptar o firmar algo. Solo se mira cuando lo esperado no
# aparece: aiuda nunca les da clic, se detiene y lo dice.
_JS_PIDE_ACEPTAR = """() => {
  const re = /(acept|firmar|autoriz|estoy de acuerdo)/i;
  const nodos = document.querySelectorAll(
    'button, input[type=button], input[type=submit], a.btn, [role=button]');
  for (const n of nodos) {
    const texto = (n.innerText || n.value || '').trim();
    const visible = n.offsetWidth > 0 && n.offsetHeight > 0;
    if (visible && texto.length < 60 && re.test(texto)) return texto;
  }
  return '';
}"""

_JS_BAJAR_PDF = """async (ruta) => {
  const r = await fetch(ruta, {credentials: 'include'});
  const b = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < b.length; i += 8192) {
    s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
  }
  return [r.status, btoa(s)];
}"""


class _Corrida:
    """El estado de una corrida: la página, la bitácora y las capturas."""

    def __init__(self, page, portal: PortalSat, password: str):
        self.page = page
        self.portal = portal
        self._password = password
        self.pasos: list[str] = []
        self.capturas: list[bytes] = []
        self.dialogo: str | None = None
        page.on("dialog", self._al_dialogo)

    def _al_dialogo(self, dialogo) -> None:
        # Un alert/confirm del portal: se anota y se CIERRA sin aceptar.
        self.dialogo = (dialogo.message or "")[:200]
        try:
            dialogo.dismiss()
        except Exception:
            pass

    def limpio(self, texto: str) -> str:
        """Ningún texto que salga de aquí lleva la contraseña."""
        if self._password:
            texto = texto.replace(self._password, "***")
        return texto

    def paso(self, texto: str) -> None:
        self.pasos.append(self.limpio(texto))

    def foto(self) -> None:
        try:
            self.capturas.append(self.page.screenshot())
        except Exception:
            pass

    def revisar_avisos(self) -> None:
        """Detiene la corrida si el portal pide aceptar, firmar o confirmar algo."""
        if self.dialogo is not None:
            raise Alto(
                "El portal del SAT abrió un aviso que pide confirmar algo "
                f"(«{self.dialogo}»). aiuda no acepta nada por ti: entra tú al portal "
                "para revisarlo."
            )
        try:
            boton = self.page.evaluate(_JS_PIDE_ACEPTAR)
        except Exception:
            return  # la página está navegando: se revisa en la siguiente vuelta
        if boton:
            raise Alto(
                f"El portal del SAT pide aceptar o firmar algo (botón «{boton}»). "
                "aiuda no acepta ni firma nada por ti: entra tú al portal para revisarlo."
            )


def _entrar(c: _Corrida, url: str, marca_login: str, cer: bytes, key: bytes, rfc: str) -> None:
    """Abre `url`, cae en el login del SAT y entra con la e.firma. La ENTRADA se
    reintenta una vez (a veces contesta un error 500); el login no se reintenta."""
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout

    pg, portal = c.page, c.portal
    for intento in (1, 2):
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_url(
                lambda u: "option=credential" in u, timeout=portal.espera_login_s * 1000
            )
            break
        except PWError:  # incluye el timeout
            c.foto()
            if intento == 2:
                raise Alto(
                    "El portal del SAT no mostró su pantalla de acceso (contestó con un "
                    "error o no respondió). Suele ser pasajero: inténtalo más tarde."
                ) from None
            c.paso("El SAT no mostró la pantalla de acceso. Espero y lo intento una vez más.")
            pg.wait_for_timeout(portal.pausa_reintento_s * 1000)
    pg.wait_for_load_state("load")
    c.paso("El SAT mostró su pantalla de acceso.")
    c.foto()

    # El botón de e.firma solo cambia de formulario (no manda nada). Con ventana visible
    # el primer clic a veces se pierde: se repite hasta 3 veces.
    for _ in range(3):
        if pg.locator("#fileCertificate").count():
            break
        try:
            pg.click("#buttonFiel", timeout=10000)
            pg.wait_for_selector("#fileCertificate", state="attached", timeout=10000)
        except PWTimeout:
            pass
    else:
        c.foto()
        raise Alto(
            "El portal del SAT no mostró el formulario de e.firma. Puede que haya "
            "cambiado su pantalla de acceso."
        )
    pg.wait_for_load_state("load")
    if pg.locator("#userCaptcha:visible").count():
        c.foto()
        raise Alto(
            "El portal del SAT está pidiendo un captcha para entrar con e.firma. aiuda "
            "no los resuelve; inténtalo más tarde."
        )

    def archivo(nombre: str, contenido: bytes) -> dict:
        return {"name": nombre, "mimeType": "application/octet-stream", "buffer": contenido}

    pg.set_input_files("#fileCertificate", archivo(f"{rfc}.cer", cer))
    pg.set_input_files("#filePrivateKey", archivo(f"{rfc}.key", key))
    c.paso("Cargué el certificado y la llave de la e.firma en el formulario del SAT.")
    c.foto()  # ANTES de teclear la contraseña: no sale en ninguna captura
    try:
        pg.fill("#privateKeyPassword", c._password)
    except Exception:
        raise Alto("No se pudo escribir en el campo de contraseña del SAT.") from None
    del_formulario = (pg.input_value("#rfc") or "").strip().upper()
    if del_formulario and del_formulario != rfc.upper():
        _vaciar_contrasena(pg)
        raise Alto(
            f"La e.firma guardada es del RFC {del_formulario}, no de {rfc}. No se entró."
        )
    pg.click("#submit")
    c.paso("Escribí la contraseña en el campo del SAT y envié el acceso.")

    limite = time.monotonic() + portal.espera_acceso_s
    while time.monotonic() < limite:
        if marca_login not in pg.url:
            c.paso("El SAT aceptó la e.firma.")
            return
        error = pg.locator("#divError:visible")
        if error.count():
            texto = (error.first.inner_text() or "").strip()
            if texto:
                _vaciar_contrasena(pg)
                c.foto()
                raise Alto(_motivo_rechazo(texto))
        if c.dialogo is not None:
            c.revisar_avisos()
        pg.wait_for_timeout(500)
    _vaciar_contrasena(pg)
    c.foto()
    raise Alto(
        "El portal del SAT no terminó el acceso con la e.firma en un minuto. "
        "Inténtalo más tarde."
    )


def _vaciar_contrasena(pg) -> None:
    """Antes de una captura de la pantalla de acceso: el campo queda vacío."""
    try:
        pg.fill("#privateKeyPassword", "", timeout=2000)
    except Exception:
        pass


def _opinion_32d(c: _Corrida, cer: bytes, key: bytes, rfc: str) -> tuple[bytes, dict]:
    pg, portal = c.page, c.portal
    visto: dict = {}

    def al_responder(respuesta) -> None:
        if "ObtenerRespuestaCompletaPdf" in respuesta.url:
            visto.setdefault("r", respuesta)

    pg.on("response", al_responder)
    c.paso("Abrí la consulta de la opinión de cumplimiento en el portal del SAT.")
    _entrar(c, portal.url_32d, portal.login_32d, cer, key, rfc)

    limite = time.monotonic() + portal.espera_documento_s
    while "r" not in visto and time.monotonic() < limite:
        c.revisar_avisos()
        pg.wait_for_timeout(500)
    if "r" not in visto:
        c.foto()
        raise Alto(
            "Entré al portal del SAT pero no entregó la opinión de cumplimiento. "
            "Inténtalo más tarde."
        )
    try:
        cuerpo = visto["r"].json()
    except Exception:
        c.foto()
        raise Alto(
            "El SAT contestó la opinión de cumplimiento con algo que no se pudo leer."
        ) from None
    respuesta = cuerpo.get("Respuesta") or {}
    validaciones = cuerpo.get("Validaciones") or {}
    if not respuesta.get("Exito") or not cuerpo.get("ContenidoBase64"):
        c.foto()
        mensaje = str(respuesta.get("Mensaje") or "sin explicación")[:200]
        raise Alto(f"El SAT no entregó la opinión de cumplimiento: {mensaje}")
    pdf = base64.b64decode(cuerpo["ContenidoBase64"])
    pg.wait_for_timeout(1500)  # que la página termine de pintar el documento
    c.foto()
    meta = {
        "sentido": validaciones.get("Descripcion") or None,
        "folio": validaciones.get("Folio") or None,
        "estatus": validaciones.get("Estatus") or None,
    }
    c.paso("El SAT entregó la opinión de cumplimiento.")
    return pdf, meta


def _constancia(c: _Corrida, cer: bytes, key: bytes, rfc: str) -> tuple[bytes, dict]:
    pg, portal = c.page, c.portal
    c.paso("Abrí la reimpresión de la constancia de situación fiscal en el portal del SAT.")
    _entrar(c, portal.url_constancia, portal.login_constancia, cer, key, rfc)

    boton = pg.get_by_role("button", name="Generar Constancia")
    limite = time.monotonic() + portal.espera_documento_s
    while time.monotonic() < limite:
        try:
            if boton.count() and boton.first.is_visible():
                break
        except Exception:
            pass  # navegando todavía
        c.revisar_avisos()
        pg.wait_for_timeout(500)
    else:
        c.foto()
        raise Alto(
            "Entré al portal del SAT pero no apareció «Generar Constancia». Puede que "
            "el portal haya cambiado o esté fallando; inténtalo más tarde."
        )
    c.foto()
    # El botón hace una llamada (prepara la constancia) y después abre una ventana con
    # el PDF. Se anula la ventana y se pide el mismo PDF desde la página.
    pg.evaluate("window.open = () => null")
    try:
        with pg.expect_response(
            lambda r: r.request.method == "POST" and "ConsultaTramite.jsf" in r.url,
            timeout=portal.espera_documento_s * 1000,
        ):
            boton.first.click()
    except Exception:
        c.foto()
        raise Alto(
            "Pedí la constancia y el portal del SAT no contestó. Inténtalo más tarde."
        ) from None
    c.paso("Pedí la constancia con «Generar Constancia».")
    c.revisar_avisos()
    estado, b64 = pg.evaluate(_JS_BAJAR_PDF, "/PTSC/IdcSiat/IdcGeneraConstancia.jsf")
    pdf = base64.b64decode(b64)
    if estado != 200 or not pdf.startswith(b"%PDF"):
        c.foto()
        raise Alto(
            f"El SAT no entregó la constancia (contestó {estado} y no un PDF). "
            "Inténtalo más tarde."
        )
    c.foto()
    c.paso("El SAT entregó la constancia de situación fiscal.")
    return pdf, {}


_GUIONES = {OPINION_32D: _opinion_32d, CONSTANCIA: _constancia}


def bajar_documento(
    cer: bytes,
    key: bytes,
    password: str,
    rfc: str,
    documento: str,
    *,
    portal: PortalSat | None = None,
    headless: bool = True,
) -> DocumentoSat:
    """Entra al SAT con la e.firma y baja `documento` (OPINION_32D o CONSTANCIA) del
    `rfc`. Nunca lanza: devuelve `ok=False` con el motivo, la bitácora y las capturas.

    Cada llamada es UNA visita al portal en un navegador limpio que se cierra al
    terminar. No reintenta el login ni la descarga."""
    if documento not in _GUIONES:
        raise ValueError(f"Documento desconocido: {documento!r}")
    out = DocumentoSat(ok=False, documento=documento)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        out.error = MSG_SIN_NAVEGADOR
        return out

    corrida: _Corrida | None = None
    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch(headless=headless)
            try:
                contexto = navegador.new_context(
                    locale="es-MX", viewport={"width": 1280, "height": 900}
                )
                corrida = _Corrida(contexto.new_page(), portal or PORTAL, password)
                pdf, meta = _GUIONES[documento](corrida, cer, key, rfc)
                validar_pdf(pdf, rfc, documento)
                corrida.paso(f"Comprobé que el PDF es de {rfc} y es el documento pedido.")
                out.ok, out.pdf, out.meta = True, pdf, meta
            except Alto as alto:
                out.error = corrida.limpio(str(alto)) if corrida else str(alto)
            finally:
                if corrida is not None:
                    out.pasos, out.capturas = corrida.pasos, corrida.capturas
                navegador.close()
    except Exception as exc:  # el portal se salió del guion o el navegador no arrancó
        detalle = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        if password:
            detalle = detalle.replace(password, "***")
        out.pasos.append(f"Detalle técnico: {detalle}")
        out.error = (
            "El portal del SAT se comportó distinto a lo esperado y la rutina se "
            "detuvo sin bajar nada. Inténtalo más tarde."
        )
    return out
