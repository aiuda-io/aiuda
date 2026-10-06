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


def _nadie_abre_el_navegador(*a, **kw):
    raise AssertionError("una prueba intentó abrir el navegador")


@pytest.fixture()
def falso(_servidor, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_issuer", _servidor.base)
    monkeypatch.setattr(settings, "openai_base", f"{_servidor.base}/v1")
    # Ninguna prueba abre una pestaña, aunque el entorno diga que sí o falte el
    # conftest de la raíz: apagado aquí, y si algo lo intenta de todos modos, falla.
    monkeypatch.setattr(settings, "abrir_navegador", False)
    monkeypatch.setattr("webbrowser.open", _nadie_abre_el_navegador)
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


def test_con_el_navegador_encendido_se_abre_la_pagina_de_openai_y_nada_mas(
    falso, client, monkeypatch
):
    """El único lugar donde se enciende, y con un navegador de mentira que solo anota."""
    abiertas: list[str] = []
    monkeypatch.setattr(settings, "abrir_navegador", True)
    monkeypatch.setattr("webbrowser.open", lambda url: abiertas.append(url) or True)

    inicio = client.post("/v1/provider/chatgpt/iniciar").json()
    assert inicio["abierto"] is True and abiertas == [inicio["url"]]
    assert inicio["url"].startswith(f"{falso.base}/api/accounts/authorize?")


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
    r = _entrar(client)
    assert r.status_code == 400 and "No se pudo conectar" in r.text
    # Una sola instrucción para reintentar, no dos pegadas.
    assert "ChatGPT no completó la entrada. Inténtalo otra vez. Vuelve a aiuda.<" in r.text
    assert r.text.count("otra vez") == 1
    db_session.refresh(tenant)
    registrado = tenant.config["chatgpt"]["client_id"]
    assert registrado.startswith("oaiapp_falso_")

    falso.modo["token"] = "ok"
    assert _entrar(client).status_code == 200
    # El segundo intento ya no fue un registro: entró con el client_id emitido.
    segundo = falso.visto["authorize"][-1]
    assert segundo["client_id"] == registrado and "agent_name_hint" not in segundo
    assert client.get("/v1/provider").json()["connected"] is True


def test_si_guardar_la_conexion_truena_el_dueno_ve_una_pagina_y_la_consola_el_motivo(
    falso, client, monkeypatch
):
    """Un fallo que no es del flujo (aquí, la llave de cifrado) no puede dejar un 500 en
    la pestaña ni a la consola diciendo que pasó demasiado tiempo."""

    def truena(*a, **kw):
        raise RuntimeError("no hay llave de cifrado")

    monkeypatch.setattr(api.cred, "set_credential", truena)
    r = _entrar(client)
    assert r.status_code == 400 and "No se pudo conectar" in r.text
    assert "aiuda no pudo guardar tu conexión con ChatGPT" in r.text
    assert "RuntimeError" not in r.text and "llave de cifrado" not in r.text
    estado = client.get("/v1/provider").json()
    assert estado["connected"] is False and estado["chatgpt"]["pendiente"] is False
    assert estado["chatgpt"]["error"].startswith("aiuda no pudo guardar")
    # Los tokens que OpenAI acababa de emitir no se quedan vivos sin dueño.
    assert len(falso.visto["revoke"]) == 1
    assert chatgpt_auth._ultimo == {}


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

    # Pedirlo a propósito y que falle a medio camino deja la cuenta de antes intacta:
    # el registro nuevo no pisa al que está en uso hasta comprobar quién entró.
    falso.modo["token"] = "caido"
    assert _entrar(client, otra_cuenta=True).status_code == 400
    db_session.refresh(tenant)
    cfg = tenant.config["chatgpt"]
    assert cfg["client_id"] == primero["client_id"] and cfg["email"] == "dueno@ejemplo.mx"
    assert cfg["subject"] == primero["subject"]
    estado = client.get("/v1/provider").json()
    assert estado["connected"] is True and estado["chatgpt"]["email"] == "dueno@ejemplo.mx"
    falso.modo["token"] = "ok"

    assert _entrar(client, otra_cuenta=True).status_code == 200
    nuevo = _bundle(db_session, tenant)
    assert nuevo["subject"] == "user-falso-2" and nuevo["client_id"] != primero["client_id"]
    assert client.get("/v1/provider").json()["chatgpt"]["email"] == "otra@ejemplo.mx"
    # Y la sesión de la cuenta anterior se cierra en OpenAI.
    assert falso.visto["revoke"][-1] == {
        "token": primero["refresh_token"],
        "token_type_hint": "refresh_token",
        "client_id": primero["client_id"],
    }
    assert chatgpt_auth._ultimo[tenant.id]["client_id"] == nuevo["client_id"]


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
def test_sesion_vencida_se_ve_en_el_estado_y_la_prueba_lo_dice(
    falso, client, db_session, tenant, monkeypatch
):
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

    # Todo lo que le cuenta al dueño si su IA está conectada dice lo mismo, y con una
    # llave en el entorno no se anuncia un respaldo que no se va a usar.
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-env")
    assert client.get("/v1/provider").json()["env_fallback"] is False
    ia = client.get("/v1/setup/estado").json()["ia"]
    assert ia["conectada"] is False and ia["proveedor"] == "chatgpt"
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    # Volver a entrar la revive con el mismo registro.
    falso.modo["refresh"] = "ok"
    assert _entrar(client).status_code == 200
    assert falso.visto["authorize"][-1]["client_id"] == bundle["client_id"]
    assert falso.visto["authorize"][-1]["login_hint"] == "dueno@ejemplo.mx"
    assert client.get("/v1/provider").json()["connected"] is True
    assert client.get("/v1/setup/estado").json()["ia"]["conectada"] is True


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


# --- cambiar de ChatGPT a otra IA --------------------------------------------
@pytest.mark.parametrize("secreto", ["", "••••••"])
def test_guardar_otra_ia_sin_su_llave_no_hereda_los_tokens_de_chatgpt(
    falso, client, db_session, tenant, secreto
):
    """Con ChatGPT conectado, un PUT de otro proveedor sin llave NO puede quedarse con
    lo guardado: serían los tokens del dueño etiquetados como la API key de otro."""
    _entrar(client)
    antes = _bundle(db_session, tenant)

    for name in ("claude", "codex"):
        r = client.put("/v1/provider", json={"name": name, "mode": "api_key", "secret": secreto})
        assert r.status_code == 400, r.text
    estado = client.get("/v1/provider").json()
    assert estado["name"] == "chatgpt" and estado["connected"] is True
    assert _bundle(db_session, tenant)["refresh_token"] == antes["refresh_token"]
    assert falso.visto["revoke"] == []


def test_guardar_otra_ia_cierra_la_sesion_de_chatgpt(falso, client, db_session, tenant):
    _entrar(client)
    bundle = _bundle(db_session, tenant)

    r = client.put("/v1/provider", json={"name": "codex", "mode": "api_key", "secret": "sk-mia"})
    assert r.json() == {"name": "codex", "mode": "api_key", "connected": True}
    assert falso.visto["revoke"][-1]["token"] == bundle["refresh_token"]
    assert chatgpt_auth._ultimo == {}
    from aiuda_core.connectors import credentials

    db_session.expire_all()
    fila = credentials.read_stored(db_session, tenant.id, "ia")
    assert (fila["name"], fila["mode"], fila["secret"]) == ("codex", "api_key", "sk-mia")
    # El registro de la app se conserva, igual que al desconectar.
    assert client.get("/v1/provider").json()["chatgpt"]["registrada"] is True


def test_guardar_otra_ia_sin_poder_avisar_a_openai_guarda_igual_y_lo_dice(
    falso, client, monkeypatch
):
    import aiuda_core.engine.cli_runner as cli

    monkeypatch.setattr(cli, "detectar", lambda nombre: "/usr/local/bin/claude")
    _entrar(client)
    falso.modo["revoke"] = "caido"
    r = client.put("/v1/provider", json={"name": "claude_cli", "mode": "cli", "secret": ""}).json()
    assert r["connected"] is True and r["name"] == "claude_cli"
    assert "no pudimos confirmar la desconexión con OpenAI" in r["aviso"]
    assert chatgpt_auth._ultimo == {}


# --- el chat y el log --------------------------------------------------------
def _ayudante(client) -> str:
    return client.post("/v1/ayudantes", json={"name": "Ayudante de prueba"}).json()["id"]


def test_el_chat_contesta_con_el_plan_y_cuenta_el_uso(falso, client):
    _entrar(client)
    r = client.post(f"/v1/ayudantes/{_ayudante(client)}/chat", json={"message": "hola"})
    assert r.json() == {"reply": "Hola desde el plan"}
    por_modelo = client.get("/v1/usage").json()["by_model"]
    assert por_modelo == [
        {"model": "chatgpt-plan", "input_tokens": 11, "output_tokens": 4, "cost_usd": 0.0}
    ]


def test_en_el_chat_el_limite_del_plan_se_dice_tal_cual(falso, client):
    _entrar(client)
    falso.modo["responses"] = "limite"
    r = client.post(f"/v1/ayudantes/{_ayudante(client)}/chat", json={"message": "hola"})
    assert r.status_code == 502
    assert "límite de uso de tu plan de ChatGPT" in r.json()["detail"]


def test_sesion_vencida_a_media_platica_se_dice_y_borra_los_tokens(
    falso, client, db_session, tenant
):
    """Que eso sobreviva a la reversión de la petición se prueba en core, con una base
    en disco (aquí la sesión de prueba es compartida y nada se revierte)."""
    _entrar(client)
    aid = _ayudante(client)
    db_session.commit()
    falso.vencer_access_tokens()
    falso.modo["refresh"] = "invalid_grant"

    r = client.post(f"/v1/ayudantes/{aid}/chat", json={"message": "hola"})
    assert r.status_code == 502
    assert r.json()["detail"] == (
        "Tu conexión con ChatGPT venció. Vuelve a entrar con ChatGPT en Tu IA."
    )
    chatgpt_auth._ultimo.clear()
    queda = _bundle(db_session, tenant)
    assert queda["access_token"] == "" and queda["client_id"].startswith("oaiapp_falso_")


def test_el_log_de_accesos_no_guarda_el_codigo_ni_el_state_del_regreso():
    import logging

    from aiuda_server.api.main import _RegresoSinQuery

    def linea(ruta: str) -> str:
        rec = logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1", "GET", ruta, "1.1", 200), None,
        )
        assert _RegresoSinQuery().filter(rec) is True
        return rec.getMessage()

    assert "secreto" not in linea("/auth/callback?code=secreto&state=secreto")
    assert "/auth/callback?…" in linea("/auth/callback?code=secreto&state=secreto")
    assert "page=2" in linea("/v1/invoices?page=2")
