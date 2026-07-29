"""Conexiones a la medida: probar en vivo, guardar (secreto cifrado), listar, editar,
re-probar, exportar/importar receta y borrar."""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.connectors import custom_api
from aiuda_core.models import Base, Tenant
from aiuda_server.api.main import app, get_db

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
def demo_tenant(db_session):
    t = Tenant(
        name="Demo",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={"demo": True, "members": [{"name": "D", "email": "d@a.mx", "role": "dueño", "status": "activo"}]},
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_probar_devuelve_muestra(client, demo_tenant, monkeypatch, demo_login):
    monkeypatch.setattr(
        custom_api, "fetch_rows", lambda **kw: ([{"name": "ACME", "phone": "5512345678"}], None)
    )
    demo_login(client)
    res = client.post(
        "/v1/custom-connectors/test",
        json={"base_url": "https://mi.api.com", "root": "data", "mapping": {"name": "n"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["count"] == 1
    assert body["sample"][0]["name"] == "ACME"


def test_probar_reporta_error_legible(client, demo_tenant, monkeypatch, demo_login):
    monkeypatch.setattr(custom_api, "fetch_rows", lambda **kw: ([], "No se pudo conectar: timeout"))
    demo_login(client)
    body = client.post("/v1/custom-connectors/test", json={"base_url": "https://x.com"}).json()
    assert body["ok"] is False and "conectar" in body["error"]


def test_crear_listar_borrar_con_secreto_cifrado(client, demo_tenant, db_session, demo_login):
    demo_login(client)
    # Crear: el auth_value se cifra y NUNCA se devuelve ni se guarda en claro.
    res = client.post(
        "/v1/custom-connectors",
        json={
            "name": "Mi ERP",
            "cap": "directorio_clientes",
            "base_url": "https://mi.api.com",
            "list_path": "clientes",
            "auth_header": "X-API-Key",
            "auth_value": "super-secreto-123",
            "mapping": {"name": "nombre"},
        },
    )
    assert res.status_code == 200
    creada = res.json()
    cid = creada["id"]
    assert "secret_ct" not in creada and "auth_value" not in creada
    # En la BD el secreto está cifrado (no aparece el texto plano).
    db_session.refresh(demo_tenant)
    guardado = demo_tenant.config["custom_sources"][0]
    assert "super-secreto-123" not in str(guardado)
    assert guardado["secret_ct"] and guardado["secret_ver"] >= 1

    # Listar: sale sin secreto.
    lista = client.get("/v1/custom-connectors").json()
    assert len(lista) == 1 and lista[0]["name"] == "Mi ERP" and "secret_ct" not in lista[0]

    # Borrar.
    assert client.delete(f"/v1/custom-connectors/{cid}").status_code == 200
    assert client.get("/v1/custom-connectors").json() == []


def test_borrar_inexistente_404(client, demo_tenant, demo_login):
    demo_login(client)
    assert client.delete("/v1/custom-connectors/nope").status_code == 404


def _crear(client, **extra):
    base = {
        "name": "Mi ERP",
        "cap": "directorio_clientes",
        "base_url": "https://mi.api.com",
        "list_path": "clientes",
        "auth_type": "header",
        "auth_header": "X-API-Key",
        "auth_value": "clave-original",
        "mapping": {"name": "nombre"},
    }
    base.update(extra)
    res = client.post("/v1/custom-connectors", json=base)
    assert res.status_code == 200
    return res.json()


def test_crear_guarda_paginacion_y_auth_avanzado(client, demo_tenant, db_session, demo_login):
    demo_login(client)
    creada = _crear(
        client,
        auth_type="oauth2_cc",
        auth_header="",
        token_url="https://mi.api.com/oauth/token",
        client_id="mi-app",
        paging="cursor",
        cursor_path="meta.next",
        cursor_param="after",
        timeout=30,
        retries=1,
        pause_ms=200,
    )
    assert creada["auth_type"] == "oauth2_cc" and creada["token_url"] == "https://mi.api.com/oauth/token"
    assert creada["paging"] == "cursor" and creada["cursor_path"] == "meta.next"
    assert creada["timeout"] == 30 and creada["retries"] == 1 and creada["pause_ms"] == 200
    assert creada["has_secret"] is True and "secret_ct" not in creada


def test_editar_conserva_el_secreto_si_no_mandas_clave(client, demo_tenant, db_session, demo_login):
    from aiuda_core.security import crypto

    demo_login(client)
    creada = _crear(client)
    cid = creada["id"]

    res = client.put(
        f"/v1/custom-connectors/{cid}",
        json={
            "name": "Mi ERP v2",
            "cap": "directorio_clientes",
            "base_url": "https://otra.api.com",
            "auth_type": "header",
            "auth_header": "X-API-Key",
            "auth_value": "",  # vacío = conserva la clave guardada
            "mapping": {"name": "razon_social"},
        },
    )
    assert res.status_code == 200
    editada = res.json()
    assert editada["name"] == "Mi ERP v2" and editada["base_url"] == "https://otra.api.com"
    assert editada["has_secret"] is True

    db_session.refresh(demo_tenant)
    guardado = demo_tenant.config["custom_sources"][0]
    plano = crypto.decrypt(base64.b64decode(guardado["secret_ct"]), guardado["secret_ver"])
    assert plano == "clave-original"  # sigue la de antes

    # Con clave nueva sí se reemplaza (re-cifrada).
    res = client.put(
        f"/v1/custom-connectors/{cid}",
        json={
            "name": "Mi ERP v2",
            "cap": "directorio_clientes",
            "base_url": "https://otra.api.com",
            "auth_value": "clave-nueva",
            "mapping": {},
        },
    )
    assert res.status_code == 200
    db_session.refresh(demo_tenant)
    guardado = demo_tenant.config["custom_sources"][0]
    assert crypto.decrypt(base64.b64decode(guardado["secret_ct"]), guardado["secret_ver"]) == "clave-nueva"


def test_editar_inexistente_404(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put(
        "/v1/custom-connectors/nope",
        json={"name": "X", "cap": "agenda", "base_url": "https://x.com", "mapping": {}},
    )
    assert res.status_code == 404


def test_reprobar_usa_la_clave_guardada(client, demo_tenant, db_session, monkeypatch, demo_login):
    demo_login(client)
    creada = _crear(client)
    capturado = {}

    def fake_fetch(**kw):
        capturado.update(kw)
        return [{"name": "ACME"}], None

    monkeypatch.setattr(custom_api, "fetch_rows", fake_fetch)
    res = client.post(f"/v1/custom-connectors/{creada['id']}/test")
    assert res.status_code == 200 and res.json()["ok"] is True
    # La clave viajó DESCIFRADA al lector, sin que el front la tocara.
    assert capturado["auth_value"] == "clave-original"
    assert capturado["base_url"] == "https://mi.api.com" and capturado["limit"] == 5

    # El resultado queda registrado en la conexión (semáforo honesto en la lista).
    lista = client.get("/v1/custom-connectors").json()
    assert lista[0]["last_test_ok"] is True and lista[0]["last_test_at"]


def test_reprobar_con_body_prueba_lo_editado_sin_perder_clave(client, demo_tenant, monkeypatch, demo_login):
    demo_login(client)
    creada = _crear(client)
    capturado = {}
    monkeypatch.setattr(
        custom_api, "fetch_rows", lambda **kw: (capturado.update(kw), ([], "El servidor respondió 404 (err)."))[1]
    )
    res = client.post(
        f"/v1/custom-connectors/{creada['id']}/test",
        json={
            "base_url": "https://mi.api.com",
            "list_path": "clientes-v2",
            "auth_type": "header",
            "auth_header": "X-API-Key",
            "auth_value": "",
            "mapping": {"name": "nombre"},
        },
    )
    body = res.json()
    assert body["ok"] is False and "404" in body["error"]
    assert capturado["list_path"] == "clientes-v2"  # probó lo del formulario
    assert capturado["auth_value"] == "clave-original"  # con la clave guardada
    lista = client.get("/v1/custom-connectors").json()
    assert lista[0]["last_test_ok"] is False and "404" in lista[0]["last_test_error"]


def test_receta_exporta_sin_secretos(client, demo_tenant, demo_login):
    demo_login(client)
    creada = _crear(client, auth_type="oauth2_cc", token_url="https://mi.api.com/token", client_id="mi-app")
    receta = client.get(f"/v1/custom-connectors/{creada['id']}/receta").json()
    assert receta["receta"] == 1 and receta["name"] == "Mi ERP"
    assert receta["base_url"] == "https://mi.api.com" and receta["token_url"] == "https://mi.api.com/token"
    # Sin identidad ni secretos: compartible tal cual.
    for prohibida in ("id", "client_id", "secret_ct", "secret_ver", "auth_value", "last_test_at"):
        assert prohibida not in receta


def test_importar_receta_crea_sin_clave(client, demo_tenant, demo_login):
    demo_login(client)
    creada = _crear(client)
    receta = client.get(f"/v1/custom-connectors/{creada['id']}/receta").json()
    # Alguien de la comunidad importa la receta; si trae claves coladas, se ignoran.
    receta["auth_value"] = "clave-colada"
    receta["secret_ct"] = "hack"
    res = client.post("/v1/custom-connectors/importar", json={"receta": receta})
    assert res.status_code == 200
    importada = res.json()
    assert importada["name"] == "Mi ERP" and importada["id"] != creada["id"]
    assert importada["has_secret"] is False  # la clave la captura el usuario, no la receta
    assert len(client.get("/v1/custom-connectors").json()) == 2


def test_importar_receta_invalida_422(client, demo_tenant, demo_login):
    demo_login(client)
    sin_url = {"receta": {"name": "X", "cap": "agenda", "base_url": "ftp://x"}}
    assert client.post("/v1/custom-connectors/importar", json=sin_url).status_code == 422
    mal_tipada = {
        "receta": {"name": "X", "cap": "agenda", "base_url": "https://x.com", "timeout": "mucho"}
    }
    assert client.post("/v1/custom-connectors/importar", json=mal_tipada).status_code == 422


def test_fields_incluye_telefono_en_cartera(client, demo_tenant):
    """El builder guía el mapeo: una factura por cobrar puede traer el teléfono del
    cliente (sin él no hay a quién recordarle por WhatsApp)."""
    campos = client.get("/v1/custom-connectors/fields").json()
    assert "phone" in campos["cap_fields"]["cuentas_por_cobrar"]
