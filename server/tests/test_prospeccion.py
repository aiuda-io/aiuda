"""Prospección DENUE: estado honesto de la fuente, búsqueda en vivo (fingida con
el contrato) y carga a la cartera con procedencia denue SIN duplicar."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.connectors.denue import Negocio
from aiuda_core.models import Base, Customer, Tenant
from aiuda_server.api import prospeccion
from aiuda_server.api.main import app, get_db

@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    # Sin token global: el estado de la fuente sale del tenant, no del self-host.
    monkeypatch.setattr(settings, "denue_token", "")


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


def _tenant(db_session, con_token: bool = True) -> Tenant:
    config = {
        "demo": True,
        "members": [{"name": "D", "email": "d@a.mx", "role": "dueño", "status": "activo"}],
    }
    if con_token:
        config["integrations"] = {"denue": {"token": "tok-inegi"}}
    t = Tenant(name="Demo", owner_phone="5215512345678", evolution_instance="demo", config=config)
    db_session.add(t)
    db_session.flush()
    return t


NEGOCIOS = [
    Negocio(
        id="2825563",
        nombre="FERRETERIA LA CENTRAL",
        razon_social="FERRETERA LA CENTRAL SA DE CV",
        actividad="Comercio al por menor en ferreterías y tlapalerías",
        telefono="5555550110",
        correo="CONTACTO@FERRECENTRAL.MX",
        direccion="AV JUAREZ 10, CENTRO, 06000",
    ),
    Negocio(
        id="2825590",
        nombre="TLAPALERIA EL TORNILLO",
        razon_social="",
        actividad="Comercio al por menor en ferreterías y tlapalerías",
        telefono="",
        correo="",
        direccion="REGINA 44, CENTRO, 06090",
    ),
]


def _como_body(n: Negocio) -> dict:
    return {
        "id": n.id,
        "nombre": n.nombre,
        "razon_social": n.razon_social,
        "actividad": n.actividad,
        "telefono": n.telefono,
        "correo": n.correo,
        "direccion": n.direccion,
    }


BUSQUEDA = {"condicion": "ferreteria", "lat": 19.4326, "lng": -99.1332, "radio_m": 1000}


# ---------- estado de la fuente ----------


def test_fuente_sin_token_es_honesta(client, db_session, demo_login):
    _tenant(db_session, con_token=False)
    demo_login(client)
    body = client.get("/v1/prospeccion/fuente").json()
    assert body["conectada"] is False and body["fuente"] == "denue"


def test_fuente_con_token_conectada(client, db_session, demo_login):
    _tenant(db_session)
    demo_login(client)
    assert client.get("/v1/prospeccion/fuente").json()["conectada"] is True


# ---------- buscar ----------


def test_buscar_sin_token_409(client, db_session, demo_login):
    _tenant(db_session, con_token=False)
    demo_login(client)
    res = client.post("/v1/prospeccion/buscar", json=BUSQUEDA)
    assert res.status_code == 409
    assert "no está conectado" in res.json()["detail"]


def test_buscar_devuelve_resultados_y_marca_los_ya_registrados(
    client, db_session, monkeypatch, demo_login
):
    t = _tenant(db_session)
    # Cliente existente con el MISMO teléfono en otro formato (52 + 10 dígitos).
    db_session.add(
        Customer(tenant_id=t.id, name="Ferretera Central", phone="525555550110", kind="cliente")
    )
    db_session.flush()
    capturado = {}

    def fake_buscar(creds, condicion, lat, lng, radio_m):
        capturado.update(creds=creds, condicion=condicion, radio_m=radio_m)
        return NEGOCIOS

    monkeypatch.setattr(prospeccion, "_buscar_denue", fake_buscar)
    demo_login(client)
    body = client.post("/v1/prospeccion/buscar", json=BUSQUEDA).json()

    assert capturado["creds"]["token"] == "tok-inegi"
    assert capturado["condicion"] == "ferreteria" and capturado["radio_m"] == 1000
    assert body["total"] == 2
    central, tornillo = body["resultados"]
    assert central["ya_registrado"] is True and central["cliente_id"]  # mismo teléfono
    assert tornillo["ya_registrado"] is False and tornillo["cliente_id"] is None
    assert central["contactable"] is True and tornillo["contactable"] is False


def test_buscar_radio_se_acota_al_maximo_de_inegi(client, db_session, monkeypatch, demo_login):
    _tenant(db_session)
    visto = {}

    def fake_buscar(creds, condicion, lat, lng, radio_m):
        visto["radio_m"] = radio_m
        return []

    monkeypatch.setattr(prospeccion, "_buscar_denue", fake_buscar)
    demo_login(client)
    body = client.post(
        "/v1/prospeccion/buscar", json={**BUSQUEDA, "radio_m": 99999}
    ).json()
    assert visto["radio_m"] == 5000
    assert body["total"] == 0 and body["resultados"] == []


def test_buscar_condicion_vacia_422(client, db_session, demo_login):
    _tenant(db_session)
    demo_login(client)
    res = client.post("/v1/prospeccion/buscar", json={**BUSQUEDA, "condicion": "  "})
    assert res.status_code == 422


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://www.inegi.org.mx/x")
    return httpx.HTTPStatusError(
        "err", request=req, response=httpx.Response(code, request=req)
    )


def test_buscar_404_de_inegi_es_sin_resultados(client, db_session, monkeypatch, demo_login):
    _tenant(db_session)

    def fake_buscar(*a, **kw):
        raise _http_status_error(404)

    monkeypatch.setattr(prospeccion, "_buscar_denue", fake_buscar)
    demo_login(client)
    res = client.post("/v1/prospeccion/buscar", json=BUSQUEDA)
    assert res.status_code == 200
    assert res.json() == {"total": 0, "resultados": []}


def test_buscar_error_de_inegi_es_502_legible(client, db_session, monkeypatch, demo_login):
    _tenant(db_session)

    def fake_buscar(*a, **kw):
        raise _http_status_error(500)

    monkeypatch.setattr(prospeccion, "_buscar_denue", fake_buscar)
    demo_login(client)
    res = client.post("/v1/prospeccion/buscar", json=BUSQUEDA)
    assert res.status_code == 502
    assert "INEGI respondió 500" in res.json()["detail"]


def test_buscar_token_invalido_es_502_con_pista(client, db_session, monkeypatch, demo_login):
    """El contrato verificado en vivo: token inválido → 'HTTP/1.1 000' →
    RemoteProtocolError. El dueño recibe la pista del token, no un stacktrace."""
    _tenant(db_session)

    def fake_buscar(*a, **kw):
        raise httpx.RemoteProtocolError(
            "InformationalResponse status_code should be in range [100, 200), not 0"
        )

    monkeypatch.setattr(prospeccion, "_buscar_denue", fake_buscar)
    demo_login(client)
    res = client.post("/v1/prospeccion/buscar", json=BUSQUEDA)
    assert res.status_code == 502
    assert "token" in res.json()["detail"]


# ---------- importar ----------


def test_importar_crea_prospectos_con_procedencia_denue(client, db_session, demo_login):
    t = _tenant(db_session)
    demo_login(client)
    res = client.post(
        "/v1/prospeccion/importar", json={"negocios": [_como_body(n) for n in NEGOCIOS]}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["importados"] == 2 and body["ya_existian"] == 0 and body["omitidos"] == 0
    assert all(d["creado"] and d["cliente_id"] for d in body["detalle"])

    filas = db_session.scalars(select(Customer).where(Customer.tenant_id == t.id)).all()
    assert len(filas) == 2
    central = next(c for c in filas if c.name == "FERRETERIA LA CENTRAL")
    assert central.kind == "prospecto"
    assert central.phone == "5555550110" and central.email == "CONTACTO@FERRECENTRAL.MX"
    assert central.presence["denue"]["ref"] == "2825563"
    assert central.meta["origen"] == "denue"
    assert central.meta["actividad"].startswith("Comercio al por menor")
    assert "CENTRO" in central.meta["direccion"]


def test_importar_dos_veces_no_duplica(client, db_session, demo_login):
    t = _tenant(db_session)
    demo_login(client)
    negocios = {"negocios": [_como_body(n) for n in NEGOCIOS]}
    client.post("/v1/prospeccion/importar", json=negocios)
    body = client.post("/v1/prospeccion/importar", json=negocios).json()
    assert body["importados"] == 0 and body["ya_existian"] == 2
    filas = db_session.scalars(select(Customer).where(Customer.tenant_id == t.id)).all()
    assert len(filas) == 2


def test_importar_no_duplica_cliente_existente_por_telefono(client, db_session, demo_login):
    """El cliente capturado como '52 + 10 dígitos' y el DENUE con 10 dígitos son
    el MISMO teléfono (match_key): no se crea otro registro, no se degrada el
    kind, y el cliente gana la presencia denue + el correo que le faltaba."""
    t = _tenant(db_session)
    db_session.add(
        Customer(tenant_id=t.id, name="Ferretera Central", phone="525555550110", kind="cliente")
    )
    db_session.flush()
    demo_login(client)
    body = client.post(
        "/v1/prospeccion/importar", json={"negocios": [_como_body(NEGOCIOS[0])]}
    ).json()
    assert body["importados"] == 0 and body["ya_existian"] == 1
    filas = db_session.scalars(select(Customer).where(Customer.tenant_id == t.id)).all()
    assert len(filas) == 1
    existente = filas[0]
    assert existente.kind == "cliente"  # no se degrada
    assert existente.name == "Ferretera Central"  # no se pisa lo del dueño
    assert existente.phone == "525555550110"  # el teléfono capturado se respeta
    assert existente.email == "CONTACTO@FERRECENTRAL.MX"  # se completa lo faltante
    assert existente.presence["denue"]["ref"] == "2825563"


def test_importar_dedupe_por_nombre_sin_acentos(client, db_session, demo_login):
    """'Tlapalería El Tornillo' (del dueño, con acentos) y 'TLAPALERIA EL
    TORNILLO' (DENUE, mayúsculas sin acentos) son el mismo negocio."""
    t = _tenant(db_session)
    db_session.add(Customer(tenant_id=t.id, name="Tlapalería El Tornillo", kind="prospecto"))
    db_session.flush()
    demo_login(client)
    body = client.post(
        "/v1/prospeccion/importar", json={"negocios": [_como_body(NEGOCIOS[1])]}
    ).json()
    assert body["importados"] == 0 and body["ya_existian"] == 1
    assert len(db_session.scalars(select(Customer).where(Customer.tenant_id == t.id)).all()) == 1


def test_importar_misma_seleccion_duplicada_entra_una_vez(client, db_session, demo_login):
    t = _tenant(db_session)
    demo_login(client)
    body = client.post(
        "/v1/prospeccion/importar",
        json={"negocios": [_como_body(NEGOCIOS[0]), _como_body(NEGOCIOS[0])]},
    ).json()
    assert body["importados"] == 1 and body["ya_existian"] == 1
    assert len(db_session.scalars(select(Customer).where(Customer.tenant_id == t.id)).all()) == 1


def test_importar_omite_sin_nombre_y_vacio_es_422(client, db_session, demo_login):
    _tenant(db_session)
    demo_login(client)
    assert client.post("/v1/prospeccion/importar", json={"negocios": []}).status_code == 422
    body = client.post(
        "/v1/prospeccion/importar",
        json={"negocios": [{"id": "X1", "nombre": "  ", "telefono": "5511122233"}]},
    ).json()
    assert body["omitidos"] == 1 and body["importados"] == 0


# ---------- probar conexión (Integraciones → DENUE) ----------


def test_probar_conexion_denue_reporta_legible(monkeypatch):
    """El tester de Integraciones hace UNA búsqueda real mínima; sin red aquí:
    se finge el cliente. Token que responde → ok con conteo; token que INEGI
    rechaza ('HTTP/1.1 000' → RemoteProtocolError) → falla legible, sin traza."""
    import aiuda_core.connectors.denue as denue_mod
    from aiuda_server.api import integrations as integ

    class FakeOK:
        def __init__(self, token=None):
            assert token == "tok-inegi"

        def buscar(self, condicion, lat, lng, radio_m=5000):
            assert condicion == "todos" and radio_m == 500
            return NEGOCIOS

    monkeypatch.setattr(denue_mod, "DenueClient", FakeOK)
    out = integ._test_denue({"token": "tok-inegi"})
    assert out["ok"] is True and out["details"]["Negocios en la muestra"] == 2

    class FakeRechazo:
        def __init__(self, token=None):
            pass

        def buscar(self, *a, **kw):
            raise httpx.RemoteProtocolError("status_code should be in range [100, 200), not 0")

    monkeypatch.setattr(denue_mod, "DenueClient", FakeRechazo)
    out = integ._test_denue({"token": "malo"})
    assert out["ok"] is False and "No se pudo conectar" in out["message"]

    assert integ._test_denue({})["ok"] is False  # sin token: honesto, sin red
