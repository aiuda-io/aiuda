"""Las dos rutinas sin IA del SAT por el camino del producto: e.firma guardada por la
API, permiso del dueño, POST /v1/cua/misiones, la corrida y el PDF servido.

El portal es el FALSO local (core/tests/fake_sat.py) y los PDF son sintéticos. Lo que
se amarra: corren sin ninguna IA conectada, no corren sin el permiso del dueño, el
documento queda guardado por negocio y la contraseña no aparece en nada de lo que la
API devuelve ni en el recado.
"""

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.connectors import credentials as cred
from aiuda_core.cua.deterministas import sat_documentos
from aiuda_core.cua.fallback import (
    CONSENTIMIENTO_SAT_TEXTO,
    consentimiento_sat,
    ejecutar_recado,
)
from aiuda_core.models import Base, CuaMission, Documento, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("satcfdi")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "core" / "tests"))
from fake_sat import PASSWORD, RFC, FakeSat, pdf_constancia, pdf_opinion  # noqa: E402
from test_sat_efirma import efirma_prueba  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def demo(db_session, client, demo_login):
    t = Tenant(
        name="Demo", owner_phone="52155", evolution_instance="demo-rutinas-sat",
        config={"demo": True, "members": []},
    )
    db_session.add(t)
    db_session.flush()
    demo_login(client)
    return t


@pytest.fixture(scope="module")
def fiel():
    return efirma_prueba(password=PASSWORD)


@pytest.fixture()
def corridas(db_session, monkeypatch):
    """La corrida de fondo usa la sesión de la prueba (en producción abre la suya) y
    una IA que truena si alguien la pide: estas rutinas no la tocan."""
    hechas = []

    def sin_ia():
        raise AssertionError("una rutina determinista no debe pedir IA")

    def correr(recado_id):
        hechas.append(recado_id)
        ejecutar_recado(db_session, db_session.get(CuaMission, recado_id), ia=sin_ia)

    monkeypatch.setattr("aiuda_server.api.cua.run_recado_blocking", correr)
    return hechas


@pytest.fixture()
def sat(monkeypatch):
    from aiuda_core.cua.computer import estado_navegador

    listo, detalle = estado_navegador()
    if not listo:
        pytest.skip(detalle)
    with FakeSat() as falso:
        monkeypatch.setattr(sat_documentos, "PORTAL", falso.portal())
        yield falso


def subir_efirma(client, fiel):
    cer, key = fiel
    r = client.post(
        "/v1/sat/efirma",
        files={
            "cer": ("firma.cer", cer, "application/octet-stream"),
            "key": ("firma.key", key, "application/octet-stream"),
        },
        data={"password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def aceptar(client, rfc=RFC):
    r = client.post("/v1/cua/deterministas/consentimiento", json={"rfc": rfc})
    assert r.status_code == 201, r.text
    return r.json()


def despachar(client, capacidad, **extra):
    return client.post("/v1/cua/misiones", json={"capacidad": capacidad, **extra})


# --- Lo que hace falta antes de correr --------------------------------------------


def test_sin_efirma_dice_donde_cargarla(client, demo, corridas):
    r = despachar(client, "sat_opinion_32d")
    assert r.status_code == 400 and "SAT · Bóveda fiscal" in r.json()["detail"]
    assert corridas == []


def test_un_rfc_sin_efirma_no_corre(client, demo, fiel, corridas):
    subir_efirma(client, fiel)
    r = despachar(client, "sat_opinion_32d", rfc="XAXX010101000")
    assert r.status_code == 400
    assert corridas == []


def test_sin_permiso_del_dueno_se_niega(client, db_session, demo, fiel, corridas):
    subir_efirma(client, fiel)
    estado = client.get("/v1/cua/deterministas").json()
    assert estado["consentimiento_texto"] == CONSENTIMIENTO_SAT_TEXTO
    assert estado["empresas"][0]["consentimiento_en"] is None

    r = despachar(client, "sat_opinion_32d")
    assert r.status_code == 409 and "permiso" in r.json()["detail"]
    assert corridas == []
    assert db_session.scalars(select(CuaMission)).all() == []


def test_el_permiso_tambien_se_revisa_al_correr(client, db_session, demo, fiel):
    """Aunque un recado llegue a la cola por otro lado, sin permiso no entra al SAT."""
    from aiuda_core.cua.fallback import enqueue_cua_mission

    subir_efirma(client, fiel)
    recado = enqueue_cua_mission(db_session, demo, "sat_constancia", rfc=RFC)
    ejecutar_recado(db_session, recado)
    assert recado.status == "failed" and "permiso" in recado.error


def test_el_permiso_es_por_rfc_y_queda_con_fecha(client, db_session, demo, fiel):
    subir_efirma(client, fiel)
    assert client.post(
        "/v1/cua/deterministas/consentimiento", json={"rfc": "XAXX010101000"}
    ).status_code == 404
    dado = aceptar(client)
    assert dado["rfc"] == RFC and dado["aceptado_en"]
    guardado = demo.config["sat_rutinas_consentimiento"][RFC]
    assert guardado["texto"] == CONSENTIMIENTO_SAT_TEXTO
    assert datetime.fromisoformat(guardado["aceptado_en"]).tzinfo is not None
    assert client.get("/v1/cua/deterministas").json()["empresas"][0]["consentimiento_en"]
    # Aceptar otra vez no mueve la fecha: es una vez por RFC.
    assert aceptar(client)["aceptado_en"] == dado["aceptado_en"]


def test_borrar_la_efirma_olvida_el_permiso(client, db_session, demo, fiel):
    subir_efirma(client, fiel)
    aceptar(client)
    assert client.delete(f"/v1/sat/efirma/{RFC}").status_code == 200
    assert consentimiento_sat(demo, RFC) is None


# --- La corrida completa ----------------------------------------------------------


def test_baja_la_opinion_sin_ia_y_sirve_el_pdf(client, db_session, demo, fiel, corridas, sat):
    subir_efirma(client, fiel)
    aceptar(client)
    r = despachar(client, "sat_opinion_32d")  # una sola e.firma: no hace falta el RFC
    assert r.status_code == 201, r.text
    assert len(corridas) == 1

    detalle = client.get(f"/v1/cua/misiones/{r.json()['id']}")
    m = detalle.json()
    assert m["status"] == "done", m["error"]
    assert m["sistema"] == "SAT · Opinión de cumplimiento"
    assert m["data"]["_rfc"] == RFC and m["data"]["sentido"] == "Positivo"
    assert m["evidencia_capturas"] >= 3 and m["steps"]
    assert "Positivo" in m["resumen"]
    # La contraseña no sale por la API ni quedó en el recado.
    assert PASSWORD not in detalle.text
    assert all(PASSWORD not in ruta + cuerpo for _, ruta, cuerpo in sat.visto)

    docs = client.get("/v1/documentos").json()["documentos"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["rfc"] == RFC and doc["tipo"] == "opinion_32d"
    assert doc["sentido"] == "Positivo" and doc["folio"] and doc["fecha"]
    assert doc["mission_id"] == m["id"] and m["data"]["documento_id"] == doc["id"]
    assert "pdf" not in doc

    pdf = client.get(f"/v1/documentos/{doc['id']}.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content == pdf_opinion()

    rutina = client.get("/v1/cua/deterministas").json()["empresas"][0]["rutinas"][0]
    assert rutina["capacidad"] == "sat_opinion_32d" and rutina["en_curso"] is False
    assert rutina["ultimo_documento"]["id"] == doc["id"]
    assert rutina["ultima_corrida"]["status"] == "done"


def test_baja_la_constancia(client, db_session, demo, fiel, corridas, sat):
    subir_efirma(client, fiel)
    aceptar(client)
    r = despachar(client, "sat_constancia", rfc=RFC)
    assert r.status_code == 201, r.text
    doc = client.get("/v1/documentos", params={"tipo": "constancia"}).json()["documentos"][0]
    assert doc["sentido"] is None and doc["nombre"] == "Constancia de situación fiscal"
    assert client.get(f"/v1/documentos/{doc['id']}.pdf").content == pdf_constancia()
    assert client.get("/v1/documentos", params={"tipo": "opinion_32d"}).json() == {
        "documentos": []
    }


def test_si_el_sat_rechaza_la_efirma_no_guarda_nada(client, db_session, demo, fiel, corridas, sat):
    subir_efirma(client, fiel)
    aceptar(client)
    sat.modo["login"] = "revocada"
    r = despachar(client, "sat_opinion_32d")
    m = client.get(f"/v1/cua/misiones/{r.json()['id']}").json()
    assert m["status"] == "failed" and "revocada" in m["error"]
    assert m["evidencia_capturas"] >= 1
    assert client.get("/v1/documentos").json() == {"documentos": []}
    rutina = client.get("/v1/cua/deterministas").json()["empresas"][0]["rutinas"][0]
    assert rutina["ultimo_documento"] is None
    assert "revocada" in rutina["ultima_corrida"]["error"]


def test_efirma_vencida_no_llega_al_portal(client, db_session, demo, corridas, sat):
    """Guardarla vencida no se puede por la API; aquí venció después de guardarse."""
    import base64

    cer, key = efirma_prueba(password=PASSWORD, dias=-1, desde_dias=-30)
    cred.set_credential(
        db_session, demo.id, f"sat_efirma:{RFC}",
        {
            "cer": base64.b64encode(cer).decode(), "key": base64.b64encode(key).decode(),
            "password": PASSWORD, "rfc": RFC,
        },
    )
    aceptar(client)
    r = despachar(client, "sat_opinion_32d")
    m = client.get(f"/v1/cua/misiones/{r.json()['id']}").json()
    assert m["status"] == "failed" and "venció" in m["error"]
    assert sat.visto == []


def test_sin_navegador_lo_dice_en_vez_de_fallar(client, db_session, demo, fiel, corridas, monkeypatch):
    monkeypatch.setattr(
        "aiuda_core.cua.computer.estado_navegador", lambda: (False, "falta el extra")
    )
    subir_efirma(client, fiel)
    aceptar(client)
    estado = client.get("/v1/cua/deterministas").json()
    assert estado["navegador_listo"] is False
    assert estado["navegador_detalle"] == sat_documentos.MSG_SIN_NAVEGADOR
    r = despachar(client, "sat_constancia")
    m = client.get(f"/v1/cua/misiones/{r.json()['id']}").json()
    assert m["status"] == "failed" and m["error"] == sat_documentos.MSG_SIN_NAVEGADOR


def test_no_despacha_dos_veces_la_misma_rutina(client, db_session, demo, fiel, monkeypatch):
    monkeypatch.setattr("aiuda_server.api.cua.run_recado_blocking", lambda _id: None)
    subir_efirma(client, fiel)
    aceptar(client)
    primera = despachar(client, "sat_opinion_32d")
    assert primera.status_code == 201
    assert despachar(client, "sat_opinion_32d").status_code == 409
    # La otra rutina sí puede ir: es otro documento.
    assert despachar(client, "sat_constancia").status_code == 201
    # Una corrida colgada (aiuda se cerró a media corrida) no bloquea para siempre.
    recado = db_session.get(CuaMission, primera.json()["id"])
    recado.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.flush()
    assert despachar(client, "sat_opinion_32d").status_code == 201


def test_los_documentos_son_de_cada_negocio(client, db_session, demo):
    otro = Tenant(name="Otro", owner_phone="52156", evolution_instance="otro", config={})
    db_session.add(otro)
    db_session.flush()
    ajeno = Documento(
        tenant_id=otro.id, rfc="XAXX010101000", tipo="constancia",
        fecha=datetime.now(timezone.utc), pdf=pdf_constancia("XAXX010101000"),
    )
    db_session.add(ajeno)
    db_session.flush()
    assert client.get("/v1/documentos").json() == {"documentos": []}
    assert client.get(f"/v1/documentos/{ajeno.id}.pdf").status_code == 404
    assert client.get("/v1/documentos/no-existe.pdf").status_code == 404


def test_las_rutinas_sin_ia_no_se_mezclan_con_los_portales(client, demo):
    """No aparecen entre los portales del asistente ni se guardan como rutina con
    instrucción: no llevan instrucción ni login a mano."""
    caps = {c["capacidad"] for c in client.get("/v1/cua/capacidades").json()}
    assert not caps & {"sat_opinion_32d", "sat_constancia"}
    r = client.post(
        "/v1/cua/rutinas", json={"nombre": "x", "capacidad": "sat_opinion_32d"}
    )
    assert r.status_code == 400
