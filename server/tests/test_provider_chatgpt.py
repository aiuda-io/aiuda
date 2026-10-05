"""Entrar con ChatGPT por el API: inicio, regreso del navegador, estado y desconexión.

Todo contra el servidor FALSO de core/tests/fake_chatgpt.py, que sigue la documentación
de OpenAI. Nadie ha entrado todavía con una cuenta real.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))
from fake_chatgpt import FakeChatGPT  # noqa: E402

from aiuda_core.config import settings  # noqa: E402
from aiuda_core.engine import chatgpt_auth  # noqa: E402
from aiuda_core.models import AuditLog, Base, IntegrationCredential, Tenant  # noqa: E402
from aiuda_server.api import provider as api  # noqa: E402
from aiuda_server.api.main import app, get_db  # noqa: E402

pytest.importorskip("cryptography")

# La consola local: 127.0.0.1 literal y con puerto, como la sirve `aiuda start`.
BASE = "http://127.0.0.1:4747"


@pytest.fixture(scope="module")
def _servidor():
    with FakeChatGPT() as f:
        yield f


@pytest.fixture()
def falso(_servidor, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_issuer", _servidor.base)
    monkeypatch.setattr(settings, "openai_base", f"{_servidor.base}/v1")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    original = dict(_servidor.modo)
    for lista in ("authorize", "token", "revoke", "responses"):
        _servidor.visto[lista].clear()
    chatgpt_auth._ultimo.clear()
    api._pendiente.update(intento=None, creado=0.0, error=None)
    yield _servidor
    _servidor.modo.clear()
    _servidor.modo.update(original)
    chatgpt_auth._ultimo.clear()
    api._pendiente.update(intento=None, creado=0.0, error=None)


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
def tenant(db_session):
    t = Tenant(name="Negocio", owner_phone="", evolution_instance="x", config={})
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture()
def client(db_session, tenant):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, base_url=BASE)
    app.dependency_overrides.clear()


def _navegador(url: str) -> str:
    """Lo que haría el navegador del dueño: ir a OpenAI y seguir el regreso. Devuelve
    la ruta + query con la que OpenAI lo manda de vuelta a aiuda."""
    resp = httpx.get(url, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    destino = urlsplit(resp.headers["location"])
    assert f"{destino.scheme}://{destino.netloc}" == BASE
    return f"{destino.path}?{destino.query}"


def _entrar(client, **body):
    inicio = client.post("/v1/provider/chatgpt/iniciar", json=body or None)
    assert inicio.status_code == 200, inicio.text
    return client.get(_navegador(inicio.json()["url"]))


def _bundle(db_session, tenant) -> dict:
    db_session.expire_all()
    from aiuda_core.connectors import credentials

    return chatgpt_auth.parse_secret(credentials.read_stored(db_session, tenant.id, "ia")["secret"])


# --- el camino completo ------------------------------------------------------
def test_entrar_deja_la_ia_conectada_con_el_plan_del_dueno(falso, client, db_session, tenant):
    antes = client.get("/v1/provider").json()["chatgpt"]
    assert antes == {
        "pendiente": False, "error": None, "email": None, "registrada": False,
        "vencida": False, "bienvenida_vista": False,
    }

    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    # En pruebas el navegador no se abre; la URL se devuelve igual, como respaldo.
    assert inicio["abierto"] is False
    q = {k: v[0] for k, v in parse_qs(urlsplit(inicio["url"]).query).items()}
    assert q["redirect_uri"] == f"{BASE}/auth/callback"
    assert q["agent_name_hint"] == "aiuda" and q["client_id"] == "dynamic_agent_client"
    assert client.get("/v1/provider").json()["chatgpt"]["pendiente"] is True

    regreso = client.get(_navegador(inicio["url"]))
    assert regreso.status_code == 200
    assert "Ya puedes cerrar esta pestaña" in regreso.text
    assert regreso.headers["cache-control"] == "no-store"
    assert regreso.headers["referrer-policy"] == "no-referrer"

    estado = client.get("/v1/provider").json()
    assert (estado["name"], estado["mode"], estado["connected"]) == ("chatgpt", "oauth", True)
    assert estado["secret"] == ""
    assert estado["chatgpt"] == {
        "pendiente": False, "error": None, "email": "dueno@ejemplo.mx", "registrada": True,
        "vencida": False, "bienvenida_vista": False,
    }

    # Los tokens van cifrados: nada de ellos en claro en la fila ni en el config.
    bundle = _bundle(db_session, tenant)
    row = db_session.scalar(select(IntegrationCredential))
    assert row.public_config == {"name": "chatgpt", "mode": "oauth"}
    for secreto in (bundle["access_token"], bundle["refresh_token"], bundle["id_token"]):
        assert secreto and secreto not in str(row.secret_ciphertext)
        assert secreto not in str(tenant.config)
    assert bundle["model"] == "gpt-falso-grande" and bundle["subject"] == "user-falso-1"
    cfg = tenant.config["chatgpt"]
    assert cfg["client_id"] == bundle["client_id"] and cfg["host_id"].startswith("urn:uuid:")

    # Queda en la bitácora, sin tokens.
    hecho = db_session.scalars(select(AuditLog).where(AuditLog.action == "provider.update")).all()
    assert len(hecho) == 1 and bundle["access_token"] not in str(hecho[0].after)

    # Y la prueba de conexión pasa por el mismo camino que el motor.
    prueba = client.post("/v1/provider/test").json()
    assert prueba["ok"] is True and prueba["mode"] == "oauth"
    assert prueba["model"] == "gpt-falso-grande"
    assert falso.visto["responses"][-1]["headers"]["authorization"] == (
        f"Bearer {bundle['access_token']}"
    )


def test_el_aviso_de_que_se_usa_el_plan_se_marca_visto_una_vez(falso, client, tenant):
    _entrar(client)
    assert client.post("/v1/provider/chatgpt/entendido").json() == {"bienvenida_vista": True}
    assert client.get("/v1/provider").json()["chatgpt"]["bienvenida_vista"] is True
    # Desconectar y volver a entrar no lo repite.
    client.delete("/v1/provider")
    _entrar(client)
    assert client.get("/v1/provider").json()["chatgpt"]["bienvenida_vista"] is True


def test_administrar_uso_devuelve_la_pagina_oficial(falso, client):
    assert client.post("/v1/provider/chatgpt/uso").json() == {
        "url": "https://chatgpt.com/settings/usage", "abierto": False,
    }


# --- el regreso se valida ----------------------------------------------------
def test_un_regreso_con_otro_state_no_conecta_ni_tumba_el_intento(falso, client):
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    bueno = _navegador(inicio["url"])

    for malo in ("/auth/callback?code=x&state=inventado", "/auth/callback?code=x"):
        r = client.get(malo)
        assert r.status_code == 400 and "no corresponde a un intento abierto" in r.text
    # Dos `state` en la misma URL tampoco.
    state = parse_qs(urlsplit(bueno).query)["state"][0]
    assert client.get(f"/auth/callback?code=x&state={state}&state=otro").status_code == 400
    assert client.get("/v1/provider").json()["connected"] is False

    # El intento de verdad sigue vivo y termina bien.
    assert client.get(bueno).status_code == 200
    assert client.get("/v1/provider").json()["connected"] is True


def test_el_regreso_sirve_una_sola_vez(falso, client):
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    regreso = _navegador(inicio["url"])
    assert client.get(regreso).status_code == 200
    assert client.get(regreso).status_code == 400
    assert [f["grant_type"] for f in falso.visto["token"]] == ["authorization_code"]


def test_sin_intento_abierto_el_regreso_no_hace_nada(falso, client):
    assert client.get("/auth/callback?code=x&state=y").status_code == 400
    assert falso.visto["token"] == []


def test_un_intento_viejo_ya_no_sirve(falso, client, monkeypatch):
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    regreso = _navegador(inicio["url"])
    api._pendiente["creado"] -= api.INTENTO_TTL_S + 1
    assert client.get(regreso).status_code == 400
    assert client.get("/v1/provider").json()["chatgpt"]["pendiente"] is False


def test_el_regreso_tiene_que_llegar_por_la_misma_direccion(falso, client):
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    regreso = _navegador(inicio["url"])
    for host in ("localhost:4747", "127.0.0.1:9999", "malo.example"):
        assert client.get(regreso, headers={"host": host}).status_code == 400
    assert client.get(regreso).status_code == 200


def test_si_el_dueno_no_da_permiso_se_dice_y_no_se_canjea_nada(falso, client):
    falso.modo["authorize"] = "denegar"
    r = _entrar(client)
    assert "No diste permiso. No se conectó nada." in r.text
    assert falso.visto["token"] == []
    estado = client.get("/v1/provider").json()
    assert estado["connected"] is False
    assert estado["chatgpt"]["error"] == "No diste permiso. No se conectó nada."
    # Un intento nuevo limpia el error anterior.
    client.post("/v1/provider/chatgpt/iniciar")
    assert client.get("/v1/provider").json()["chatgpt"]["error"] is None


@pytest.mark.parametrize("modo", ["sin_client_id", "otro_client_id"])
def test_registro_sin_un_client_id_propio_y_valido_no_conecta(falso, client, tenant, modo):
    falso.modo["authorize"] = modo
    r = _entrar(client)
    # sin_client_id: registro incompleto. otro_client_id: el canje no cuadra con el código.
    assert "No se pudo conectar" in r.text
    assert client.get("/v1/provider").json()["connected"] is False


def test_el_client_id_de_arranque_nunca_se_guarda(falso, client, tenant, db_session):
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    state = parse_qs(urlsplit(inicio["url"]).query)["state"][0]
    r = client.get(f"/auth/callback?code=x&state={state}&client_id=dynamic_agent_client")
    assert "no terminó de registrar a aiuda" in r.text
    db_session.refresh(tenant)
    assert "client_id" not in tenant.config["chatgpt"]
    assert falso.visto["token"] == []


def test_si_el_canje_falla_el_registro_se_conserva_y_no_se_crea_otra_app(
    falso, client, tenant, db_session
):
    falso.modo["token"] = "caido"
    assert "No se pudo conectar" in _entrar(client).text
    db_session.refresh(tenant)
    registrado = tenant.config["chatgpt"]["client_id"]
    assert registrado.startswith("oaiapp_falso_")

    falso.modo["token"] = "ok"
    assert _entrar(client).status_code == 200
    # El segundo intento ya no fue un registro: entró con el client_id emitido.
    segundo = falso.visto["authorize"][-1]
    assert segundo["client_id"] == registrado and "agent_name_hint" not in segundo
    assert client.get("/v1/provider").json()["connected"] is True


def test_volver_a_entrar_con_un_client_id_distinto_se_rechaza(falso, client):
    _entrar(client)
    client.delete("/v1/provider")
    falso.modo["authorize"] = "otro_client_id"
    r = _entrar(client)
    assert "contestó para otra aplicación" in r.text
    assert client.get("/v1/provider").json()["connected"] is False


def test_volver_a_entrar_con_otra_cuenta_se_rechaza_y_se_puede_pedir_a_proposito(
    falso, client, tenant, db_session
):
    _entrar(client)
    primero = _bundle(db_session, tenant)
    falso.modo.update(sub="user-falso-2", email="otra@ejemplo.mx")

    r = _entrar(client)
    assert "cuenta distinta a la que ya estaba registrada" in r.text
    # La conexión que ya había no se pisa, y los tokens de la cuenta equivocada se revocan.
    assert _bundle(db_session, tenant)["access_token"] == primero["access_token"]
    assert len(falso.visto["revoke"]) == 1

    assert _entrar(client, otra_cuenta=True).status_code == 200
    nuevo = _bundle(db_session, tenant)
    assert nuevo["subject"] == "user-falso-2" and nuevo["client_id"] != primero["client_id"]
    assert client.get("/v1/provider").json()["chatgpt"]["email"] == "otra@ejemplo.mx"


def test_entrar_sin_autorizar_el_plan_no_conecta(falso, client):
    falso.modo["authorize"] = "sin_plan"
    r = _entrar(client)
    assert "no autorizaste usar tu plan de ChatGPT" in r.text
    assert client.get("/v1/provider").json()["connected"] is False
    assert len(falso.visto["revoke"]) == 1


@pytest.mark.parametrize("modo", [{"firma_mala": True}, {"nonce": "de-otro"}, {"aud": "oaiapp_x"}])
def test_identidad_que_no_se_puede_comprobar_no_conecta(falso, client, modo):
    falso.modo.update(modo)
    r = _entrar(client)
    assert "no se pudo comprobar" in r.text
    assert client.get("/v1/provider").json()["connected"] is False


# --- lo que NO se puede hacer ------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        {"name": "chatgpt", "mode": "oauth", "secret": '{"access_token": "x"}'},
        {"name": "chatgpt", "mode": "api_key", "secret": "x"},
        {"name": "codex", "mode": "oauth", "secret": "x"},
    ],
)
def test_no_se_puede_conectar_chatgpt_pegando_algo(falso, client, body):
    r = client.put("/v1/provider", json=body)
    assert r.status_code == 400
    assert "entrando con tu cuenta" in r.json()["detail"]
    assert client.get("/v1/provider").json()["connected"] is False


def _por_la_red(metodo: str, ruta: str, **kw):
    """La misma app, entrando por la puerta de la red con un aparato del dueño."""
    from aiuda_server.api import main
    from aiuda_server.red_local import _YaArrancada

    class Dueno:
        papel = "dueno"
        activo = True
        id = "d1"
        nombre = "Teléfono"

        def puede_aprobar(self, monto=None):
            return True

    original = main._aparato_de
    main._aparato_de = lambda request: Dueno()
    try:
        return TestClient(_YaArrancada(app), base_url=BASE).request(metodo, ruta, **kw)
    finally:
        main._aparato_de = original


def test_desde_la_red_no_se_empieza_ni_se_termina_un_login(falso, client):
    r = _por_la_red("POST", "/v1/provider/chatgpt/iniciar")
    assert r.status_code == 400 and "computadora donde corre aiuda" in r.json()["detail"]
    assert _por_la_red("POST", "/v1/provider/chatgpt/uso").status_code == 400

    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    regreso = _navegador(inicio["url"])
    assert _por_la_red("GET", regreso).status_code == 404
    assert falso.visto["token"] == []
    # Y sin aparato emparejado, la puerta de la red ni siquiera llega a la ruta.
    from aiuda_server.red_local import _YaArrancada

    sin_aparato = TestClient(_YaArrancada(app), base_url=BASE).get(regreso)
    assert sin_aparato.status_code == 401
    # El intento sigue vivo para el navegador de la propia computadora.
    assert client.get(regreso).status_code == 200


def test_el_guardia_de_sesion_solo_deja_pasar_el_regreso(falso, client, monkeypatch):
    monkeypatch.setattr(settings, "session_token", "el-bueno")
    # Sin cookie: la consola y el API siguen cerrados...
    assert client.get("/v1/provider").status_code == 401
    assert client.post("/v1/provider/chatgpt/iniciar").status_code == 401
    assert client.get("/auth/callback/otra").status_code == 401
    assert client.get("/auth").status_code == 401
    # ...y el regreso pasa el guardia, pero sin un intento abierto no hace nada.
    r = client.get("/auth/callback?code=x&state=y")
    assert r.status_code == 400 and "no corresponde a un intento abierto" in r.text

    # Con la cookie de la consola se empieza; el navegador regresa SIN ella y conecta.
    client.cookies.set("aiuda_local", "el-bueno")
    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    regreso = _navegador(inicio["url"])
    client.cookies.clear()
    assert client.get(regreso).status_code == 200
    client.cookies.set("aiuda_local", "el-bueno")
    assert client.get("/v1/provider").json()["connected"] is True


# --- vencer y desconectar ----------------------------------------------------
def test_sesion_vencida_se_ve_en_el_estado_y_la_prueba_lo_dice(falso, client, db_session, tenant):
    _entrar(client)
    bundle = _bundle(db_session, tenant)
    chatgpt_auth._persistir(db_session, tenant.id, {**bundle, "expires_at": 0})
    falso.modo["refresh"] = "refresh_token_expired"

    prueba = client.post("/v1/provider/test").json()
    assert prueba == {
        "ok": False, "mode": "oauth", "code": "auth",
        "error": "Tu conexión con ChatGPT venció. Vuelve a entrar con ChatGPT en Tu IA.",
    }
    estado = client.get("/v1/provider").json()
    assert estado["connected"] is False and estado["name"] == "chatgpt"
    assert estado["chatgpt"]["vencida"] is True and estado["chatgpt"]["registrada"] is True

    # Volver a entrar la revive con el mismo registro.
    falso.modo["refresh"] = "ok"
    assert _entrar(client).status_code == 200
    assert falso.visto["authorize"][-1]["client_id"] == bundle["client_id"]
    assert falso.visto["authorize"][-1]["login_hint"] == "dueno@ejemplo.mx"
    assert client.get("/v1/provider").json()["connected"] is True


def test_el_limite_del_plan_llega_a_la_consola_con_su_codigo(falso, client):
    _entrar(client)
    falso.modo["responses"] = "limite"
    prueba = client.post("/v1/provider/test").json()
    assert prueba["ok"] is False and prueba["code"] == "limite"
    assert "Administrar uso" in prueba["error"]


def test_desconectar_revoca_borra_los_tokens_y_conserva_el_registro(
    falso, client, db_session, tenant
):
    _entrar(client)
    bundle = _bundle(db_session, tenant)

    r = client.delete("/v1/provider").json()
    assert r == {"connected": False, "env_fallback": False}
    assert falso.visto["revoke"][-1]["token"] == bundle["refresh_token"]
    assert db_session.scalar(select(IntegrationCredential)) is None
    assert chatgpt_auth._ultimo == {}
    db_session.refresh(tenant)
    cfg = tenant.config["chatgpt"]
    assert cfg["client_id"] == bundle["client_id"] and cfg["email"] == "dueno@ejemplo.mx"
    estado = client.get("/v1/provider").json()
    assert estado["connected"] is False and estado["chatgpt"]["registrada"] is True


def test_desconectar_sin_poder_avisar_a_openai_borra_igual_y_lo_dice(falso, client, db_session):
    _entrar(client)
    falso.modo["revoke"] = "caido"
    r = client.delete("/v1/provider").json()
    assert r["connected"] is False
    assert "no pudimos confirmar la desconexión con OpenAI" in r["aviso"]
    assert db_session.scalar(select(IntegrationCredential)) is None
