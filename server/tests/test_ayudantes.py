"""Ayudantes del dueño + catálogo de aiuditas (capability-first)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Customer, Product, Tenant
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
        evolution_instance="demo-ayud",
        config={"demo": True, "members": []},
    )
    db_session.add(t)
    db_session.flush()
    return t


# --- Catálogo ---------------------------------------------------------------

def test_catalogo_trae_perfiles_y_perillas(client):
    cat = client.get("/v1/aiuditas/catalog")
    assert cat.status_code == 200
    data = cat.json()
    assert len(data["perfiles"]) == 8
    red = next(a for a in data["aiuditas"] if a["id"] == "cobranza.redactar_recordatorio")
    assert red["live"] is True
    assert red["reglas_libres"] is True
    tono = next(p for p in red["perillas"] if p["key"] == "tono_base")
    assert tono["tipo"] == "enum"
    assert {o["value"] for o in tono["opciones"]} == {"amable", "directo", "firme"}


# --- CRUD + config ----------------------------------------------------------

def test_crear_desde_plantilla_precarga_config_default(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.post(
        "/v1/ayudantes",
        json={"name": "abi", "aiuditas": ["cobranza.redactar_recordatorio", "no.existe"]},
    )
    assert res.status_code == 201
    a = res.json()
    assert a["name"] == "abi"
    # la desconocida se ignora; la válida entra con su config por defecto
    assert list(a["aiuditas"].keys()) == ["cobranza.redactar_recordatorio"]
    cfg = a["aiuditas"]["cobranza.redactar_recordatorio"]
    assert cfg["tono_base"] == "amable"
    assert cfg["escalar_por_atraso"] is True
    assert cfg["reglas"] == ""


def test_set_aiudita_valida_y_acota(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "ome"}).json()["id"]
    # config sucia: enum inválido, número fuera de rango, llave desconocida
    res = client.put(
        f"/v1/ayudantes/{aid}/aiuditas/cobranza.enviar_whatsapp",
        json={"config": {"autonomia": "hackeado", "cooldown_dias": 999, "basura": "x"}},
    )
    assert res.status_code == 200
    cfg = res.json()["aiuditas"]["cobranza.enviar_whatsapp"]
    assert cfg["autonomia"] == "siempre_pedir"  # enum inválido -> default
    assert cfg["cooldown_dias"] == 30  # acotado al máximo
    assert "basura" not in cfg  # lo desconocido se descarta


def test_quitar_aiudita(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post(
        "/v1/ayudantes", json={"name": "gio", "aiuditas": ["cobranza.consultar_cartera"]}
    ).json()["id"]
    res = client.delete(f"/v1/ayudantes/{aid}/aiuditas/cobranza.consultar_cartera")
    assert res.status_code == 200
    assert res.json()["aiuditas"] == {}


def test_aiudita_desconocida_404(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "uli"}).json()["id"]
    res = client.put(f"/v1/ayudantes/{aid}/aiuditas/no.existe", json={"config": {}})
    assert res.status_code == 404


def test_editar_y_eliminar(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "tavo"}).json()["id"]
    client.put(f"/v1/ayudantes/{aid}", json={"name": "Tavo el cobrador"})
    assert client.get(f"/v1/ayudantes/{aid}").json()["name"] == "Tavo el cobrador"
    assert client.delete(f"/v1/ayudantes/{aid}").status_code == 204
    assert client.get(f"/v1/ayudantes/{aid}").status_code == 404


def test_instrucciones_persisten_y_entran_al_prompt(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post(
        "/v1/ayudantes", json={"name": "abi", "aiuditas": ["cobranza.consultar_cartera"]}
    ).json()["id"]
    instr = "Habla siempre de usted y sé muy breve."
    r = client.put(f"/v1/ayudantes/{aid}", json={"instructions": instr})
    assert r.status_code == 200
    assert r.json()["instructions"] == instr
    # el detalle las devuelve
    assert client.get(f"/v1/ayudantes/{aid}").json()["instructions"] == instr
    # y la vista previa del prompt REAL las incluye (fuente única de verdad)
    prompt = client.get(f"/v1/ayudantes/{aid}/prompt").json()["system"]
    assert instr in prompt
    assert "abi" in prompt  # persona + capacidades ensambladas de verdad
    # limpiar con "" borra
    client.put(f"/v1/ayudantes/{aid}", json={"instructions": "   "})
    assert client.get(f"/v1/ayudantes/{aid}").json()["instructions"] == ""


def test_endpoints_locales_sin_sesion(client, demo_tenant):
    # En local no hay sesiones: el API resuelve el workspace único y responde.
    assert client.get("/v1/ayudantes").status_code == 200
    assert client.get("/v1/aiuditas/catalog").status_code == 200


def test_chat_sin_proveedor_responde_gracioso(client, demo_tenant, monkeypatch, demo_login):
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")  # sin proveedor de IA
    demo_login(client)
    aid = client.post(
        "/v1/ayudantes", json={"name": "abi", "aiuditas": ["cobranza.consultar_cartera"]}
    ).json()["id"]
    res = client.post(f"/v1/ayudantes/{aid}/chat", json={"message": "¿cómo va la cartera?"})
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "abi" in reply and "proveedor" in reply.lower()


def test_chat_mensaje_vacio_400(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "ome"}).json()["id"]
    assert client.post(f"/v1/ayudantes/{aid}/chat", json={"message": "  "}).status_code == 400


def test_generar_cotizacion(client, demo_tenant, db_session, monkeypatch, demo_login):
    from aiuda_core.config import settings as s

    monkeypatch.setattr(s, "anthropic_api_key", "")  # sin LLM: cuerpo determinista + intro fallback
    c = Customer(tenant_id=demo_tenant.id, name="Joyería Aurora", phone="5215511112222")
    p = Product(tenant_id=demo_tenant.id, name="Anillo oro 14k", sku="AN-14", price=1000, stock=5)
    db_session.add_all([c, p])
    db_session.flush()
    demo_login(client)
    res = client.post(
        "/v1/quotes",
        json={"customer_id": c.id, "items": [{"product_id": p.id, "cantidad": 2}]},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending_approval"
    assert "Joyería Aurora" in body["title"]
    assert "$2,000.00" in body["message"]  # 1000 x2
    # aparece en la bandeja de aprobaciones, como agente carlos
    pend = client.get("/v1/reminders?status=pending_approval").json()
    assert any(r["agent"] == "carlos" for r in pend)


def test_cotizacion_cliente_inexistente_404(client, demo_tenant, demo_login):
    demo_login(client)
    res = client.post("/v1/quotes", json={"customer_id": "x", "items": [{"product_id": "y"}]})
    assert res.status_code == 404


def test_reminders_exponen_procedencia_de_la_cotizacion(client, demo_tenant, db_session, monkeypatch, demo_login):
    from aiuda_core.config import settings as s

    monkeypatch.setattr(s, "anthropic_api_key", "")
    c = Customer(tenant_id=demo_tenant.id, name="Joyería Aurora", phone="5215511112222")
    p = Product(
        tenant_id=demo_tenant.id, name="Anillo oro 14k", sku="AN-14", price=1000, stock=5,
        source="excel", presence={"excel": {"file": "catalogo.xlsx", "at": "2026-06-15"}},
    )
    db_session.add_all([c, p])
    db_session.flush()
    demo_login(client)
    client.post("/v1/quotes", json={"customer_id": c.id, "items": [{"product_id": p.id, "cantidad": 1}]})
    pend = client.get("/v1/reminders?status=pending_approval").json()
    quote = next(r for r in pend if r["agent"] == "carlos")
    assert quote["procedencia"]["source"] == "excel"
    assert quote["procedencia"]["presence"]["excel"]["file"] == "catalogo.xlsx"


# --- Fuente por aiudita (de dónde lee) --------------------------------------

def test_catalogo_trae_fuentes_de_la_capacidad(client):
    data = client.get("/v1/aiuditas/catalog").json()
    cart = next(a for a in data["aiuditas"] if a["id"] == "cobranza.consultar_cartera")
    assert cart["capacidad"] == "cuentas_por_cobrar"
    fuentes = {f["key"]: f for f in cart["fuentes"]}
    assert fuentes["excel"]["live"] is True       # el importador ya lee hoy
    # la lectura de cartera de Odoo ya está cableada (sync_fuentes) -> viva
    assert fuentes["odoo"]["live"] is True
    # el CATÁLOGO (productos) lo leen Excel, Odoo, Shopify y Woo (sync_catalogo);
    # misma capacidad, cuatro fuentes, ninguna privilegiada
    cot = next(a for a in data["aiuditas"] if a["id"] == "ventas.generar_cotizacion")
    fcot = {f["key"]: f for f in cot["fuentes"]}
    assert fcot["excel"]["live"] is True and fcot["odoo"]["live"] is True
    assert fcot["shopify"]["live"] is True
    assert fcot["woocommerce"]["live"] is True
    # directorio de clientes: Odoo, HubSpot y Shopify ya lo leen (sync_directorio) -> vivos
    cli = next(a for a in data["aiuditas"] if a["id"] == "ventas.consultar_cliente")
    cli_live = {f["key"]: f["live"] for f in cli["fuentes"]}
    assert cli_live["odoo"] is True and cli_live["hubspot"] is True
    assert cli_live["shopify"] is True
    # prospección: HubSpot (deals) y DENUE (directorio público) ya la leen -> vivas
    pro = next(a for a in data["aiuditas"] if a["id"] == "prospeccion.buscar_prospectos")
    pro_live = {f["key"]: f["live"] for f in pro["fuentes"]}
    assert pro_live["hubspot"] is True and pro_live["denue"] is True
    # agenda: Google Calendar ya la lee (sync_agenda, list_events) -> viva
    ag = next(a for a in data["aiuditas"] if a["id"] == "recepcion.consultar_agenda")
    assert {f["key"]: f["live"] for f in ag["fuentes"]}["googlecalendar"] is True
    # CFDI: Facturama y Facturapi ya lo leen (sync_cfdi) -> vivos
    cfd = next(a for a in data["aiuditas"] if a["id"] == "conciliacion.descargar_cfdi")
    cfd_live = {f["key"]: f["live"] for f in cfd["fuentes"]}
    assert cfd_live["facturama"] is True and cfd_live["facturapi"] is True
    # compras: Odoo ya lee las ordenes de compra (sync_compras) -> viva
    com = next(a for a in data["aiuditas"] if a["id"] == "compras.monitorear_ocs")
    assert {f["key"]: f["live"] for f in com["fuentes"]}["odoo"] is True
    # una aiudita que no lee datos no trae fuentes
    env = next(a for a in data["aiuditas"] if a["id"] == "cobranza.enviar_whatsapp")
    assert env["capacidad"] == "" and "fuentes" not in env


def test_crear_precarga_fuente_default(client, demo_tenant, demo_login):
    demo_login(client)
    a = client.post(
        "/v1/ayudantes", json={"name": "abi", "aiuditas": ["cobranza.consultar_cartera"]}
    ).json()
    # la fuente viva por defecto = Excel (lo que de verdad jala hoy)
    assert a["aiuditas"]["cobranza.consultar_cartera"]["_fuente"] == "excel"


def test_fuentes_preferidas_solo_cuenta_eleccion_explicita(client, demo_tenant, db_session, demo_login):
    from aiuda_server.api.integrations import fuentes_preferidas

    demo_login(client)
    aid = client.post(
        "/v1/ayudantes", json={"name": "abi", "aiuditas": ["cobranza.consultar_cartera"]}
    ).json()["id"]
    # _fuente por defecto = excel (== default): NO cuenta como eleccion -> no suprime nada
    assert fuentes_preferidas(db_session, demo_tenant) == {}
    # el dueno elige EXPLICITAMENTE Odoo para su cartera -> ahora si es preferencia real
    client.put(
        f"/v1/ayudantes/{aid}/aiuditas/cobranza.consultar_cartera",
        json={"config": {"_fuente": "odoo"}},
    )
    assert fuentes_preferidas(db_session, demo_tenant) == {"cuentas_por_cobrar": "odoo"}


def test_cua_es_fuente_elegible_para_capacidad_sin_api(client, demo_tenant, db_session, demo_login):
    """El fallback CUA se ofrece como fuente ('de donde lee' = CUA) en capacidades sin
    conector API (cfdi). Elegirlo cuenta como preferencia real que el motor enruta."""
    from aiuda_server.api.integrations import fuente_valida, fuentes_preferidas

    assert fuente_valida("cfdi", "cua") is True  # CUA es elegible para CFDI
    assert fuente_valida("cuentas_por_cobrar", "cua") is False  # no para capacidades con API
    demo_login(client)
    aid = client.post(
        "/v1/ayudantes", json={"name": "lupe", "aiuditas": ["conciliacion.descargar_cfdi"]}
    ).json()["id"]
    r = client.put(
        f"/v1/ayudantes/{aid}/aiuditas/conciliacion.descargar_cfdi",
        json={"config": {"_fuente": "cua"}},
    )
    assert r.json()["aiuditas"]["conciliacion.descargar_cfdi"]["_fuente"] == "cua"
    assert fuentes_preferidas(db_session, demo_tenant) == {"cfdi": "cua"}


def test_set_aiudita_valida_la_fuente(client, demo_tenant, demo_login):
    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "ome"}).json()["id"]
    # fuente que no provee esta capacidad -> cae al default vivo (excel)
    r = client.put(
        f"/v1/ayudantes/{aid}/aiuditas/cobranza.consultar_cartera",
        json={"config": {"_fuente": "stripe"}},
    )
    assert r.json()["aiuditas"]["cobranza.consultar_cartera"]["_fuente"] == "excel"
    # fuente posible (aunque "por conectar") -> se respeta la elección del dueño
    r2 = client.put(
        f"/v1/ayudantes/{aid}/aiuditas/cobranza.consultar_cartera",
        json={"config": {"_fuente": "odoo"}},
    )
    assert r2.json()["aiuditas"]["cobranza.consultar_cartera"]["_fuente"] == "odoo"


# --- Correr al ayudante + plan de carrera ------------------------------------

class _FakeRunner:
    """Runner mínimo para la corrida: redacta sin IA real, pero un texto que sí se
    le podría mandar a un cliente (el motor descarta lo que no cita folio y monto)."""

    _usage_callback = None

    def complete(self, system, user, **kw):
        return "Buen día, le recuerdo su factura F-77 por $1,800.00, ya vencida."


def _factura_vencida(db_session, tenant):
    from datetime import date, timedelta

    from aiuda_core.models import Customer, Invoice

    c = Customer(tenant_id=tenant.id, name="Papelería Roma", phone="5215533334444")
    db_session.add(c)
    db_session.flush()
    inv = Invoice(
        tenant_id=tenant.id, customer_id=c.id, folio="F-77", amount=1800,
        issued_date=date.today() - timedelta(days=35),
        due_date=date.today() - timedelta(days=5), status="open",
    )
    db_session.add(inv)
    db_session.flush()
    return inv


def test_serializa_acciones_y_nivel(client, demo_tenant, demo_login):
    demo_login(client)
    a = client.post("/v1/ayudantes", json={"name": "abi"}).json()
    assert a["acciones"] == {"pendientes": 0, "enviadas": 0, "total": 0}
    assert a["nivel"]["nivel"] == "Aprendiz"
    assert a["nivel"]["siguiente"] == 10


def test_correr_produce_propuestas_atribuidas(client, demo_tenant, db_session, monkeypatch, demo_login):
    """El ciclo completo de §8: ayudante creado → corre en el motor genérico con SU
    config → deja PROPUESTAS (HITL) visibles en la bandeja, atribuidas a él — y su
    plan de carrera las cuenta como acciones reales."""
    import aiuda_core.engine.engine as engine_mod
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-prueba")  # hay credencial
    monkeypatch.setattr(engine_mod, "make_runner", lambda *a, **k: _FakeRunner())
    _factura_vencida(db_session, demo_tenant)

    demo_login(client)
    a = client.post(
        "/v1/ayudantes",
        json={
            "name": "abi",
            "aiuditas": ["cobranza.redactar_recordatorio", "cobranza.enviar_whatsapp"],
        },
    ).json()

    res = client.post(f"/v1/ayudantes/{a['id']}/correr")
    assert res.status_code == 200
    body = res.json()
    assert body["corrio"] == ["cobranza.redactar_recordatorio"]
    assert body["propuestas"] == 1
    assert body["pendientes"] == 1

    # La propuesta está en la bandeja (HITL), con su autor visible.
    pend = client.get("/v1/reminders?status=pending_approval").json()
    assert len(pend) == 1
    assert pend[0]["propuesto_por"] == "abi"
    assert pend[0]["status"] == "pending_approval"  # nada salió sin aprobación

    # Y alimenta su carrera: una acción real, derivada de la fila.
    det = client.get(f"/v1/ayudantes/{a['id']}").json()
    assert det["acciones"] == {"pendientes": 1, "enviadas": 0, "total": 1}


def test_correr_sin_credencial_409(client, demo_tenant, monkeypatch, demo_login):
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    demo_login(client)
    a = client.post(
        "/v1/ayudantes", json={"name": "gio", "aiuditas": ["cobranza.redactar_recordatorio"]}
    ).json()
    res = client.post(f"/v1/ayudantes/{a['id']}/correr")
    assert res.status_code == 409
    assert "proveedor" in res.json()["detail"].lower()


def test_correr_sin_aiuditas_corribles_es_honesto(client, demo_tenant, monkeypatch, demo_login):
    """Un ayudante solo de consulta no finge una corrida: responde qué no corre y
    dónde vive lo demás. Ni siquiera exige credencial (no hay nada que correr)."""
    from aiuda_core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    demo_login(client)
    a = client.post(
        "/v1/ayudantes", json={"name": "uli", "aiuditas": ["ventas.consultar_catalogo"]}
    ).json()
    res = client.post(f"/v1/ayudantes/{a['id']}/correr")
    assert res.status_code == 200
    body = res.json()
    assert body["corrio"] == []
    assert body["propuestas"] == 0
    assert body["sin_corrida"] == ["ventas.consultar_catalogo"]
    assert "no tiene aiuditas que corran solas" in body["detalle"]


def test_nivel_sube_de_verdad_y_se_deriva_de_filas(client, demo_tenant, db_session, demo_login):
    """La señal de carrera es REAL, no cosmética: el nivel se deriva de las filas
    atribuidas en cada lectura. Trabajo lo sube; borrar el trabajo lo baja; lo
    rechazado no cuenta."""
    from sqlalchemy import select

    from aiuda_core.models import Reminder

    demo_login(client)
    aid = client.post("/v1/ayudantes", json={"name": "abi"}).json()["id"]

    def _propuesta(i, status="pending_approval"):
        return Reminder(
            tenant_id=demo_tenant.id, bucket="vencida", tone="firme",
            message=f"m{i}", status=status,
            meta={"ayudante_id": aid, "ayudante_name": "abi"},
        )

    db_session.add_all([_propuesta(i) for i in range(9)])
    db_session.flush()
    assert client.get(f"/v1/ayudantes/{aid}").json()["nivel"]["nivel"] == "Aprendiz"

    db_session.add(_propuesta(9, status="sent"))
    # Una rechazada NO da carrera.
    db_session.add(_propuesta(10, status="rejected"))
    db_session.flush()
    det = client.get(f"/v1/ayudantes/{aid}").json()
    assert det["acciones"]["total"] == 10
    assert det["nivel"]["nivel"] == "Junior"  # subió DE VERDAD

    # Borrar el trabajo baja el nivel: no hay contador guardado que quede inflado.
    for r in db_session.scalars(select(Reminder)).all():
        db_session.delete(r)
    db_session.flush()
    assert client.get(f"/v1/ayudantes/{aid}").json()["nivel"]["nivel"] == "Aprendiz"


def test_agents_del_equipo_traen_nivel(client, demo_tenant, db_session, demo_login):
    """El plan de carrera del equipo (/v1/agents) sale del backend con la misma
    escala: acciones reales → nivel. Mariana sube al acumular trabajo."""
    from aiuda_core.models import Reminder

    demo_login(client)
    antes = client.get("/v1/agents").json()
    mariana = next(x for x in antes if x["slug"] == "mariana")
    assert mariana["nivel"]["nivel"] == "Aprendiz"

    db_session.add_all(
        Reminder(
            tenant_id=demo_tenant.id, agent="mariana", bucket="vencida", tone="firme",
            message=f"m{i}", status="pending_approval",
        )
        for i in range(12)
    )
    db_session.flush()
    despues = client.get("/v1/agents").json()
    mariana = next(x for x in despues if x["slug"] == "mariana")
    assert mariana["actions"] >= 12
    assert mariana["nivel"]["nivel"] == "Junior"
