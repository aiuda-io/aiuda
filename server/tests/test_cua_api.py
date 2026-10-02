"""Recados de CUA: la cola + el log de misiones (endpoints)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.cua.fallback import ejecutar_recado
from aiuda_core.cua.mission import MissionResult
from aiuda_core.models import Base, CuaMission, Tenant
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
        name="Demo", owner_phone="5215512345678", evolution_instance="demo-cua",
        # con la URL de su banca configurada (sin ella el recado corta honesto)
        config={
            "demo": True,
            "members": [],
            "cua_portales": {"confirmacion_pago": "https://banca.example/acceso"},
        },
    )
    db_session.add(t)
    db_session.flush()
    return t


class FakeCuaOK:
    def __init__(self, data):
        self._data = data

    async def run(self, mission):
        return MissionResult(success=True, data=self._data, evidence=[])


def test_capacidades_lista_las_de_cua(client, demo_tenant, demo_login):
    demo_login(client)
    caps = client.get("/v1/cua/capacidades").json()
    porcap = {c["capacidad"]: c for c in caps}
    assert {"confirmacion_pago", "cfdi", "expedientes"} <= set(porcap)
    # la banca del demo_tenant sí tiene URL; el tribunal (expedientes) no
    assert porcap["confirmacion_pago"]["url_configurada"] is True
    assert porcap["expedientes"]["url_configurada"] is False
    # sin handoff todavía, ninguno tiene acceso conectado
    assert porcap["confirmacion_pago"]["tiene_sesion"] is False


def test_encolar_corre_y_registra_el_log(client, demo_tenant, db_session, monkeypatch, demo_login):
    # El background corre con la sesion de prueba y un runner OK (simula el ayudante).
    def fake_bg(recado_id):
        recado = db_session.get(CuaMission, recado_id)
        ejecutar_recado(db_session, recado, runner=FakeCuaOK({"depositos": [{"monto": 1500}]}))

    monkeypatch.setattr("aiuda_server.api.cua.run_recado_blocking", fake_bg)
    demo_login(client)

    res = client.post("/v1/cua/misiones", json={"capacidad": "confirmacion_pago"})
    assert res.status_code == 201
    recado = res.json()
    assert recado["capacidad"] == "confirmacion_pago" and recado["sistema"]

    # el background (fake) ya corrio: el log muestra el recado terminado con lo que extrajo
    lista = client.get("/v1/cua/misiones").json()
    assert len(lista) == 1 and lista[0]["status"] == "done"
    assert lista[0]["data"] == {"depositos": [{"monto": 1500}]}

    det = client.get(f"/v1/cua/misiones/{recado['id']}").json()
    assert "evidencia" in det  # el detalle trae las capturas (base64), aqui vacio


def test_encolar_capacidad_sin_cua_400(client, demo_tenant, demo_login):
    demo_login(client)
    r = client.post("/v1/cua/misiones", json={"capacidad": "cuentas_por_cobrar"})
    assert r.status_code == 400


def test_misiones_responde_local(client, demo_tenant):
    assert client.get("/v1/cua/misiones").status_code == 200


def test_encolar_capacidad_sin_url_de_portal_falla_honesto(client, demo_tenant, db_session, monkeypatch, demo_login):
    """expedientes (tribunal) no tiene URL configurada en el demo_tenant: el recado
    queda failed con la razon y donde configurarla — no se inventa nada."""

    def fake_bg(recado_id):
        recado = db_session.get(CuaMission, recado_id)
        ejecutar_recado(db_session, recado)

    monkeypatch.setattr("aiuda_server.api.cua.run_recado_blocking", fake_bg)
    demo_login(client)
    res = client.post("/v1/cua/misiones", json={"capacidad": "expedientes"})
    assert res.status_code == 201
    lista = client.get("/v1/cua/misiones").json()
    assert lista[0]["status"] == "failed"
    assert "dirección configurada" in lista[0]["error"]


def test_estado_reporta_navegador_y_credencial(client, demo_tenant, monkeypatch, demo_login):
    """El estado honesto que ve la UI: navegador instalado o no (con detalle accionable)
    y si el tenant tiene credencial de IA."""
    demo_login(client)

    monkeypatch.setattr(
        "aiuda_core.cua.computer.estado_navegador",
        lambda: (False, "El navegador del asistente no está instalado (extra `cua`)."),
    )
    estado = client.get("/v1/cua/estado").json()
    assert estado["navegador_listo"] is False and estado["listo"] is False
    assert "no está instalado" in estado["navegador_detalle"]
    assert estado["credencial_ia"] in (False, True)

    monkeypatch.setattr(
        "aiuda_core.cua.computer.estado_navegador", lambda: (True, "Navegador listo.")
    )
    estado = client.get("/v1/cua/estado").json()
    assert estado["navegador_listo"] is True
    # sin credencial de IA del tenant ni del entorno, listo sigue en False
    if not estado["credencial_ia"]:
        assert estado["listo"] is False


def test_estado_responde_local(client, demo_tenant):
    assert client.get("/v1/cua/estado").status_code == 200


# ---------- Portales a la medida (registrar por URL) ----------


def test_crear_listar_borrar_portal(client, demo_tenant, demo_login):
    demo_login(client)
    # sin URL válida: rechazo honesto
    assert client.post("/v1/cua/portales", json={"nombre": "X", "url": "sat.gob.mx"}).status_code == 400

    creado = client.post(
        "/v1/cua/portales",
        json={"nombre": "Mi banco", "url": "https://banco.example/acceso", "notas": "e.firma"},
    )
    assert creado.status_code == 201
    portal = creado.json()
    assert portal["nombre"] == "Mi banco" and portal["id"]

    # aparece como capacidad "portal:<id>" en el lanzador, con su URL
    caps = {c["capacidad"]: c for c in client.get("/v1/cua/capacidades").json()}
    cap = f"portal:{portal['id']}"
    assert cap in caps and caps[cap]["url_configurada"] is True and caps[cap]["editable"] is True

    # y se puede borrar
    assert client.delete(f"/v1/cua/portales/{portal['id']}").status_code == 204
    caps2 = {c["capacidad"] for c in client.get("/v1/cua/capacidades").json()}
    assert cap not in caps2


def test_encolar_portal_a_la_medida_corre(client, demo_tenant, db_session, monkeypatch, demo_login):
    """Un portal registrado por URL se despacha igual que un built-in: el recado corre y
    el log lo muestra terminado con lo que trajo."""
    demo_login(client)
    portal = client.post(
        "/v1/cua/portales", json={"nombre": "Proveedor", "url": "https://prov.example/"}
    ).json()
    cap = f"portal:{portal['id']}"

    def fake_bg(recado_id):
        recado = db_session.get(CuaMission, recado_id)
        ejecutar_recado(db_session, recado, runner=FakeCuaOK({"resultado": "3 pedidos"}))

    monkeypatch.setattr("aiuda_server.api.cua.run_recado_blocking", fake_bg)
    res = client.post("/v1/cua/misiones", json={"capacidad": cap, "instruccion": "trae pedidos"})
    assert res.status_code == 201 and res.json()["sistema"] == "Proveedor"
    lista = client.get("/v1/cua/misiones").json()
    assert lista[0]["status"] == "done"
    # lo extraído, y la instrucción del dueño preservada junto a ello
    assert lista[0]["data"]["resultado"] == "3 pedidos"
    assert lista[0]["data"]["_instruccion"] == "trae pedidos"


def test_set_url_builtin(client, demo_tenant, demo_login):
    demo_login(client)
    # expedientes (tribunal) empieza sin URL
    r = client.put(
        "/v1/cua/portales/builtin/expedientes",
        json={"url": "https://tribunal.example/boletin"},
    )
    assert r.status_code == 200 and r.json()["url_configurada"] is True
    caps = {c["capacidad"]: c for c in client.get("/v1/cua/capacidades").json()}
    assert caps["expedientes"]["url_configurada"] is True
    # capacidad inexistente: 404
    assert client.put("/v1/cua/portales/builtin/nope", json={"url": "https://x.example"}).status_code == 404


# ---------- Handoff de login (endpoints, gate honesto) ----------


def test_iniciar_sesion_sin_navegador_corta_honesto(client, demo_tenant, monkeypatch, demo_login):
    """En la nube (sin navegador) no se puede abrir la ventana: 409 con la razón, no un
    botón muerto."""
    demo_login(client)
    monkeypatch.setattr(
        "aiuda_server.api.cua.estado_handoff_posible",
        lambda: (False, "El navegador del asistente no está instalado en este servidor."),
    )
    r = client.post("/v1/cua/sesion", json={"capacidad": "confirmacion_pago"})
    assert r.status_code == 409 and "no está instalado" in r.json()["detail"]


def test_estado_expone_handoff_posible(client, demo_tenant, monkeypatch, demo_login):
    demo_login(client)
    monkeypatch.setattr(
        "aiuda_core.cua.computer.estado_navegador", lambda: (True, "Navegador listo.")
    )
    estado = client.get("/v1/cua/estado").json()
    assert estado["handoff_posible"] is True and estado["handoff_detalle"]


# ---------- La IA del dueño en el CUA: tope, uso y aviso honesto ----------


def test_recado_por_tenant_runner_cuenta_el_gasto(db_session, demo_tenant, monkeypatch):
    """El camino de la capa HTTP: `tenant_runner` arma la IA y cada paso de la misión
    queda como UsageEvent (tarea "cua"), o sea que cuenta para el tope del dueño."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from aiuda_core.connectors.credentials import set_credential
    from aiuda_core.cua.fallback import enqueue_cua_mission
    from aiuda_core.models import UsageEvent
    from aiuda_server.metering import tenant_runner

    set_credential(
        db_session, demo_tenant.id, "ia",
        {"name": "claude", "mode": "api_key", "secret": "sk-ant-prueba"},
    )
    db_session.flush()

    class Navegador:
        width, height = 1280, 800

        def __init__(self, headless=True, storage_state=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def goto(self, url):
            pass

        async def screenshot(self):
            return b"PNG"

    class Anthropic:
        def __init__(self):
            self.beta = SimpleNamespace(messages=self)

        def create(self, **kw):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"depositos": [{"monto": 10}]}')],
                usage=SimpleNamespace(input_tokens=1200, output_tokens=30),
            )

    monkeypatch.setattr("aiuda_core.cua.runner.LocalComputer", Navegador)
    monkeypatch.setattr("aiuda_core.cua.runner.paquete_playwright_instalado", lambda: True)
    monkeypatch.setattr("aiuda_core.engine.llm.build_anthropic_client", lambda cred: Anthropic())

    recado = enqueue_cua_mission(db_session, demo_tenant, "confirmacion_pago")
    ejecutar_recado(db_session, recado, ia=lambda: tenant_runner(db_session, demo_tenant))
    db_session.flush()

    assert recado.status == "done", recado.error
    usos = db_session.scalars(
        select(UsageEvent).where(UsageEvent.tenant_id == demo_tenant.id)
    ).all()
    assert [(u.task, u.input_tokens, u.output_tokens) for u in usos] == [("cua", 1200, 30)]


def test_estado_dice_por_que_la_ia_conectada_no_sirve(
    client, demo_tenant, db_session, monkeypatch, demo_login
):
    """Tener IA conectada no basta: con el CLI del dueño la oficina NO está lista, y
    el estado trae el motivo para que la consola no diga "falta conectar la IA"."""
    from aiuda_core.connectors.credentials import set_credential

    demo_login(client)
    monkeypatch.setattr(
        "aiuda_core.cua.computer.estado_navegador", lambda: (True, "Navegador listo.")
    )
    set_credential(db_session, demo_tenant.id, "ia", {"name": "claude_cli", "mode": "cli"})
    db_session.flush()
    estado = client.get("/v1/cua/estado").json()
    assert estado["credencial_ia"] is False and estado["listo"] is False
    assert "Claude Code instalado" in estado["ia_detalle"]

    set_credential(
        db_session, demo_tenant.id, "ia",
        {"name": "claude", "mode": "api_key", "secret": "sk-ant-prueba"},
    )
    db_session.flush()
    estado = client.get("/v1/cua/estado").json()
    assert estado["credencial_ia"] is True and estado["listo"] is True
