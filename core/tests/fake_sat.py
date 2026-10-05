"""Portal FALSO del SAT para pruebas. No es parte de la app.

Imita, en chiquito, lo que la rutina determinista encontró en el portal real: la
entrada que se reenvía sola a un login con `option=credential`, el botón que cambia al
formulario de e.firma, la validación de la contraseña EN LA PÁGINA (nada viaja), la
consulta 32-D que la página pide sola por POST y la constancia que se genera con un
botón y luego se abre en otra ventana.

Todos los datos son inventados y los PDF son sintéticos. Que algo pase contra este
servidor prueba que el guion hace lo que dice; NO prueba que el SAT siga igual: eso
solo lo dice una corrida real.

Uso:  with FakeSat() as falso: ...  (falso.portal(), falso.modo, falso.visto)
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from pdf_sintetico import construir_pdf

RFC = "HCO250213281"
PASSWORD = "clave-de-prueba"
FOLIO = "26NM0000001"

ERROR_INVALIDA = (
    "Certificado, clave privada o contraseña de clave privada inválidos, "
    "inténtelo nuevamente."
)
ERROR_REVOCADA = "No se puede acceder al aplicativo porque su E.FIRMA está revocada."
ERROR_NO_VIGENTE = "No se puede acceder al aplicativo porque su E.FIRMA no está vigente."

RUTA_CONSTANCIA = "/PTSC/IdcSiat/autc/ReimpresionTramite/ConsultaTramite.jsf"
RUTA_PDF_CONSTANCIA = "/PTSC/IdcSiat/IdcGeneraConstancia.jsf"
RUTA_32D = "/RespuestaCompleta/ObtenerRespuestaCompletaPdf"


def pdf_opinion(rfc: str = RFC, sentido: str = "POSITIVO") -> bytes:
    return construir_pdf([[
        (60, 60, "Opinion del cumplimiento de obligaciones fiscales"),
        (60, 90, "EMPRESA DE PRUEBA SA DE CV"),
        (60, 110, f"RFC {rfc}"),
        (60, 130, f"Sentido {sentido}"),
        (60, 150, f"Folio {FOLIO}"),
        (60, 190, "Documento sintetico de prueba. No es del SAT."),
    ]], tam=10)


def pdf_constancia(rfc: str = RFC) -> bytes:
    return construir_pdf([[
        (60, 60, "CONSTANCIA DE SITUACION FISCAL"),
        (60, 90, "EMPRESA DE PRUEBA SA DE CV"),
        (60, 110, f"RFC: {rfc}"),
        (60, 150, "Documento sintetico de prueba. No es del SAT."),
    ]], tam=10)


_REENVIO = """<!doctype html><meta charset="utf-8"><title>Entrando</title>
<form id="f" method="get" action="/nidp/login">
<input type="hidden" name="option" value="credential">
<input type="hidden" name="destino" value="%s"></form>
<script>document.getElementById('f').submit()</script>"""

_LOGIN = """<!doctype html><meta charset="utf-8"><title>Acceso (portal de prueba)</title>
<h1>Portal de prueba local: acceso</h1>
<p>Usuario <input id="rfcUsuario"> Contraseña <input id="password" type="password"></p>
%(captcha)s
<button id="buttonFiel" type="button">e.firma</button>
<script>
document.getElementById('buttonFiel').onclick = () => {
  location.href = location.pathname + location.search + '&id=fiel';
};
</script>"""

_FIEL = """<!doctype html><meta charset="utf-8"><title>Acceso con e.firma (portal de prueba)</title>
<h1>Portal de prueba local: acceso con e.firma</h1>
<input id="fileCertificate" type="file" style="display:none">
<input id="filePrivateKey" type="file" style="display:none">
<p>Contraseña de clave privada: <input id="privateKeyPassword" type="password"></p>
<p>RFC: <input id="rfc" readonly></p>
%(captcha)s%(aviso)s
<div id="divError" style="display:none;color:#a00"></div>
<button id="submit" type="button">Enviar</button>
<script>
const cer = document.getElementById('fileCertificate');
cer.onchange = () => { document.getElementById('rfc').value = %(rfc)s; };
document.getElementById('submit').onclick = () => {
  const err = document.getElementById('divError');
  const key = document.getElementById('filePrivateKey');
  const pw = document.getElementById('privateKeyPassword').value;
  let error = %(error)s;
  if (!error && (!cer.files.length || !key.files.length || pw !== %(password)s)) {
    error = %(invalida)s;
  }
  if (error) { err.textContent = error; err.style.display = 'block'; return; }
  document.cookie = 'sesion=1; path=/';
  location.href = %(destino)s;
};
</script>"""

_OPINION = """<!doctype html><meta charset="utf-8"><title>Opinión (portal de prueba)</title>
<h1>Portal de prueba local: opinión de cumplimiento</h1>
<p id="estado">Consultando…</p>%s
<script>
fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
  .then(r => r.json())
  .then(j => { document.getElementById('estado').textContent =
    'Sentido: ' + ((j.Validaciones || {}).Descripcion || 'sin dato'); });
</script>"""

_ACEPTAR = """<!doctype html><meta charset="utf-8"><title>Aviso (portal de prueba)</title>
<h1>Portal de prueba local: términos</h1>
<p>Antes de continuar debes aceptar los nuevos términos.</p>
<button id="aceptar" type="button" onclick="fetch('/_acepto', {method: 'POST'})">Aceptar términos</button>"""

_CONSTANCIA = """<!doctype html><meta charset="utf-8"><title>Reimpresión (portal de prueba)</title>
<h1>Portal de prueba local: reimpresión de acuses</h1>
<button type="button">Limpiar</button> <button type="button">Buscar</button>
<button id="j_idt42" type="button">Generar Constancia</button>%s
<script>
document.getElementById('j_idt42').onclick = async () => {
  await fetch(location.pathname, {method: 'POST', body: 'generar=1'});
  window.open('%s');
};
</script>"""

_CAPTCHA = '<p>Captcha: <input id="userCaptcha"></p>'
# Un aviso con botón de aceptar que convive con la pantalla normal (no la reemplaza).
_BOTON_ACEPTAR = (
    '<p>Aviso de privacidad <button type="button" '
    "onclick=\"fetch('/_acepto', {method: 'POST'})\">Aceptar</button></p>"
)


class FakeSat:
    """El portal en un puerto local. `modo` cambia cómo se porta; `visto` guarda cada
    petición (método, ruta con query, cuerpo) para que la prueba revise qué viajó."""

    def __init__(self):
        self.modo = {
            "entrada_500": 0,  # cuántas veces la entrada contesta el error 500
            "captcha": False,
            "login": "ok",  # ok | revocada | no_vigente
            "aviso_login": "",  # alert | confirm: diálogo al abrir el formulario de e.firma
            "boton_aceptar": False,  # un «Aceptar» visible junto a la pantalla normal
            "rfc_formulario": RFC,
            "tras_login": "ok",  # ok | aceptar (pide aceptar términos) | dialogo
            "opinion": "ok",  # ok | sin_exito | otro_rfc | no_pdf
            "sentido": "Positivo",
            "constancia": "ok",  # ok | otro_rfc | html | otro_documento
        }
        self.visto: list[tuple[str, str, str]] = []
        self._candado = threading.Lock()
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self._http.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self._http.shutdown()
        self._http.server_close()
        return False

    def portal(self, **esperas):
        """El `PortalSat` que apunta a este servidor, con esperas cortas."""
        from aiuda_core.cua.deterministas.sat_documentos import PortalSat

        base = {
            "espera_login_s": 4, "pausa_reintento_s": 0.2,
            "espera_acceso_s": 6, "espera_documento_s": 4, "gracia_aviso_s": 0.6,
        }
        return PortalSat(
            url_32d=f"{self.base}/opinion",
            login_32d="/nidp/",
            url_constancia=f"{self.base}{RUTA_CONSTANCIA}",
            login_constancia="/nidp/",
            **{**base, **esperas},
        )

    def rutas(self, metodo: str | None = None) -> list[str]:
        return [r.split("?")[0] for m, r, _ in self.visto if metodo in (None, m)]

    def _handler(self):
        falso = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silencioso
                pass

            def _enviar(self, cuerpo, tipo="text/html; charset=utf-8", estado=200):
                if isinstance(cuerpo, str):
                    cuerpo = cuerpo.encode()
                self.send_response(estado)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def _anotar(self, cuerpo=""):
                with falso._candado:
                    falso.visto.append((self.command, self.path, cuerpo))

            def _con_sesion(self) -> bool:
                return "sesion=1" in (self.headers.get("Cookie") or "")

            def do_GET(self):
                self._anotar()
                url = urlsplit(self.path)
                query = parse_qs(url.query)
                modo = falso.modo
                if url.path in ("/opinion", RUTA_CONSTANCIA):
                    destino = "opinion" if url.path == "/opinion" else "constancia"
                    if not self._con_sesion():
                        with falso._candado:
                            falla = modo["entrada_500"] > 0
                            if falla:
                                modo["entrada_500"] -= 1
                        if falla:
                            return self._enviar(
                                "Error: HTTP 500 Internal Server Error", "text/plain", 500
                            )
                        return self._enviar(_REENVIO % destino)
                    if modo["tras_login"] == "aceptar":
                        return self._enviar(_ACEPTAR)
                    if modo["tras_login"] == "dialogo":
                        return self._enviar(
                            "<!doctype html><script>confirm('¿Acepta el aviso?')</script>"
                        )
                    extra = _BOTON_ACEPTAR if modo["boton_aceptar"] else ""
                    if destino == "opinion":
                        return self._enviar(_OPINION % (extra, RUTA_32D))
                    return self._enviar(_CONSTANCIA % (extra, RUTA_PDF_CONSTANCIA))
                if url.path == "/nidp/login":
                    captcha = _CAPTCHA if modo["captcha"] else ""
                    if "id" not in query:
                        return self._enviar(_LOGIN % {"captcha": captcha})
                    destino = (query.get("destino") or ["opinion"])[0]
                    error = {
                        "revocada": ERROR_REVOCADA, "no_vigente": ERROR_NO_VIGENTE,
                    }.get(modo["login"], "")
                    aviso = {
                        "alert": "<script>alert('Aviso: mantenimiento el sábado')</script>",
                        "confirm": "<script>confirm('¿Acepta los nuevos términos?')</script>",
                    }.get(modo["aviso_login"], "")
                    return self._enviar(_FIEL % {
                        "captcha": captcha,
                        "aviso": aviso,
                        "rfc": json.dumps(modo["rfc_formulario"]),
                        "error": json.dumps(error),
                        "password": json.dumps(PASSWORD),
                        "invalida": json.dumps(ERROR_INVALIDA),
                        "destino": json.dumps(
                            "/opinion" if destino == "opinion" else RUTA_CONSTANCIA
                        ),
                    })
                if url.path == RUTA_PDF_CONSTANCIA:
                    c = modo["constancia"]
                    if c == "html":
                        return self._enviar("<h1>Sesión expirada</h1>")
                    if c == "otro_documento":
                        return self._enviar(pdf_opinion(), "application/pdf")
                    rfc = "XAXX010101000" if c == "otro_rfc" else RFC
                    return self._enviar(pdf_constancia(rfc), "application/pdf")
                self._enviar("No existe", "text/plain", 404)

            def do_POST(self):
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(largo).decode("utf-8", "replace")
                self._anotar(cuerpo)
                url = urlsplit(self.path)
                modo = falso.modo
                if url.path == RUTA_32D:
                    o = modo["opinion"]
                    if o == "sin_exito":
                        return self._enviar(json.dumps({
                            "ContenidoBase64": None, "Validaciones": None,
                            "Respuesta": {"Exito": False, "Mensaje": "Servicio no disponible"},
                        }), "application/json")
                    pdf = pdf_opinion("XAXX010101000" if o == "otro_rfc" else RFC)
                    if o == "no_pdf":
                        pdf = b"<html>no soy un pdf</html>"
                    return self._enviar(json.dumps({
                        "ContenidoBase64": base64.b64encode(pdf).decode(),
                        "Validaciones": {
                            "Descripcion": modo["sentido"], "Valor": "1",
                            "Estatus": "Vigente", "Folio": FOLIO,
                        },
                        "Respuesta": {"Exito": True, "Mensaje": ""},
                    }), "application/json")
                self._enviar("{}", "application/json")

        return Handler
