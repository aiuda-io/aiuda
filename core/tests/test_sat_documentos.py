"""La rutina determinista del SAT contra un portal FALSO local (fake_sat.py).

Lo que amarran estas pruebas: que el guion baja los dos documentos, que valida que el
PDF sea del RFC y del documento pedido, que se detiene (sin dar clic a nada más) ante
captcha, avisos de aceptar, errores del portal y e.firma rechazada, y que la contraseña
no viaja ni aparece en la bitácora o en el error.

Los PDF son sintéticos. Las que abren navegador se saltan solas si falta Chromium.
"""

import pytest

from aiuda_core.cua.deterministas import sat_documentos as sd
from aiuda_core.cua.deterministas.sat_documentos import (
    CONSTANCIA,
    OPINION_32D,
    Alto,
    bajar_documento,
    validar_pdf,
)
from fake_sat import (
    FOLIO,
    PASSWORD,
    RFC,
    RUTA_32D,
    RUTA_CONSTANCIA,
    RUTA_PDF_CONSTANCIA,
    FakeSat,
    pdf_constancia,
    pdf_opinion,
)

CER, KEY = b"certificado de prueba", b"llave de prueba"
PNG = b"\x89PNG"


@pytest.fixture(scope="module")
def chromium():
    from aiuda_core.cua.computer import estado_navegador

    listo, detalle = estado_navegador()
    if not listo:
        pytest.skip(detalle)


@pytest.fixture()
def sat(chromium):
    with FakeSat() as falso:
        yield falso


def bajar(sat, documento, password=PASSWORD, **esperas):
    return bajar_documento(CER, KEY, password, RFC, documento, portal=sat.portal(**esperas))


def sin_contrasena(sat, resultado, password=PASSWORD):
    """La contraseña no viajó al portal ni quedó en lo que la rutina devuelve."""
    for metodo, ruta, cuerpo in sat.visto:
        assert password not in ruta and password not in cuerpo, (metodo, ruta)
    assert password not in " ".join(resultado.pasos)
    assert password not in (resultado.error or "")


# --- Validación del PDF (sin navegador) ------------------------------------------


def test_validar_pdf_acepta_el_documento_del_rfc():
    validar_pdf(pdf_opinion(), RFC, OPINION_32D)
    validar_pdf(pdf_constancia(), RFC, CONSTANCIA)


def test_validar_pdf_rechaza_lo_que_no_es():
    with pytest.raises(Alto, match="no es un PDF"):
        validar_pdf(b"<html>error</html>", RFC, OPINION_32D)
    with pytest.raises(Alto, match="no menciona el RFC"):
        validar_pdf(pdf_opinion("XAXX010101000"), RFC, OPINION_32D)
    with pytest.raises(Alto, match="no es la constancia"):
        validar_pdf(pdf_opinion(), RFC, CONSTANCIA)
    with pytest.raises(Alto, match="no se pudo leer"):
        validar_pdf(b"%PDF-1.4 basura", RFC, OPINION_32D)


def test_documento_desconocido_no_abre_nada():
    with pytest.raises(ValueError):
        bajar_documento(CER, KEY, PASSWORD, RFC, "declaracion_anual")


def test_sin_playwright_lo_dice_sin_tronar(monkeypatch):
    import builtins

    real = builtins.__import__

    def sin_playwright(nombre, *a, **k):
        if nombre.startswith("playwright"):
            raise ImportError(nombre)
        return real(nombre, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sin_playwright)
    r = bajar_documento(CER, KEY, PASSWORD, RFC, OPINION_32D)
    assert r.ok is False and r.error == sd.MSG_SIN_NAVEGADOR


# --- El guion completo -----------------------------------------------------------


def test_baja_la_opinion_de_cumplimiento(sat):
    r = bajar(sat, OPINION_32D)
    assert r.ok, r.error
    assert r.pdf == pdf_opinion()
    assert r.meta == {"sentido": "Positivo", "folio": FOLIO, "estatus": "Vigente"}
    assert r.error is None
    assert len(r.capturas) >= 3 and all(c.startswith(PNG) for c in r.capturas)
    assert any("aceptó la e.firma" in p for p in r.pasos)
    # Una sola consulta: cada una le saca un folio nuevo al SAT.
    assert sat.rutas("POST") == [RUTA_32D]
    sin_contrasena(sat, r)


def test_baja_la_constancia_sin_abrir_la_ventana(sat):
    r = bajar(sat, CONSTANCIA)
    assert r.ok, r.error
    assert r.pdf == pdf_constancia()
    assert r.meta == {}
    assert sat.rutas("POST") == [RUTA_CONSTANCIA]
    # El PDF se pidió UNA vez (desde la página); la ventana del portal quedó anulada.
    assert sat.rutas("GET").count(RUTA_PDF_CONSTANCIA) == 1
    sin_contrasena(sat, r)


def test_reintenta_la_entrada_una_vez_si_el_sat_da_500(sat):
    sat.modo["entrada_500"] = 1
    r = bajar(sat, OPINION_32D, espera_login_s=1.5)
    assert r.ok, r.error
    assert sat.rutas("GET").count("/opinion") == 3  # falla, entra, y de regreso ya adentro
    assert any("lo intento una vez más" in p for p in r.pasos)


def test_dos_fallas_de_entrada_y_se_detiene_sin_llegar_al_login(sat):
    sat.modo["entrada_500"] = 5
    r = bajar(sat, OPINION_32D, espera_login_s=1.5)
    assert not r.ok and "no mostró su pantalla de acceso" in r.error
    assert sat.rutas("GET") == ["/opinion", "/opinion"]  # dos y ya: sin ciclo
    assert r.capturas and r.pdf is None


# --- Se detiene, con motivo claro -------------------------------------------------


def test_contrasena_equivocada_se_detiene_y_no_se_filtra(sat):
    mala = "contrasena-equivocada-123"
    r = bajar(sat, OPINION_32D, password=mala)
    assert not r.ok and "no aceptó la e.firma guardada" in r.error
    assert RUTA_32D not in sat.rutas()  # nunca entró
    assert r.capturas
    sin_contrasena(sat, r, password=mala)


@pytest.mark.parametrize(
    "modo,dice", [("revocada", "está revocada"), ("no_vigente", "ya no está vigente")]
)
def test_efirma_revocada_o_vencida(sat, modo, dice):
    sat.modo["login"] = modo
    r = bajar(sat, CONSTANCIA)
    assert not r.ok and dice in r.error
    assert sat.rutas("POST") == []


def test_captcha_se_detiene_antes_de_cargar_la_efirma(sat):
    sat.modo["captcha"] = True
    r = bajar(sat, OPINION_32D)
    assert not r.ok and "captcha" in r.error
    assert not any("Cargué el certificado" in p for p in r.pasos)
    assert RUTA_32D not in sat.rutas()


def test_la_efirma_de_otro_rfc_no_se_envia(sat):
    sat.modo["rfc_formulario"] = "XAXX010101000"
    r = bajar(sat, OPINION_32D)
    assert not r.ok and "XAXX010101000" in r.error
    assert RUTA_32D not in sat.rutas()


@pytest.mark.parametrize("documento", [OPINION_32D, CONSTANCIA])
def test_si_el_portal_pide_aceptar_algo_no_lo_acepta(sat, documento):
    sat.modo["tras_login"] = "aceptar"
    r = bajar(sat, documento)
    assert not r.ok and "pide aceptar o firmar" in r.error and "Aceptar términos" in r.error
    assert "/_acepto" not in sat.rutas()
    assert sat.rutas("POST") == []
    assert r.capturas


def test_un_aviso_de_confirmar_se_cierra_sin_aceptar(sat):
    sat.modo["tras_login"] = "dialogo"
    r = bajar(sat, CONSTANCIA)
    assert not r.ok and "pide confirmar algo" in r.error


def test_el_sat_no_entrega_la_opinion(sat):
    sat.modo["opinion"] = "sin_exito"
    r = bajar(sat, OPINION_32D)
    assert not r.ok and "Servicio no disponible" in r.error and r.pdf is None


@pytest.mark.parametrize(
    "documento,llave,modo,dice",
    [
        (OPINION_32D, "opinion", "otro_rfc", "no menciona el RFC"),
        (OPINION_32D, "opinion", "no_pdf", "no es un PDF"),
        (CONSTANCIA, "constancia", "otro_rfc", "no menciona el RFC"),
        (CONSTANCIA, "constancia", "otro_documento", "no es la constancia"),
        (CONSTANCIA, "constancia", "html", "no un PDF"),
    ],
)
def test_no_guarda_un_pdf_que_no_es_el_del_rfc(sat, documento, llave, modo, dice):
    sat.modo[llave] = modo
    r = bajar(sat, documento)
    assert not r.ok and dice in r.error and r.pdf is None
