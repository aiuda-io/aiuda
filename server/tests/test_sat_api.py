"""API de la bóveda fiscal del SAT: importar XML/ZIP, empresas (hasta 3), estado.

La regla de seguridad se prueba aparte (test_sat_efirma_api.py): aquí va el
camino de datos — subir CFDIs, clasificarlos por empresa y no inflar cartera.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, CfdiBoveda, Invoice, Tenant
from aiuda_server.api.main import app, get_db

HANOVA = "HCO250213281"
PERSONA = "GOBM980902FL1"
TERCERA = "LHE250604HT6"
CLIENTE = "PIA210312BD3"

U1 = "BBBB0001-0000-4000-8000-000000000001"
U2 = "BBBB0002-0000-4000-8000-000000000002"
U3 = "BBBB0003-0000-4000-8000-000000000003"


def cfdi_xml(uuid, tipo="I", metodo="PPD", emisor=HANOVA, receptor=CLIENTE,
             total="1160.00", folio="1"):
    metodo_attr = f'MetodoPago="{metodo}"' if metodo else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="F" Folio="{folio}" Fecha="2026-06-10T11:30:13"
  TipoDeComprobante="{tipo}" {metodo_attr} Moneda="MXN" Total="{total}">
  <cfdi:Emisor Rfc="{emisor}" Nombre="Emisor" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{receptor}" Nombre="Receptor" UsoCFDI="G03"/>
  <cfdi:Conceptos><cfdi:Concepto Descripcion="Servicio"/></cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="{uuid}" FechaTimbrado="2026-06-10T11:30:14"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
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
        name="Demo", owner_phone="52155", evolution_instance="demo-sat",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño"}]},
    )
    db_session.add(t)
    db_session.flush()
    demo_login(client)
    return t


def _subir(client, contenido: bytes, nombre="cfdi.xml", rfc=""):
    return client.post(
        "/v1/sat/importar",
        files={"archivo": (nombre, contenido, "application/xml")},
        data={"rfc": rfc} if rfc else {},
    )


def test_importar_xml_crea_boveda_y_cartera(client, db_session, demo):
    r = _subir(client, cfdi_xml(U1).encode(), rfc=HANOVA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nuevos"] == 1 and body["facturas_creadas"] == 1
    inv = db_session.scalar(select(Invoice))
    assert inv.source == "sat" and inv.cfdi_xml


def test_importar_zip_como_lo_entrega_el_sat(client, db_session, demo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.xml", cfdi_xml(U1, folio="1"))
        zf.writestr("b.xml", cfdi_xml(U2, folio="2"))
        zf.writestr("basura.txt", "esto no es un cfdi")
    r = _subir(client, buf.getvalue(), nombre="paquete.zip", rfc=HANOVA)
    assert r.status_code == 200
    assert r.json()["nuevos"] == 2
    assert len(db_session.scalars(select(CfdiBoveda)).all()) == 2


def test_reimportar_no_duplica(client, db_session, demo):
    _subir(client, cfdi_xml(U1).encode(), rfc=HANOVA)
    r = _subir(client, cfdi_xml(U1).encode())
    assert r.json()["duplicados"] == 1
    assert len(db_session.scalars(select(Invoice)).all()) == 1


def test_archivo_sin_xml_da_422(client, demo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nada.txt", "vacío")
    r = _subir(client, buf.getvalue(), nombre="vacio.zip")
    assert r.status_code == 422


def test_empresas_tope_de_tres_con_mensaje_claro(client, demo):
    for rfc in (HANOVA, PERSONA, TERCERA):
        r = client.post("/v1/sat/empresas", json={"rfc": rfc})
        assert r.status_code == 201, r.text
    r = client.post("/v1/sat/empresas", json={"rfc": "XAXX010101000"})
    assert r.status_code == 409
    assert "tope" in r.json()["detail"]


def test_empresa_rfc_invalido_da_422(client, demo):
    r = client.post("/v1/sat/empresas", json={"rfc": "NOESUNRFC"})
    assert r.status_code == 422


def test_quitar_empresa_manual(client, demo):
    client.post("/v1/sat/empresas", json={"rfc": HANOVA, "nombre": "Hanova"})
    r = client.delete(f"/v1/sat/empresas/{HANOVA}")
    assert r.status_code == 200
    assert r.json()["empresas"] == []


def test_plazo_estimado_es_configurable_por_empresa(client, db_session, demo):
    client.post(
        "/v1/sat/empresas",
        json={"rfc": HANOVA, "nombre": "Hanova", "plazo_dias": 45},
    )
    estado = client.get("/v1/sat/estado").json()
    assert estado["empresas"][0]["plazo_dias"] == 45

    r = _subir(client, cfdi_xml(U1).encode())
    assert r.status_code == 200
    inv = db_session.scalar(select(Invoice))
    assert inv.due_date.isoformat() == "2026-07-25"
    assert inv.meta["vencimiento_estimado"] == "45 días (el CFDI no trae plazo)"

    cambio = client.patch(
        f"/v1/sat/empresas/{HANOVA}",
        json={"nombre": "Hanova", "plazo_dias": 60},
    )
    assert cambio.status_code == 200
    assert cambio.json()["empresas"][0]["plazo_dias"] == 60


def test_estado_trae_empresas_boveda_y_cartera_por_empresa(client, demo):
    _subir(client, cfdi_xml(U1, emisor=HANOVA, folio="1").encode(), rfc=HANOVA)
    client.post("/v1/sat/empresas", json={"rfc": PERSONA})
    _subir(client, cfdi_xml(U2, emisor=PERSONA, folio="2", total="500.00").encode())
    r = client.get("/v1/sat/estado")
    assert r.status_code == 200
    body = r.json()
    assert body["maximo"] == 3
    assert [e["rfc"] for e in body["empresas"]] == [HANOVA, PERSONA]
    assert body["boveda"]["total"] == 2 and body["boveda"]["emitidas"] == 2
    por = {e["rfc"]: e for e in body["cartera"]["por_empresa"]}
    assert por[HANOVA]["total"] == 1160.0
    assert por[PERSONA]["total"] == 500.0
    assert body["cartera"]["todo_junto"]["total"] == 1660.0


def test_intercompania_fuera_de_los_totales(client, db_session, demo):
    """Tres empresas; una le factura a otra. La bóveda lo guarda UNA vez y los
    totales de cartera no lo cuentan: es dinero de la misma casa."""
    for rfc in (HANOVA, PERSONA, TERCERA):
        client.post("/v1/sat/empresas", json={"rfc": rfc})
    entre = cfdi_xml(U1, emisor=HANOVA, receptor=PERSONA)
    _subir(client, entre.encode())
    _subir(client, entre.encode())  # baja dos veces: emitida y recibida
    r = client.get("/v1/sat/estado")
    body = r.json()
    assert body["boveda"]["intercompania"] == 1
    assert body["cartera"]["todo_junto"]["total"] == 0
    assert db_session.scalar(select(Invoice)) is None


def test_boveda_filtra_por_empresa(client, demo):
    _subir(client, cfdi_xml(U1, emisor=HANOVA, folio="1").encode(), rfc=HANOVA)
    client.post("/v1/sat/empresas", json={"rfc": PERSONA})
    _subir(client, cfdi_xml(U2, emisor=PERSONA, folio="2").encode())
    todo = client.get("/v1/sat/boveda").json()
    assert todo["count"] == 2
    solo = client.get(f"/v1/sat/boveda?rfc={PERSONA}").json()
    assert solo["count"] == 1
    assert solo["cfdis"][0]["rfc_emisor"] == PERSONA
    # el listado jamás trae el XML completo
    assert "xml" not in solo["cfdis"][0]
