"""Emparejar el teléfono del dueño, y a quien él deje entrar.

Lo que se cuida aquí es lo que puede salir caro: que el código del QR no sirva
dos veces ni después de su rato, que un invitado no pueda ascenderse solo, y que
revocar un aparato lo deje afuera de inmediato.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.models import Base, Dispositivo, Tenant
from aiuda_server.api import dispositivos as api
from aiuda_server.api.main import app, get_db

pytest.importorskip("cryptography")  # el certificado de la red local


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    # El guardián de la sesión revisa el token del aparato ANTES de que exista
    # una petición con dependencias, así que abre su propia sesión. Aquí se le
    # apunta a la misma base de prueba; si no, en el test hablaría con la real.
    from aiuda_core import db as core_db

    monkeypatch.setattr(core_db, "get_sessionmaker", lambda: SessionLocal)
    session = SessionLocal()
    session.add(Tenant(name="Mi negocio", owner_phone="", evolution_instance="x"))
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session, monkeypatch, tmp_path):
    # El certificado se escribe en la carpeta de datos: aquí, una temporal.
    from aiuda_core import db as core_db

    monkeypatch.setattr(core_db, "default_data_dir", lambda: tmp_path)

    def _db():
        # Igual que en producción: cada petición cierra con commit. Importa aquí
        # porque el guardián de la siguiente petición abre SU propia sesión, y
        # sin commit no vería el aparato que se acaba de emparejar.
        yield db_session
        db_session.commit()

    app.dependency_overrides[get_db] = _db
    api._olvidar_invitacion()
    yield TestClient(app)
    app.dependency_overrides.clear()
    api._olvidar_invitacion()


@pytest.fixture()
def en_la_red(monkeypatch):
    """Como si la computadora ya estuviera escuchando en la red del changarro."""
    from aiuda_server import red_local

    monkeypatch.setattr(red_local, "direccion_lan", lambda: "192.168.1.50")
    app.state.puerto_red_local = 4748


def invitar(client, **cuerpo) -> dict:
    r = client.post("/v1/dispositivos/invitacion", json=cuerpo or {})
    assert r.status_code == 200, r.text
    return r.json()


# --- El QR ------------------------------------------------------------------


def test_sin_red_prendida_no_hay_qr_que_ensenar(client):
    """Un QR con una dirección que nadie puede alcanzar es peor que ninguno."""
    from aiuda_server import red_local

    app.state.puerto_red_local = None
    r = client.post("/v1/dispositivos/invitacion", json={})
    assert r.status_code == 409
    assert "red local" in r.json()["detail"]
    assert red_local  # el módulo se importa sin tronar aunque no haya red


def test_el_qr_lleva_la_huella_del_certificado(client, en_la_red):
    """Es lo que hace que el teléfono acepte a ESTA computadora y a ninguna otra."""
    qr = invitar(client)["qr"]
    assert qr["host"] == "192.168.1.50"
    assert qr["puerto"] == 4748
    assert len(qr["huella"]) == 64  # SHA-256 en hex
    assert qr["codigo"]


# --- Emparejar --------------------------------------------------------------


def test_el_telefono_queda_dentro_y_el_token_sirve(client, en_la_red, db_session):
    codigo = invitar(client)["qr"]["codigo"]
    r = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "iPhone de Ana"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["dispositivo"]["papel"] == "invitado"

    # Del token solo queda su huella: la base no lo guarda en claro.
    guardado = db_session.scalars(select(Dispositivo)).one()
    assert token not in guardado.token_hash
    assert guardado.token_hash == api.huella_token(token)

    yo = client.get("/v1/dispositivos/yo", headers={"Authorization": f"Bearer {token}"})
    assert yo.status_code == 200
    assert yo.json()["dispositivo"]["nombre"] == "iPhone de Ana"


def test_el_codigo_sirve_una_sola_vez(client, en_la_red):
    codigo = invitar(client)["qr"]["codigo"]
    assert client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "uno"}).status_code == 200
    segundo = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "dos"})
    assert segundo.status_code == 403


def test_el_codigo_caduca(client, en_la_red, monkeypatch):
    codigo = invitar(client)["qr"]["codigo"]
    viejo = api._invitacion
    monkeypatch.setattr(api, "_invitacion", type(viejo)(**{**viejo.__dict__, "caduca": viejo.caduca - timedelta(minutes=10)}))
    r = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "tarde"})
    assert r.status_code == 403


def test_un_codigo_inventado_no_entra(client, en_la_red):
    invitar(client)
    r = client.post("/v1/emparejar", json={"codigo": "no-soy-el-bueno", "nombre": "x"})
    assert r.status_code == 403


def test_cancelar_el_qr_lo_mata_de_inmediato(client, en_la_red):
    codigo = invitar(client)["qr"]["codigo"]
    assert client.delete("/v1/dispositivos/invitacion").status_code == 200
    r = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "x"})
    assert r.status_code == 403


# --- Papeles ----------------------------------------------------------------


def emparejar_como(client, papel="invitado", tope=None, nombre="aparato") -> str:
    cuerpo = {"papel": papel}
    if tope is not None:
        cuerpo["tope_aprobacion"] = tope
    codigo = invitar(client, **cuerpo)["qr"]["codigo"]
    r = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": nombre})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_un_invitado_no_puede_meter_a_nadie_mas(client, en_la_red):
    token = emparejar_como(client, "invitado")
    r = client.post(
        "/v1/dispositivos/invitacion", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_un_invitado_no_se_puede_ascender_solo(client, en_la_red, db_session):
    token = emparejar_como(client, "invitado")
    suyo = db_session.scalars(select(Dispositivo)).one()
    r = client.patch(
        f"/v1/dispositivos/{suyo.id}",
        json={"papel": "dueno"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    db_session.refresh(suyo)
    assert suyo.papel == "invitado"


def test_un_invitado_no_prende_ni_apaga_la_red(client, en_la_red):
    token = emparejar_como(client, "invitado")
    r = client.put(
        "/v1/red-local", json={"prendida": False}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_el_tope_decide_que_puede_aprobar_un_invitado():
    dueno = Dispositivo(tenant_id="t", nombre="mero mero", papel="dueno", token_hash="a")
    assert dueno.puede_aprobar(999_999)

    sin_tope = Dispositivo(tenant_id="t", nombre="ve nomás", papel="invitado", token_hash="b")
    assert not sin_tope.puede_aprobar(1)  # sin tope no aprueba ni lo chico

    con_tope = Dispositivo(
        tenant_id="t", nombre="hasta 5 mil", papel="invitado",
        token_hash="c", tope_aprobacion=5000,
    )
    assert con_tope.puede_aprobar(5000)
    assert not con_tope.puede_aprobar(5000.01)

    con_tope.revocado_en = api._ahora()
    assert not con_tope.puede_aprobar(1)  # revocado no aprueba nada


# --- Revocar ----------------------------------------------------------------


def test_revocar_deja_al_aparato_afuera_de_inmediato(client, en_la_red, db_session):
    token = emparejar_como(client, "invitado")
    aparato = db_session.scalars(select(Dispositivo)).one()

    assert client.post(f"/v1/dispositivos/{aparato.id}/revocar").status_code == 200
    r = client.get("/v1/dispositivos/yo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_revocar_no_borra_la_fila(client, en_la_red, db_session):
    """El dueño merece ver que ese teléfono estuvo dentro y cuándo salió."""
    emparejar_como(client, "invitado", nombre="el que se fue")
    aparato = db_session.scalars(select(Dispositivo)).one()
    client.post(f"/v1/dispositivos/{aparato.id}/revocar")

    lista = client.get("/v1/dispositivos").json()["dispositivos"]
    assert len(lista) == 1
    assert lista[0]["nombre"] == "el que se fue"
    assert lista[0]["activo"] is False
    assert lista[0]["revocado_en"]


def test_nadie_se_saca_a_si_mismo_desde_su_propio_aparato(client, en_la_red, db_session):
    token = emparejar_como(client, "dueno")
    suyo = db_session.scalars(select(Dispositivo)).one()
    r = client.post(
        f"/v1/dispositivos/{suyo.id}/revocar", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 400


# --- El candado de la sesión ------------------------------------------------


def test_la_puerta_de_la_red_no_se_afloja_con_no_token(client, en_la_red, monkeypatch, db_session):
    """`--no-token` deja la consola sin candado a propósito: es esta computadora
    hablando consigo misma. Lo que llega de la red es otra cosa y siempre tiene
    que traer el token de su aparato."""
    from aiuda_server.red_local import _YaArrancada  # el envoltorio real de esa puerta

    token = emparejar_como(client, "invitado")
    monkeypatch.setattr(settings, "session_token", "")  # como --no-token

    # Por la consola, sin candado, pasa: es 127.0.0.1 hablando consigo mismo.
    assert client.get("/v1/cartera").status_code == 200

    # Por la red, no.
    red = TestClient(_YaArrancada(app))
    assert red.get("/v1/cartera").status_code == 401
    con_aparato = red.get("/v1/cartera", headers={"Authorization": f"Bearer {token}"})
    assert con_aparato.status_code == 200

    # Y el aparato revocado tampoco, aunque conserve su token.
    aparato = db_session.scalars(select(Dispositivo)).one()
    client.post(f"/v1/dispositivos/{aparato.id}/revocar")
    assert (
        red.get("/v1/cartera", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_emparejar_es_lo_unico_que_pasa_sin_la_llave_de_la_sesion(client, en_la_red, monkeypatch):
    """El teléfono todavía no tiene token: por eso /v1/emparejar se contesta sin
    él. Todo lo demás sigue cerrado."""
    codigo = invitar(client)["qr"]["codigo"]
    monkeypatch.setattr(settings, "session_token", "la-de-la-consola")

    assert client.get("/v1/cartera").status_code == 401
    r = client.post("/v1/emparejar", json={"codigo": codigo, "nombre": "iPhone"})
    assert r.status_code == 200
    token = r.json()["token"]

    # Y ya con su token, el teléfono sí entra a lo demás.
    assert client.get(
        "/v1/dispositivos/yo", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200


# --- Lo que un invitado NO puede hacer --------------------------------------


def por_la_red():
    """Un cliente que entra por la puerta de la red, como el teléfono."""
    from aiuda_server.red_local import _YaArrancada

    return TestClient(_YaArrancada(app))


def test_un_invitado_no_toca_como_esta_armado_el_negocio(client, en_la_red):
    """El hueco grande: un aparato emparejado entraba a TODO el API. Con eso,
    quien tuviera un token de invitado podía apuntar el proveedor de IA a su
    propio servidor y llevarse la cartera entera en los prompts, apagar el modo
    sombra, o exportarlo todo en un Excel."""
    token = emparejar_como(client, "invitado")
    red = por_la_red()
    llave = {"Authorization": f"Bearer {token}"}

    prohibidas = [
        ("PUT", "/v1/provider"),          # apuntar la IA a otro servidor
        ("GET", "/v1/export/facturas.xlsx"),  # llevarse todo
        ("PUT", "/v1/settings/modo-sombra"),  # soltar mensajes a clientes reales
        ("POST", "/v1/cua/misiones"),     # usar las sesiones ya autenticadas
        ("POST", "/v1/custom-connectors/test"),
        ("GET", "/v1/red-local"),
        ("POST", "/v1/dispositivos/invitacion"),
    ]
    for metodo, ruta in prohibidas:
        r = red.request(metodo, ruta, headers=llave, json={})
        assert r.status_code == 403, f"{metodo} {ruta} contestó {r.status_code}"

    # Y lo que sí es su trabajo, sigue abierto.
    assert red.get("/v1/cartera", headers=llave).status_code == 200


def test_el_aparato_del_dueno_si_entra_a_todo(client, en_la_red):
    token = emparejar_como(client, "dueno")
    red = por_la_red()
    r = red.get("/v1/red-local", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_el_tope_deja_de_ser_decorativo(client, en_la_red, db_session):
    """Vivía solo en el modelo y en la pantalla: la UI prometía 'aprueba hasta X'
    y el API dejaba aprobar cualquier monto."""
    from datetime import date

    from aiuda_core.models import Customer, Invoice, Reminder

    tenant = db_session.scalars(select(Tenant)).one()
    cliente = Customer(tenant_id=tenant.id, name="Aceros del Norte")
    db_session.add(cliente)
    db_session.flush()
    cara = Invoice(
        tenant_id=tenant.id, customer_id=cliente.id, folio="F-900", amount=90000,
        issued_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
    )
    db_session.add(cara)
    db_session.flush()
    recado = Reminder(
        tenant_id=tenant.id, invoice_id=cara.id, message="Buen día", status="draft",
        channel="whatsapp", recipient_phone="+522291234567", bucket="vencida_16_45",
        tone="firme",
    )
    db_session.add(recado)
    db_session.commit()

    token = emparejar_como(client, "invitado", tope=5000)
    red = por_la_red()
    r = red.post(
        f"/v1/reminders/{recado.id}/approve", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
    assert "monto" in r.json()["detail"]


def test_la_bitacora_dice_que_aparato_fue(client, en_la_red, db_session):
    """Antes, lo que aprobaba el teléfono de alguien del equipo quedaba firmado
    como si lo hubiera hecho el dueño en su computadora."""
    from aiuda_server.api.deps import Principal

    aparato = Dispositivo(
        tenant_id="t", id="abc123", nombre="iPhone de Ana", papel="invitado", token_hash="z"
    )
    suyo = Principal(
        tenant=None, dispositivo_id=aparato.id, dispositivo_nombre=aparato.nombre,
        _dispositivo=aparato,
    )
    assert suyo.quien == "iPhone de Ana"
    assert Principal(tenant=None).quien == "esta computadora"
    # Sin tope no aprueba nada; la consola local sí.
    assert not suyo.puede_aprobar(1)
    assert Principal(tenant=None).puede_aprobar(999_999)


def test_emparejar_no_se_puede_usar_para_tumbar_aiuda(client, en_la_red):
    """Es lo único sin llave, así que cualquiera en el WiFi lo puede tocar."""
    red = por_la_red()
    grande = red.post(
        "/v1/emparejar",
        headers={"Content-Length": "9999999"},
        json={"codigo": "x", "nombre": "y"},
    )
    assert grande.status_code == 413

    codigos = [red.post("/v1/emparejar", json={"codigo": "x", "nombre": "y"}) for _ in range(12)]
    assert any(r.status_code == 429 for r in codigos), "sin freno de intentos"


def test_un_invitado_no_cierra_una_factura_que_no_le_toca(client, en_la_red, db_session):
    """Dar por pagada una factura es cerrar dinero y devolverlo a la fuente. Pesa
    igual que aprobar un envío, así que el tope manda igual. Faltaba: con tope de
    5 mil se podía cerrar una de 95 mil."""
    from datetime import date

    from aiuda_core.models import Customer, Invoice

    tenant = db_session.scalars(select(Tenant)).one()
    cliente_neg = Customer(tenant_id=tenant.id, name="Constructora GAMA")
    db_session.add(cliente_neg)
    db_session.flush()
    grande = Invoice(
        tenant_id=tenant.id, customer_id=cliente_neg.id, folio="F-950", amount=95000,
        issued_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
    )
    chica = Invoice(
        tenant_id=tenant.id, customer_id=cliente_neg.id, folio="F-951", amount=900,
        issued_date=date(2026, 1, 1), due_date=date(2026, 2, 1),
    )
    db_session.add_all([grande, chica])
    db_session.commit()

    token = emparejar_como(client, "invitado", tope=5000)
    red = por_la_red()
    llave = {"Authorization": f"Bearer {token}"}

    assert red.post(f"/v1/invoices/{grande.id}/pay", headers=llave).status_code == 403
    assert red.post(f"/v1/invoices/{chica.id}/pay", headers=llave).status_code == 200


def test_un_invitado_no_le_escribe_a_los_clientes(client, en_la_red, db_session):
    """El aparato invitado podía escribirle a cualquier cliente del negocio
    (ficha, hilo, adjuntos) sin tope ni bitácora, y hasta QUITARLE una baja
    (opt-out) para reabrirle la cobranza. Hablar en nombre del negocio con un
    cliente es del dueño; el trabajo del día del invitado es aprobar/rechazar."""
    from aiuda_core.models import Conversation, Customer

    tenant = db_session.scalars(select(Tenant)).one()
    cliente = Customer(tenant_id=tenant.id, name="Cliente", phone="+522291234567")
    db_session.add(cliente)
    db_session.flush()
    conv = Conversation(tenant_id=tenant.id, remote_phone="5212291234567", channel="whatsapp")
    db_session.add(conv)
    db_session.commit()

    token = emparejar_como(client, "invitado")
    red = por_la_red()
    llave = {"Authorization": f"Bearer {token}"}

    prohibidas = [
        red.post(f"/v1/customers/{cliente.id}/messages", headers=llave, json={"body": "hola"}),
        red.post(f"/v1/conversations/{conv.id}/messages", headers=llave, json={"body": "hola"}),
        red.post(f"/v1/customers/{cliente.id}/optout", headers=llave, json={"activo": False}),
        red.post(
            f"/v1/customers/{cliente.id}/attachments",
            headers=llave,
            files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        ),
    ]
    for r in prohibidas:
        assert r.status_code == 403, f"{r.request.url.path} contestó {r.status_code}"

    # El aparato del DUEÑO sí puede (sin canal conectado el envío queda failed,
    # pero la petición pasa: es su negocio).
    token_dueno = emparejar_como(client, "dueno", nombre="el del dueño")
    r = red.post(
        f"/v1/customers/{cliente.id}/messages",
        headers={"Authorization": f"Bearer {token_dueno}"},
        json={"body": "hola"},
    )
    assert r.status_code == 200


def test_los_endpoints_de_admin_dejan_de_estar_abiertos_al_invitado(client, en_la_red):
    """require_role era un no-op: devolvía el principal sin comparar rangos, y la
    bitácora (GET /v1/audit) y el link de cobro (POST /v1/cobro/link) quedaban
    abiertos a cualquier invitado del WiFi. Ahora el rango se compara de verdad."""
    token = emparejar_como(client, "invitado")
    red = por_la_red()
    llave = {"Authorization": f"Bearer {token}"}

    assert red.get("/v1/audit", headers=llave).status_code == 403
    assert red.post(
        "/v1/cobro/link", headers=llave, json={"monto": 100.0, "concepto": "x"}
    ).status_code == 403

    # La consola local (el dueño en su computadora) sigue entrando.
    assert client.get("/v1/audit").status_code == 200


def test_un_endpoint_no_declarado_queda_cerrado_al_invitado(client, en_la_red):
    """La regla se invirtió: antes cualquier POST pasaba (fallaba ABIERTO) y un
    router nuevo quedaba accesible por default. Hoy un invitado solo toca lo
    declarado en permisos.INVITADO; dar de alta un cliente no lo está."""
    token = emparejar_como(client, "invitado")
    red = por_la_red()
    llave = {"Authorization": f"Bearer {token}"}

    r = red.post("/v1/customers", headers=llave, json={"name": "Colado", "phone": "+5215500000000"})
    assert r.status_code == 403

    # Y lo que sí es su trabajo sigue abierto: leer el negocio.
    assert red.get("/v1/cartera", headers=llave).status_code == 200


def test_la_lista_de_clientes_dice_quien_pidio_que_no_lo_contacten(client, db_session):
    """La ficha lo mandaba y la lista no. Sin ese dato, una app puede ofrecer
    escribirle por WhatsApp a alguien que ya dijo que no, que es justo lo que el
    registro de bajas existe para evitar."""
    from aiuda_core.models import Customer
    from aiuda_core.optout import mark_opt_out

    tenant = db_session.scalars(select(Tenant)).one()
    quiere = Customer(tenant_id=tenant.id, name="Sí quiere", phone="+522291110000")
    no_quiere = Customer(tenant_id=tenant.id, name="No quiere", phone="+522292220000")
    db_session.add_all([quiere, no_quiere])
    assert mark_opt_out(tenant, no_quiere.phone)
    db_session.add(tenant)
    db_session.commit()

    por_nombre = {c["name"]: c for c in client.get("/v1/customers").json()}
    assert por_nombre["No quiere"]["opt_out"] is True
    assert por_nombre["Sí quiere"]["opt_out"] is False
    # La ficha sí manda el registro completo (por qué medio y cuándo); la lista
    # solo el sí o no, que es lo que necesita para esconder un botón.
