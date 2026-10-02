"""Grafo de integraciones y acceso demo público."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import date

from aiuda_core.models import Base, Customer, Invoice, Tenant
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
        name="Taquería Demo",
        owner_phone="5215512345678",
        evolution_instance="demo",
        config={
            "demo": True,
            # El canal conectado de verdad (QR escaneado), no el identificador
            # que el workspace genera solo: eso decía "conectado" sin serlo.
            "integrations": {"whatsapp": {"via": "wacli", "instance": "demo"}},
            "members": [
                {"name": "Demo", "email": "demo@aiuda.mx", "role": "dueño", "status": "activo"}
            ],
        },
    )
    db_session.add(t)
    db_session.flush()
    c = Customer(tenant_id=t.id, name="Cliente", phone="5215599998888")
    db_session.add(c)
    db_session.flush()
    db_session.add(
        Invoice(
            tenant_id=t.id,
            customer_id=c.id,
            folio="F-1",
            amount=100,
            currency="MXN",
            issued_date=date(2026, 6, 1),
            due_date=date(2026, 6, 10),
            source="shopify",
            presence={"shopify": {"ref": "F-1"}},
        )
    )
    db_session.flush()
    return t


def test_workspace_activo(client, demo_tenant, demo_login):
    demo_login(client)
    # /v1/workspace confirma qué negocio resuelve el API local.
    me = client.get("/v1/workspace").json()
    assert me["business_name"] == "Taquería Demo"
    assert me["role"] == "dueño"


def test_integrations_marca_conectados(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.get("/v1/integrations")
    assert res.status_code == 200
    body = res.json()
    by_key = {s["key"]: s for s in body["systems"]}
    # whatsapp conectado porque el dueño configuró el canal; shopify por la factura
    assert by_key["whatsapp"]["connected"] is True
    assert by_key["shopify"]["connected"] is True
    assert by_key["shopify"]["records"] >= 1
    assert by_key["sat"]["connected"] is False
    # algo no tocado queda disponible
    assert by_key["stripe"]["connected"] is False
    assert body["connected_count"] >= 2
    # El mapa muestra el equipo del DUEÑO. Sin ayudantes creados va vacío, y ningún
    # sistema le atribuye uso a nadie: antes inventaba ocho roles de fábrica.
    assert body["agents"] == []
    assert by_key["whatsapp"]["agents"] == []


def test_integrations_responde_local(client, demo_tenant):
    assert client.get("/v1/integrations").status_code == 200


def test_sat_aparece_en_catalogo_y_conecta_con_empresa(
    client, demo_tenant, demo_login
):
    demo_login(client)
    client.post("/v1/sat/empresas", json={"rfc": "AAA010101AAA"})
    graph = client.get("/v1/integrations").json()
    sat = next(s for s in graph["systems"] if s["key"] == "sat")
    assert sat["connected"] is True
    assert {p["cap"] for p in sat["provides"]} == {
        "cfdi",
        "cuentas_por_cobrar",
    }


def test_object_source_deeplink_a_odoo(client, demo_tenant, db_session, demo_login):
    # Con Odoo conectado, "Agregar cliente/producto" apunta a crear el registro EN Odoo
    # (aiuda no es el maestro; se crea en la fuente y baja como espejo).
    demo_tenant.config = {
        **demo_tenant.config,
        "odoo": {"url": "https://mi.odoo.com", "db": "d", "username": "u", "api_key": "k"},
    }
    db_session.add(demo_tenant)
    db_session.flush()
    demo_login(client)
    body = client.get("/v1/objects/clientes/source").json()
    assert body["source"] == "odoo" and body["native"] is False
    assert body["new_url"] == "https://mi.odoo.com/odoo/res.partner/new"
    assert client.get("/v1/objects/productos/source").json()["new_url"].endswith(
        "/odoo/product.template/new"
    )


def test_object_source_tipo_desconocido(client, demo_tenant, demo_login):
    demo_login(client)
    assert client.get("/v1/objects/patos/source").status_code == 404


def test_guardar_y_desconectar_config(client, demo_tenant, demo_login):
    demo_login(client)
    # Guardar credenciales
    res = client.put("/v1/integrations/hubspot/config", json={"values": {"token": "secret_xyz"}})
    assert res.status_code == 200 and res.json()["connected"] is True
    # Leer: el secreto va enmascarado
    cfg = client.get("/v1/integrations/hubspot/config").json()
    assert cfg["configured"] is True and cfg["values"]["token"] == "••••••"
    # El grafo ahora lo marca conectado
    graph = client.get("/v1/integrations").json()
    hubspot = next(s for s in graph["systems"] if s["key"] == "hubspot")
    assert hubspot["connected"] is True and hubspot["configured"] is True
    # Desconectar
    assert client.delete("/v1/integrations/hubspot/config").json()["connected"] is False
    graph2 = client.get("/v1/integrations").json()
    assert next(s for s in graph2["systems"] if s["key"] == "hubspot")["connected"] is False


def test_config_integracion_desconocida(client, demo_tenant, demo_login):
    demo_login(client)
    assert client.put("/v1/integrations/inventada/config", json={"values": {}}).status_code == 404


# --- Capa de capacidades ----------------------------------------------------


def test_las_capacidades_salen_de_las_aiuditas_del_ayudante(db_session, demo_tenant):
    """La relación ayudante<->fuente sale de cruzar lo que sus aiuditas necesitan con lo
    que cada fuente provee. Ya no hay tabla de roles de fábrica que mantener a mano."""
    from aiuda_core.models import Ayudante
    from aiuda_server.api.integrations import _CAP_PROVIDERS, capacidades_de

    a = Ayudante(
        tenant_id=demo_tenant.id, name="Male", appearance={},
        aiuditas={"cobranza.consultar_cartera": {}, "cobranza.redactar_recordatorio": {}},
    )
    caps = capacidades_de(a)
    assert "cuentas_por_cobrar" in caps
    # Y de ahí salen las fuentes que le sirven, sin listarlas a mano.
    fuentes = {f for c in caps for f in _CAP_PROVIDERS.get(c, [])}
    assert {"odoo", "excel"} <= fuentes

    # Un ayudante sin aiuditas no necesita nada: no se le inventa un oficio.
    vacio = Ayudante(tenant_id=demo_tenant.id, name="Nuevo", appearance={}, aiuditas={})
    assert capacidades_de(vacio) == []

def test_integrations_devuelve_capacidades_y_huecos(client, demo_tenant, demo_login):
    demo_login(client)
    body = client.get("/v1/integrations").json()

    # El catálogo de capacidades viene con su estado (live derivado de la lectura cableada).
    caps = {c["key"]: c for c in body["capabilities"]}
    assert caps["cuentas_por_cobrar"]["live"] is True
    assert caps["cfdi"]["live"] is True  # facturama/facturapi ya leen CFDI (sync_cfdi)
    assert caps["avisos_equipo"]["live"] is True  # el worker ya avisa por Slack (aviso_al_equipo)
    # cartera está cubierta (shopify conectado); confirmación de pago no.
    assert caps["cuentas_por_cobrar"]["connected"] is True
    assert caps["confirmacion_pago"]["connected"] is False

    # Cada fuente declara qué provee; el live coincide con lo que el motor lee de verdad.
    by_key = {s["key"]: s for s in body["systems"]}
    odoo_caps = {p["cap"]: p["live"] for p in by_key["odoo"]["provides"]}
    assert odoo_caps["cuentas_por_cobrar"] is True
    assert odoo_caps["catalogo_productos"] is True  # sync_catalogo ya lee de Odoo

    # El equipo del mapa son los ayudantes que el dueño creó. Sin ninguno, va vacío:
    # no se inventa un equipo de fábrica para llenar la pantalla.
    assert body["agents"] == []


def test_integration_detail_da_capacidades_con_toggles(client, demo_tenant, demo_login):
    demo_login(client)
    body = client.get("/v1/integrations/odoo").json()
    caps = {c["cap"]: c for c in body["capabilities"]}
    # Odoo lee cartera, directorio, catálogo y compras: todas cableadas (vivas, prendibles).
    assert caps["cuentas_por_cobrar"]["live"] is True
    assert caps["cuentas_por_cobrar"]["enabled"] is True
    assert caps["cuentas_por_cobrar"]["toggleable"] is True
    assert caps["catalogo_productos"]["live"] is True
    assert caps["catalogo_productos"]["toggleable"] is True
    # Sin ayudantes creados, la capacidad no le atribuye el uso a nadie.
    assert caps["cuentas_por_cobrar"]["agents"] == []


def test_live_de_capacidades_es_una_sola_verdad():
    """Blindaje anti-regresión: el `live` del mapa (SOURCE_CAPS) se DERIVA de una sola
    fuente (lectura cableada + flujos vivos no-lectura), así el mapa y el selector "de
    dónde lee" de los aiudantes no pueden volver a contradecirse."""
    from aiuda_server.api import integrations as I

    for src, caps in I.SOURCE_CAPS.items():
        for cap, live in caps:
            expected = I._lee_en_vivo(src, cap) or (src, cap) in I._NON_READ_LIVE
            assert live is expected, f"{src}.{cap}: mapa={live} vs cableado={expected}"

    # Toda lectura cableada aparece como live en el mapa (no se sub-reporta).
    for src, caps in I._LECTURA_CABLEADA.items():
        provided = dict(I.SOURCE_CAPS.get(src, []))
        for cap in caps:
            assert provided.get(cap) is True, f"{src}.{cap} cableado pero no live en el mapa"

    # El live por conector (badge del catálogo) coincide con "tiene alguna capacidad viva".
    for item in I.CATALOG:
        any_live = any(live for _, live in I.SOURCE_CAPS.get(item["key"], []))
        assert item["live"] is any_live, f"{item['key']}: catálogo={item['live']} vs caps={any_live}"


def test_apagar_capacidad_se_guarda(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.put(
        "/v1/integrations/odoo/capabilities", json={"disabled": ["cuentas_por_cobrar"]}
    )
    assert res.status_code == 200
    detail = client.get("/v1/integrations/odoo").json()
    caps = {c["cap"]: c for c in detail["capabilities"]}
    assert caps["cuentas_por_cobrar"]["enabled"] is False
    # Apagar una capacidad NO marca la fuente como conectada.
    graph = client.get("/v1/integrations").json()
    assert next(s for s in graph["systems"] if s["key"] == "odoo")["connected"] is False


def test_probar_conexion_sin_credenciales(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.post("/v1/integrations/odoo/test")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "guarda" in body["message"].lower()


def test_probar_conexion_odoo_credenciales_incompletas(client, demo_tenant, demo_login):
    demo_login(client)
    # Guarda solo la URL: faltan db/usuario/api_key. No toca la red.
    client.put("/v1/integrations/odoo/config", json={"values": {"url": "http://x:8069"}})
    body = client.post("/v1/integrations/odoo/test").json()
    assert body["ok"] is False
    assert "Faltan datos" in body["message"]


def test_probar_conexion_odoo_distingue_contactos_de_clientes(client, demo_tenant, monkeypatch, demo_login):
    """Señal honesta para el dueño: el detalle separa los contactos totales de
    Odoo de los clientes que el sync de verdad lee. Antes decía "Clientes: 25"
    (search_count sin filtro) cuando fetch_partners ingiere 3."""
    demo_login(client)
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "http://x:8069", "db": "d", "username": "u", "api_key": "k"}},
    )

    import aiuda_core.connectors.odoo as odoo_mod

    class FakeConn:
        def __init__(self, *args, **kwargs):
            pass

        def test_connection(self):
            # La forma que hoy devuelve OdooConnector.test_connection (contrato
            # pinned en core/tests/test_odoo_contrato.py con los datos de Hanova).
            return {"version": "19.0+e-20260318", "partners": 25, "clientes": 3, "invoices": 1}

    monkeypatch.setattr(odoo_mod, "OdooConnector", FakeConn)
    body = client.post("/v1/integrations/odoo/test").json()
    assert body["ok"] is True
    assert body["details"] == {
        "Contactos en Odoo": 25,
        "Clientes que se leen": 3,
        "Facturas por cobrar": 1,
    }


def test_probar_conexion_fuente_por_habilitar(client, demo_tenant, demo_login):
    demo_login(client)
    # Excel es carga de archivo: no hay a qué "conectarse", así que responde honesto.
    # (Shopify, Belvo, Stripe, etc. ya tienen prueba real contra su API.)
    body = client.post("/v1/integrations/excel/test").json()
    assert body["ok"] is None  # honesto: aún no hay prueba real para esta fuente


def test_probar_conexion_fuentes_cableadas_piden_credenciales(client, demo_tenant, demo_login):
    """Las fuentes con prueba real (ventas/recepción) ya NO responden 'por habilitar':
    sin credenciales piden guardarlas (ok=False), señal de que el tester está cableado."""
    demo_login(client)
    for key in ("shopify", "woocommerce", "hubspot", "googlecalendar", "facturama", "facturapi", "belvo", "stripe"):
        body = client.post(f"/v1/integrations/{key}/test").json()
        assert body["ok"] is False, key
        assert "credenciales" in body["message"].lower(), key


def test_systems_del_ayudante_solo_trae_lo_que_ese_ayudante_usa(client, demo_tenant, demo_login):
    demo_login(client)
    a = client.post(
        "/v1/ayudantes",
        json={"name": "Male", "aiuditas": ["cobranza.consultar_cartera"]},
    ).json()
    body = client.get(f"/v1/ayudantes/{a['id']}/systems").json()

    assert body["name"] == "Male"
    assert "cuentas_por_cobrar" in body["needs"]
    # Cada sistema sólo muestra las capacidades que ESTE ayudante usa.
    by_key = {s["key"]: s for s in body["systems"]}
    assert all(p["cap"] in body["needs"] for p in by_key["odoo"]["provides"])


def test_systems_de_un_ayudante_ajeno_da_404(client, demo_tenant, demo_login):
    demo_login(client)
    assert client.get("/v1/ayudantes/no-existe/systems").status_code == 404

def test_instalacion_nueva_no_presume_fuentes_conectadas(client, db_session):
    """Un negocio recién instalado NO tiene ninguna fuente conectada.

    Antes se contaba WhatsApp como conectado solo porque el workspace nace con
    un identificador de instancia: la consola saludaba con "1 conectadas" a
    quien no había conectado nada."""
    from aiuda_core.config import settings
    from aiuda_core.models import Tenant

    nuevo = Tenant(name="Recién instalado", owner_phone="", evolution_instance="inst-nueva")
    db_session.add(nuevo)
    db_session.flush()
    settings.workspace_id = nuevo.id
    try:
        body = client.get("/v1/integrations").json()
        por_key = {s["key"]: s for s in body["systems"]}
        assert por_key["whatsapp"]["connected"] is False
        assert body["connected_count"] == 0
    finally:
        settings.workspace_id = ""
