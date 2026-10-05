"""Entrar con ChatGPT: el protocolo y la renovación, contra el servidor FALSO.

El falso (fake_chatgpt.py) sigue la documentación pública de OpenAI. Que esto pase
prueba que aiuda sigue esa documentación; no prueba cómo se porta el backend real.
"""

import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fake_chatgpt import FakeChatGPT
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aiuda_core.config import settings
from aiuda_core.connectors import credentials
from aiuda_core.engine import chatgpt_auth
from aiuda_core.engine.codex import CodexError, CodexRunner
from aiuda_core.engine.codex import test_codex as probar_codex
from aiuda_core.engine.provider import credential_from_config, resolve_credential
from aiuda_core.engine.runner import make_runner
from aiuda_core.models import Base, Tenant

pytest.importorskip("cryptography")

REDIRECT = "http://127.0.0.1:4999/auth/callback"
HOST = "urn:uuid:11111111-2222-4333-8444-555555555555"


@pytest.fixture(scope="module")
def _servidor():
    with FakeChatGPT() as f:
        yield f


@pytest.fixture()
def falso(_servidor, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_issuer", _servidor.base)
    monkeypatch.setattr(settings, "openai_base", f"{_servidor.base}/v1")
    original = dict(_servidor.modo)
    for lista in ("authorize", "token", "revoke", "responses"):
        _servidor.visto[lista].clear()
    chatgpt_auth._ultimo.clear()
    yield _servidor
    _servidor.modo.clear()
    _servidor.modo.update(original)
    chatgpt_auth._ultimo.clear()


def _entrar(falso, client_id=None):
    """Recorre el navegador a mano: authorize -> regreso. Devuelve (intento, params)."""
    intento = chatgpt_auth.nuevo_intento(REDIRECT, host_id=HOST, client_id=client_id)
    resp = httpx.get(intento.url, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    vuelta = {k: v[0] for k, v in parse_qs(urlsplit(resp.headers["location"]).query).items()}
    return intento, vuelta


def _conectar(falso, session, tenant) -> dict:
    """Deja una conexión de ChatGPT guardada, como la deja el regreso del navegador."""
    intento, vuelta = _entrar(falso)
    tok = chatgpt_auth.canjear(intento, vuelta["code"], vuelta["client_id"])
    datos = chatgpt_auth.verificar_id_token(
        tok["id_token"], client_id=vuelta["client_id"], nonce=intento.nonce
    )
    bundle = chatgpt_auth.armar_bundle(
        tok, previo={"client_id": vuelta["client_id"], "subject": datos["sub"]}
    )
    bundle["model"] = chatgpt_auth.elegir_modelo(bundle["access_token"])
    credentials.set_credential(session, tenant.id, "ia", chatgpt_auth.valores(bundle))
    chatgpt_auth.recordar(tenant.id, bundle)
    session.commit()
    return bundle


def _guardado(session, tenant) -> dict:
    session.expire_all()
    return chatgpt_auth.parse_secret(credentials.read_stored(session, tenant.id, "ia")["secret"])


def _envejecer(session, tenant, bundle, **cambios) -> dict:
    """Reescribe el bundle guardado (p. ej. como si ya estuviera por vencer)."""
    viejo = {**bundle, **cambios}
    credentials.refresh_secret(session, tenant.id, "ia", chatgpt_auth.valores(viejo))
    chatgpt_auth.recordar(tenant.id, viejo)
    session.commit()
    return viejo


# --- inicio ------------------------------------------------------------------
def test_el_registro_se_presenta_como_aiuda_y_no_como_otro(falso):
    intento = chatgpt_auth.nuevo_intento(REDIRECT, host_id=HOST)
    q = {k: v[0] for k, v in parse_qs(urlsplit(intento.url).query).items()}

    assert intento.url.startswith(f"{falso.base}/api/accounts/authorize?")
    assert q["client_id"] == "dynamic_agent_client"
    assert q["agent_name_hint"] == "aiuda"
    assert q["ext_agent_host_id"] == HOST
    assert q["redirect_uri"] == REDIRECT
    assert q["resource"] == "https://api.openai.com/v1"
    assert q["code_challenge_method"] == "S256" and q["code_challenge"] != intento.verifier
    assert set(q["scope"].split()) == {
        "openid", "profile", "email", "offline_access", "resource.invoke",
        "chatgpt.tokens.use.direct",
    }
    # Ningún token viaja en la URL del navegador.
    assert "id_token_hint" not in q


def test_volver_a_entrar_usa_el_client_id_emitido_y_ya_no_manda_el_nombre(falso):
    intento = chatgpt_auth.nuevo_intento(
        REDIRECT, host_id=HOST, client_id="oaiapp_mio", email="dueno@ejemplo.mx"
    )
    q = {k: v[0] for k, v in parse_qs(urlsplit(intento.url).query).items()}
    assert q["client_id"] == "oaiapp_mio"
    assert "agent_name_hint" not in q
    assert q["login_hint"] == "dueno@ejemplo.mx"


def test_cada_intento_trae_valores_frescos(falso):
    a = chatgpt_auth.nuevo_intento(REDIRECT, host_id=HOST)
    b = chatgpt_auth.nuevo_intento(REDIRECT, host_id=HOST)
    assert len({a.state, a.nonce, a.verifier, b.state, b.nonce, b.verifier}) == 6


# --- canje e identidad -------------------------------------------------------
def test_canje_valida_identidad_y_escoge_un_modelo_de_la_cuenta(falso):
    intento, vuelta = _entrar(falso)
    assert vuelta["client_id"].startswith("oaiapp_falso_")

    tok = chatgpt_auth.canjear(intento, vuelta["code"], vuelta["client_id"])
    datos = chatgpt_auth.verificar_id_token(
        tok["id_token"], client_id=vuelta["client_id"], nonce=intento.nonce
    )
    assert datos["sub"] == "user-falso-1" and datos["email"] == "dueno@ejemplo.mx"

    # El canje fue de cliente público: sin secreto, con el client_id EMITIDO.
    form = falso.visto["token"][-1]
    assert "client_secret" not in form and form["client_id"] == vuelta["client_id"]
    assert form["redirect_uri"] == REDIRECT

    # El modelo de la configuración no está en la lista de esta cuenta: va el primero.
    assert chatgpt_auth.elegir_modelo(tok["access_token"]) == "gpt-falso-grande"


def test_prefiere_el_modelo_de_la_configuracion_si_la_cuenta_lo_tiene(falso, monkeypatch):
    intento, vuelta = _entrar(falso)
    tok = chatgpt_auth.canjear(intento, vuelta["code"], vuelta["client_id"])
    monkeypatch.setattr(settings, "model_codex", "gpt-falso-chico")
    assert chatgpt_auth.elegir_modelo(tok["access_token"]) == "gpt-falso-chico"


def test_un_codigo_ajeno_al_verificador_no_se_canjea(falso):
    intento, vuelta = _entrar(falso)
    otro = chatgpt_auth.nuevo_intento(REDIRECT, host_id=HOST)
    with pytest.raises(chatgpt_auth.ChatGPTAuthError):
        chatgpt_auth.canjear(otro, vuelta["code"], vuelta["client_id"])


@pytest.mark.parametrize(
    "modo",
    [{"firma_mala": True}, {"nonce": "de-otro-intento"}, {"aud": "oaiapp_de_otro"}],
)
def test_id_token_que_no_cuadra_se_rechaza(falso, modo):
    falso.modo.update(modo)
    intento, vuelta = _entrar(falso)
    tok = chatgpt_auth.canjear(intento, vuelta["code"], vuelta["client_id"])
    with pytest.raises(chatgpt_auth.ChatGPTAuthError, match="no se pudo comprobar"):
        chatgpt_auth.verificar_id_token(
            tok["id_token"], client_id=vuelta["client_id"], nonce=intento.nonce
        )


def test_id_token_vencido_de_otro_emisor_o_sin_firma_se_rechaza(falso):
    base = {"iss": falso.base, "aud": "c1", "sub": "u", "nonce": "n", "exp": time.time() + 60}
    ok = chatgpt_auth.verificar_id_token(falso.jwt(base), client_id="c1", nonce="n")
    assert ok["sub"] == "u"
    # `aud` también puede venir como lista.
    chatgpt_auth.verificar_id_token(falso.jwt({**base, "aud": ["x", "c1"]}), client_id="c1", nonce="n")

    for malo in (
        {**base, "exp": time.time() - 5},
        {**base, "iss": "https://otro.example"},
        {**base, "sub": ""},
    ):
        with pytest.raises(chatgpt_auth.ChatGPTAuthError):
            chatgpt_auth.verificar_id_token(falso.jwt(malo), client_id="c1", nonce="n")

    # alg=none: un token "firmado" con nada no pasa.
    sin_firma = (
        chatgpt_auth._b64(json.dumps({"alg": "none", "kid": falso.kid}).encode())
        + "."
        + chatgpt_auth._b64(json.dumps(base).encode())
        + "."
    )
    with pytest.raises(chatgpt_auth.ChatGPTAuthError):
        chatgpt_auth.verificar_id_token(sin_firma, client_id="c1", nonce="n")


# --- la credencial y el runner -----------------------------------------------
def test_chatgpt_no_se_acepta_desde_el_config_en_claro():
    cfg = {"provider": {"name": "chatgpt", "mode": "oauth", "secret": "{}"}}
    assert credential_from_config(cfg) is None


def test_un_turno_va_a_la_api_publica_con_el_token_y_sin_headers_ajenos(falso, session, tenant):
    bundle = _conectar(falso, session, tenant)
    usos: list = []
    cred = resolve_credential(session=session, tenant_id=tenant.id)
    assert (cred.name, cred.mode) == ("chatgpt", "oauth")

    runner = make_runner(cred, usage_callback=lambda *a: usos.append(a))
    assert isinstance(runner, CodexRunner) and runner.mode == "oauth"
    assert runner.model_for("triage") == runner.model_for("redaccion") == "gpt-falso-grande"
    assert runner.complete(system="Eres breve.", user="hola", task="redactar") == "Hola desde el plan"

    llamada = falso.visto["responses"][-1]
    assert llamada["headers"]["authorization"] == f"Bearer {bundle['access_token']}"
    for ajeno in ("originator", "chatgpt-account-id", "openai-beta", "session_id"):
        assert ajeno not in llamada["headers"]
    assert "codex" not in llamada["headers"].get("user-agent", "").lower()
    body = llamada["body"]
    assert body["store"] is False and body["stream"] is True
    assert body["instructions"] == "Eres breve." and isinstance(body["input"], list)
    assert "max_output_tokens" not in body

    # El uso se cuenta con la etiqueta del plan (sin precio por token).
    assert usos == [("chatgpt-plan", "redactar", 11, 4)]
    # Con el token vigente no se renovó nada.
    assert [f["grant_type"] for f in falso.visto["token"]] == ["authorization_code"]


def test_por_vencer_se_renueva_antes_de_llamar_y_el_token_rotado_queda_guardado(
    falso, session, tenant
):
    bundle = _envejecer(
        session, tenant, _conectar(falso, session, tenant), expires_at=int(time.time()) + 60
    )
    runner = make_runner(resolve_credential(session=session, tenant_id=tenant.id))
    assert runner.complete(system="s", user="u", task="t") == "Hola desde el plan"

    nuevo = _guardado(session, tenant)
    assert nuevo["refresh_token"] != bundle["refresh_token"]
    assert nuevo["access_token"] != bundle["access_token"]
    assert nuevo["client_id"] == bundle["client_id"] and nuevo["model"] == bundle["model"]
    assert nuevo["id_token"] == bundle["id_token"]  # la renovación no lo repite: se conserva
    assert falso.visto["responses"][-1]["headers"]["authorization"] == (
        f"Bearer {nuevo['access_token']}"
    )
    # La renovación no manda `scope` (así se conserva el permiso) ni secreto.
    renovacion = falso.visto["token"][-1]
    assert renovacion["grant_type"] == "refresh_token" and "scope" not in renovacion


def test_si_openai_dice_que_aun_no_toca_renovar_se_usa_el_token_que_hay(falso, session, tenant):
    bundle = _envejecer(
        session,
        tenant,
        _conectar(falso, session, tenant),
        expires_at=int(time.time()) + 60,
        earliest_refresh_at=int(time.time()) + 600,
    )
    assert chatgpt_auth.token_vigente(session, tenant.id) == bundle["access_token"]
    assert [f["grant_type"] for f in falso.visto["token"]] == ["authorization_code"]


def test_un_401_renueva_una_vez_y_reintenta_una_vez(falso, session, tenant):
    bundle = _conectar(falso, session, tenant)
    falso.vencer_access_tokens()  # el reloj de aiuda dice que sigue vigente; OpenAI no

    runner = make_runner(resolve_credential(session=session, tenant_id=tenant.id))
    assert runner.complete(system="s", user="u", task="t") == "Hola desde el plan"

    assert len(falso.visto["responses"]) == 2
    assert [f["grant_type"] for f in falso.visto["token"]].count("refresh_token") == 1
    assert _guardado(session, tenant)["refresh_token"] != bundle["refresh_token"]


def test_si_tras_renovar_sigue_el_401_se_dice_y_no_se_insiste(falso, session, tenant):
    _conectar(falso, session, tenant)
    falso.modo["responses"] = "401"

    runner = make_runner(resolve_credential(session=session, tenant_id=tenant.id))
    with pytest.raises(CodexError, match="Vuelve a entrar con ChatGPT") as exc:
        runner.complete(system="s", user="u", task="t")
    assert exc.value.code == "auth"
    assert "API key" not in str(exc.value)
    assert len(falso.visto["responses"]) == 2  # el intento y UN reintento


@pytest.mark.parametrize("codigo", ["invalid_grant", "refresh_token_reused", "refresh_token_expired"])
def test_renovacion_rechazada_borra_los_tokens_conserva_el_registro_y_pide_volver_a_entrar(
    falso, session, tenant, codigo
):
    bundle = _envejecer(
        session, tenant, _conectar(falso, session, tenant), expires_at=int(time.time()) - 5
    )
    falso.modo["refresh"] = codigo

    runner = make_runner(resolve_credential(session=session, tenant_id=tenant.id))
    with pytest.raises(CodexError, match="Tu conexión con ChatGPT venció. Vuelve a entrar"):
        runner.complete(system="s", user="u", task="t")

    queda = _guardado(session, tenant)
    assert queda["access_token"] == queda["refresh_token"] == queda["id_token"] == ""
    assert queda["client_id"] == bundle["client_id"] and queda["subject"] == "user-falso-1"
    assert falso.visto["responses"] == []  # nada salió hacia la API con un token muerto

    # Y sigue diciéndolo: no cae en silencio a la llave del entorno ni a otro cobro.
    falso.modo["refresh"] = "ok"
    cred = resolve_credential(session=session, tenant_id=tenant.id)
    assert cred is not None and cred.name == "chatgpt"
    v = probar_codex(make_runner(cred))
    assert v["ok"] is False and v["code"] == "auth" and "Vuelve a entrar" in v["error"]


def test_una_caida_al_renovar_no_borra_la_conexion(falso, session, tenant):
    bundle = _envejecer(
        session, tenant, _conectar(falso, session, tenant), expires_at=int(time.time()) + 60
    )
    falso.modo["refresh"] = "caido"

    # Le quedan 60 s: se usa lo que hay.
    assert chatgpt_auth.token_vigente(session, tenant.id) == bundle["access_token"]
    assert _guardado(session, tenant)["refresh_token"] == bundle["refresh_token"]

    # Ya vencido y sin poder renovar: se dice, y la conexión sigue guardada.
    _envejecer(session, tenant, bundle, expires_at=int(time.time()) - 5)
    with pytest.raises(chatgpt_auth.ChatGPTAuthError, match="No se pudo renovar") as exc:
        chatgpt_auth.token_vigente(session, tenant.id)
    assert not isinstance(exc.value, chatgpt_auth.SesionVencida)
    assert _guardado(session, tenant)["refresh_token"] == bundle["refresh_token"]


@pytest.mark.parametrize(
    ("modo", "code", "frase"),
    [
        ("limite", "limite", "límite de uso de tu plan de ChatGPT"),
        ("no_elegible", "no_elegible", "no puede usar su plan en otras aplicaciones"),
        ("detail_403", "permiso", "no permitió usar tu plan"),
        ("cortado", "status", "no terminó la respuesta"),
    ],
)
def test_los_rechazos_del_plan_se_dicen_en_espanol_y_sin_hablar_de_llaves(
    falso, session, tenant, modo, code, frase
):
    _conectar(falso, session, tenant)
    falso.modo["responses"] = modo
    usos: list = []

    runner = make_runner(
        resolve_credential(session=session, tenant_id=tenant.id),
        usage_callback=lambda *a: usos.append(a),
    )
    with pytest.raises(CodexError, match=frase) as exc:
        runner.complete(system="s", user="u", task="t")
    assert exc.value.code == code
    assert "API key" not in str(exc.value) and "key" not in str(exc.value).lower()
    assert usos == []
    assert len(falso.visto["responses"]) == 1  # no se reintenta un rechazo que no es 401
    assert probar_codex(runner)["code"] == code


def test_revocar_avisa_a_openai_y_dice_la_verdad_si_no_pudo(falso, session, tenant):
    bundle = _conectar(falso, session, tenant)
    assert chatgpt_auth.revocar(bundle) is True
    form = falso.visto["revoke"][-1]
    assert form == {
        "token": bundle["refresh_token"],
        "token_type_hint": "refresh_token",
        "client_id": bundle["client_id"],
    }
    falso.modo["revoke"] = "caido"
    assert chatgpt_auth.revocar(bundle) is False
    assert chatgpt_auth.revocar({**bundle, "refresh_token": ""}) is False


# --- que el token rotado no se pierda ----------------------------------------
@pytest.fixture()
def base_en_disco(tmp_path):
    """Una base en archivo, como la de verdad: varias conexiones y un solo escritor."""
    engine = create_engine(f"sqlite:///{tmp_path / 'aiuda.db'}", connect_args={"timeout": 5})
    Base.metadata.create_all(engine)
    hacer = sessionmaker(bind=engine, expire_on_commit=False)
    s = hacer()
    t = Tenant(name="Negocio", owner_phone="", evolution_instance="x", config={})
    s.add(t)
    s.commit()
    yield hacer, s, t
    s.close()
    engine.dispose()


def test_el_token_renovado_sobrevive_a_que_la_corrida_que_lo_pidio_se_revierta(
    falso, base_en_disco
):
    hacer, s, t = base_en_disco
    bundle = _envejecer(s, t, _conectar(falso, s, t), expires_at=int(time.time()) + 60)

    corrida = hacer()
    nuevo = chatgpt_auth.token_vigente(corrida, t.id)
    corrida.add(Tenant(name="basura de la corrida", owner_phone="", evolution_instance="y"))
    corrida.flush()
    corrida.rollback()  # a la corrida le fue mal DESPUÉS de renovar
    corrida.close()

    # Como si la app se hubiera cerrado: sin memoria, solo lo que quedó en disco.
    chatgpt_auth._ultimo.clear()
    queda = _guardado(hacer(), t)
    assert queda["access_token"] == nuevo and queda["refresh_token"] != bundle["refresh_token"]


def test_si_quien_renueva_ya_estaba_escribiendo_el_token_se_repone_al_revertir(
    falso, base_en_disco
):
    """El caso de todos los días: la corrida ya anotó algo (su bitácora) antes de
    llamar a la IA, renueva, y luego falla. SQLite no deja escribir aparte mientras
    ella tiene la base, así que se repone en cuanto la suelta."""
    hacer, s, t = base_en_disco
    bundle = _envejecer(s, t, _conectar(falso, s, t), expires_at=int(time.time()) + 60)

    corrida = hacer()
    corrida.add(Tenant(name="a media corrida", owner_phone="", evolution_instance="z"))
    corrida.flush()  # ya tiene el candado de escritura de SQLite
    nuevo = chatgpt_auth.token_vigente(corrida, t.id)
    corrida.rollback()
    corrida.close()

    chatgpt_auth._ultimo.clear()  # como si la app se cerrara justo después
    queda = _guardado(hacer(), t)
    assert queda["access_token"] == nuevo and queda["refresh_token"] != bundle["refresh_token"]


def test_lo_que_solo_quedo_en_memoria_se_escribe_en_la_siguiente_llamada(falso, base_en_disco):
    hacer, s, t = base_en_disco
    bundle = _conectar(falso, s, t)
    # Un token más nuevo que el de la fila, que no alcanzó a escribirse.
    chatgpt_auth.recordar(t.id, {**bundle, "access_token": "at_nuevo", "guardado": time.time()})

    otra = hacer()
    assert chatgpt_auth.token_vigente(otra, t.id) == "at_nuevo"
    otra.close()
    chatgpt_auth._ultimo.clear()
    assert _guardado(hacer(), t)["access_token"] == "at_nuevo"
    assert [f["grant_type"] for f in falso.visto["token"]] == ["authorization_code"]


def test_dos_hilos_a_la_vez_renuevan_una_sola_vez(falso, base_en_disco):
    hacer, s, t = base_en_disco
    _envejecer(s, t, _conectar(falso, s, t), expires_at=int(time.time()) + 60)
    tokens: list = []
    errores: list = []
    salida = threading.Barrier(4)

    def corrida():
        db = hacer()
        try:
            salida.wait()
            tokens.append(chatgpt_auth.token_vigente(db, t.id))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            errores.append(exc)
        finally:
            db.close()

    hilos = [threading.Thread(target=corrida) for _ in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert errores == []
    assert len(set(tokens)) == 1
    # Un token de renovación usado dos veces sería `refresh_token_reused` y adiós sesión.
    assert [f["grant_type"] for f in falso.visto["token"]].count("refresh_token") == 1


def test_una_renovacion_en_curso_no_le_escribe_encima_a_la_ia_que_el_dueno_acaba_de_guardar(
    falso, base_en_disco, monkeypatch
):
    """Mientras se renueva (la llamada a OpenAI tarda), el dueño cambia de IA en Tu IA.
    Lo que guardó manda: el token renovado no regresa la fila a ChatGPT."""
    hacer, s, t = base_en_disco
    _envejecer(s, t, _conectar(falso, s, t), expires_at=int(time.time()) + 60)
    renovar = chatgpt_auth.renovar

    def renovar_lento(bundle):
        nuevo = renovar(bundle)
        with hacer() as otra:  # lo que hace PUT /v1/provider en otra petición
            credentials.set_credential(
                otra, t.id, "ia", {"name": "codex", "mode": "api_key", "secret": "sk-del-dueno"}
            )
            otra.commit()
        return nuevo

    monkeypatch.setattr(chatgpt_auth, "renovar", renovar_lento)
    corrida = hacer()
    chatgpt_auth.token_vigente(corrida, t.id)
    corrida.close()

    fila = credentials.read_stored(hacer(), t.id, "ia")
    assert (fila["name"], fila["mode"], fila["secret"]) == ("codex", "api_key", "sk-del-dueno")
    # Y nada en memoria que la reviva en la siguiente llamada.
    assert t.id not in chatgpt_auth._ultimo


def test_al_abrir_un_trabajo_el_token_se_renueva_y_queda_en_disco_antes_de_escribir(
    falso, base_en_disco
):
    """Si la app se cierra a media corrida, lo que no se confirmó se pierde. El token
    recién rotado no puede estar ahí: se renueva al abrir el run, antes de su primera
    escritura, y otra conexión ya lo ve en disco con el run todavía abierto."""
    from aiuda_core.observabilidad import abrir_run

    hacer, s, t = base_en_disco
    # Le quedan 10 minutos: no vence todavía, pero sí durante un trabajo largo.
    bundle = _envejecer(s, t, _conectar(falso, s, t), expires_at=int(time.time()) + 600)

    corrida = hacer()
    with abrir_run(corrida, corrida.get(Tenant, t.id), disparo="corrida"):
        en_disco = _guardado(hacer(), t)
        assert en_disco["refresh_token"] != bundle["refresh_token"]
        # La llamada de verdad ya no renueva dentro de la transacción del trabajo.
        assert chatgpt_auth.token_vigente(corrida, t.id) == en_disco["access_token"]
    # La app "muere" sin confirmar nada de la corrida y sin memoria.
    corrida.connection().connection.dbapi_connection.rollback()
    corrida.close()
    chatgpt_auth._ultimo.clear()

    assert _guardado(hacer(), t)["refresh_token"] == en_disco["refresh_token"]
    assert [f["grant_type"] for f in falso.visto["token"]].count("refresh_token") == 1


def test_adelantar_la_renovacion_no_hace_nada_si_la_ia_no_es_chatgpt(falso, session, tenant):
    credentials.set_credential(
        session, tenant.id, "ia", {"name": "codex", "mode": "api_key", "secret": "sk-x"}
    )
    session.commit()
    chatgpt_auth.adelantar_renovacion(session, tenant.id)
    assert falso.visto["token"] == []
    assert credentials.read_stored(session, tenant.id, "ia")["secret"] == "sk-x"
