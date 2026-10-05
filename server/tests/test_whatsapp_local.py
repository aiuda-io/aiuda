"""WhatsApp sin terminal: instalar el conector con un clic, que el server sea
dueño del proceso de wacli y que las fallas lleguen en español.

Nada de aquí toca un WhatsApp de verdad: el binario es el wacli falso de
``wacli_falso/`` (mismo candado, mismos eventos) sobre un store temporal.
"""

import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.config import settings
from aiuda_core.connectors import wacli_bin
from aiuda_core.connectors.wacli import WacliClient, WacliError
import aiuda_server.worker.main as worker_main
from aiuda_core.models import Base, Customer, Tenant
from aiuda_server import wacli_sync
from aiuda_server.api.main import app, get_db

WACLI_FALSO = str(Path(__file__).parent / "wacli_falso" / "wacli")


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
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def tenant(db_session):
    t = Tenant(name="Negocio", owner_phone="5215500000000", evolution_instance="inst-a", config={})
    db_session.add(t)
    db_session.flush()
    return t


# ---------- instalar con un clic ----------

def test_status_sin_conector_ofrece_instalar(client, tenant, monkeypatch):
    monkeypatch.setattr(wacli_bin, "puede_instalarse", lambda: None)
    r = client.get("/v1/integrations/whatsapp/status").json()
    assert r["connected"] is False
    assert r["instalado"] is False and r["no_se_puede"] is None


def test_status_en_mac_vieja_dice_por_que_no(client, tenant, monkeypatch):
    monkeypatch.setattr(wacli_bin, "_macos_mayor", lambda: 14)
    r = client.get("/v1/integrations/whatsapp/status").json()
    assert r["instalado"] is False
    assert "macOS 15" in r["no_se_puede"]


def test_instalar_deja_el_conector_listo(client, tenant, monkeypatch):
    def instalar():
        monkeypatch.setattr(settings, "wacli_bin", WACLI_FALSO)
        return WACLI_FALSO

    monkeypatch.setattr(wacli_bin, "instalar", instalar)
    r = client.post("/v1/integrations/whatsapp/instalar")
    assert r.status_code == 200
    assert r.json() == {"instalado": True, "version": "0.20.0", "no_se_puede": None}


def test_instalar_que_falla_responde_en_espanol(client, tenant, monkeypatch):
    def instalar():
        raise wacli_bin.WacliInstallError(wacli_bin.DESCARGA_FALLO)

    monkeypatch.setattr(wacli_bin, "instalar", instalar)
    r = client.post("/v1/integrations/whatsapp/instalar")
    assert r.status_code == 502
    assert "Revisa tu internet" in r.json()["detail"]


def test_qr_sin_conector_pide_instalarlo(client, tenant):
    r = client.post("/v1/integrations/whatsapp/qr")
    assert r.status_code == 409
    assert "presiona Instalar" in r.json()["detail"]


# ---------- el veredicto del envío, con sesiones de base separadas ----------

@pytest.fixture()
def api_real(tmp_path, monkeypatch):
    """Como corre de verdad: cada request con SU sesión (commit al terminar) y el
    envío en segundo plano con otra. Con una sola sesión compartida, las pruebas
    no ven que la tarea corre ANTES del commit del request."""
    engine = create_engine(f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_db():
        s = Sesion()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    @contextmanager
    def _scope():
        yield from _get_db()

    monkeypatch.setattr(worker_main, "session_scope", _scope)
    with Sesion() as s:
        t = Tenant(
            name="Negocio", owner_phone="5215500000000", evolution_instance="inst-a",
            config={"integrations": {"whatsapp": {"via": "wacli", "instance": "inst-a"}}},
        )
        s.add(t)
        s.flush()
        c = Customer(tenant_id=t.id, name="Cliente", phone="5215599998888")
        s.add(c)
        s.commit()
        cliente_id = c.id
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app), cliente_id
    app.dependency_overrides.clear()


def _mensaje(http, conv_id, message_id) -> dict:
    mensajes = http.get(f"/v1/conversations/{conv_id}").json()["messages"]
    return next(m for m in mensajes if m["id"] == message_id)


def test_mensaje_desde_la_ficha_queda_sent_y_no_pending(api_real, monkeypatch):
    """Visto en vivo: la tarea de envío corría antes de que el request guardara el
    mensaje, no lo encontraba para marcarlo y se quedaba 'pending'; el barrido de
    pendientes lo habría mandado otra vez."""
    http, cliente_id = api_real
    monkeypatch.setattr(worker_main, "get_whatsapp_sender", lambda wa, w=None: lambda p, t: None)
    r = http.post(f"/v1/customers/{cliente_id}/messages", json={"body": "Hola"}).json()
    assert _mensaje(http, r["conversation_id"], r["id"])["delivery"] == "sent"
    # Y desde el hilo, y al reintentar: mismo veredicto.
    r2 = http.post(f"/v1/conversations/{r['conversation_id']}/messages", json={"body": "Otra"}).json()
    assert _mensaje(http, r["conversation_id"], r2["id"])["delivery"] == "sent"
    url = f"/v1/conversations/{r['conversation_id']}/messages/{r2['id']}/resend"
    assert http.post(url).status_code == 200
    assert _mensaje(http, r["conversation_id"], r2["id"])["delivery"] == "sent"


def _falla_con(monkeypatch, exc):
    def sender(wa, w=None):
        def _s(phone, text):
            raise exc
        return _s

    monkeypatch.setattr(worker_main, "get_whatsapp_sender", sender)


def test_mensaje_que_falla_guarda_el_motivo_en_espanol(api_real, monkeypatch):
    http, cliente_id = api_real
    _falla_con(monkeypatch, WacliError("not authenticated; run `wacli auth`"))
    r = http.post(f"/v1/customers/{cliente_id}/messages", json={"body": "Hola"}).json()
    m = _mensaje(http, r["conversation_id"], r["id"])
    assert m["delivery"] == "failed" and m["reintentable"] is True
    assert m["motivo_fallo"].startswith("Tu WhatsApp no está vinculado.")
    assert "wacli" not in m["motivo_fallo"]

    # El teléfono los ve todos juntos, sin recorrer cada conversación.
    fallidos = http.get("/v1/mensajes/fallidos").json()["fallidos"]
    assert [f["id"] for f in fallidos] == [r["id"]]
    assert fallidos[0]["motivo_fallo"] == m["motivo_fallo"]
    assert fallidos[0]["customer"] == "Cliente" and fallidos[0]["body"] == "Hola"

    # Reintento que sí sale: el motivo se borra y deja de aparecer como fallido.
    monkeypatch.setattr(worker_main, "get_whatsapp_sender", lambda wa, w=None: lambda p, t: None)
    http.post(f"/v1/conversations/{r['conversation_id']}/messages/{r['id']}/resend")
    m = _mensaje(http, r["conversation_id"], r["id"])
    assert m["delivery"] == "sent" and m["motivo_fallo"] is None
    assert http.get("/v1/mensajes/fallidos").json()["fallidos"] == []


def test_envio_que_se_corta_a_media_espera_no_invita_a_reenviar_a_ciegas(api_real, monkeypatch):
    http, cliente_id = api_real
    _falla_con(monkeypatch, subprocess.TimeoutExpired(cmd="wacli", timeout=60))
    r = http.post(f"/v1/customers/{cliente_id}/messages", json={"body": "Hola"}).json()
    motivo = _mensaje(http, r["conversation_id"], r["id"])["motivo_fallo"]
    assert motivo.startswith("No supimos si el mensaje salió.")


def test_adjunto_que_falla_queda_fallido_con_motivo_y_no_se_reintenta(api_real, monkeypatch):
    http, cliente_id = api_real

    def send_file(self, phone, file_path, caption="", filename=None):
        raise WacliError("file too large (99 bytes); maximum size is 1 bytes")

    monkeypatch.setattr(WacliClient, "send_file", send_file)
    r = http.post(
        f"/v1/customers/{cliente_id}/attachments",
        files={"file": ("factura.pdf", b"%PDF-1.4", "application/pdf")},
    ).json()
    m = _mensaje(http, r["conversation_id"], r["id"])
    assert m["delivery"] == "failed" and m["reintentable"] is False
    assert m["motivo_fallo"] == "El archivo es demasiado grande para WhatsApp."
    url = f"/v1/conversations/{r['conversation_id']}/messages/{r['id']}/resend"
    assert http.post(url).status_code == 400  # el archivo ya no existe: se vuelve a adjuntar


def test_adjunto_que_sale_queda_sent(api_real, monkeypatch):
    http, cliente_id = api_real
    monkeypatch.setattr(WacliClient, "send_file", lambda self, *a, **k: None)
    r = http.post(
        f"/v1/customers/{cliente_id}/attachments",
        files={"file": ("factura.pdf", b"%PDF-1.4", "application/pdf")},
    ).json()
    assert _mensaje(http, r["conversation_id"], r["id"])["delivery"] == "sent"


def test_adjunto_interrumpido_se_marca_fallido_y_no_se_reenvia_como_texto(api_real, monkeypatch):
    http, cliente_id = api_real
    # La tarea "muere" sin dar veredicto: el mensaje se queda en 'sending'.
    monkeypatch.setattr(worker_main, "send_human_file_blocking", lambda *a: None)
    r = http.post(
        f"/v1/customers/{cliente_id}/attachments",
        files={"file": ("factura.pdf", b"%PDF-1.4", "application/pdf")},
    ).json()
    assert _mensaje(http, r["conversation_id"], r["id"])["delivery"] == "sending"
    enviados = []
    monkeypatch.setattr(worker_main, "send_human_message_blocking", lambda *a: enviados.append(a))
    worker_main._sweep_pending_sends(datetime.now(timezone.utc) + timedelta(hours=1))
    m = _mensaje(http, r["conversation_id"], r["id"])
    assert m["delivery"] == "failed" and "Vuelve a adjuntarlo" in m["motivo_fallo"]
    assert enviados == []


def test_los_motivos_guardados_no_crecen_sin_limite(api_real, monkeypatch):
    http, cliente_id = api_real
    monkeypatch.setattr(worker_main, "_MAX_ENVIOS_FALLIDOS", 2)
    _falla_con(monkeypatch, WacliError("not connected"))
    ids = [
        http.post(f"/v1/customers/{cliente_id}/messages", json={"body": f"m{i}"}).json()["id"]
        for i in range(3)
    ]
    with worker_main.session_scope() as s:
        guardados = list(s.query(Tenant).one().config[worker_main.ENVIOS_FALLIDOS_KEY])
    assert guardados == ids[1:]


# ---------- probar conexión y "conectado" en vivo ----------

def _marcado(db_session, tenant) -> None:
    tenant.config = {"integrations": {"whatsapp": {"via": "wacli", "instance": "inst-a"}}}
    db_session.add(tenant)
    db_session.flush()


def _conectado_en_lista(client) -> bool:
    sistemas = client.get("/v1/integrations").json()["systems"]
    return next(s for s in sistemas if s["key"] == "whatsapp")["connected"]


def test_probar_conexion_sin_conector_dice_que_falta_instalar(client, tenant, monkeypatch):
    monkeypatch.setattr(wacli_bin, "puede_instalarse", lambda: None)
    r = client.post("/v1/integrations/whatsapp/test").json()
    assert r["ok"] is False and "presiona Instalar" in r["message"]


def test_probar_conexion_sin_vincular(client, tenant, falso):
    r = client.post("/v1/integrations/whatsapp/test").json()
    assert r["ok"] is False and "escanea el código QR" in r["message"]


def test_probar_conexion_con_sesion_viva(client, tenant, falso):
    _vinculado(falso)
    r = client.post("/v1/integrations/whatsapp/test").json()  # arranca el sync y espera
    assert r == {
        "ok": True, "message": "Conectado a WhatsApp.", "details": {"Número": "+5215511112222"}
    }


def test_probar_conexion_con_la_sesion_cerrada_desde_el_telefono(client, tenant, falso):
    _vinculado(falso)
    client.post("/v1/integrations/whatsapp/test")
    (falso / "cerrar_sesion").write_text("")
    assert _esperar(lambda: _estado(falso) == "sesion_cerrada")
    r = client.post("/v1/integrations/whatsapp/test").json()
    assert r["ok"] is False and "Vuelve a escanear el código QR" in r["message"]


def test_conectado_sigue_a_la_sesion_y_no_a_la_marca_guardada(client, db_session, tenant, falso):
    _marcado(db_session, tenant)
    # La marca dice wacli, pero no hay sesión: NO está conectado.
    assert _conectado_en_lista(client) is False
    _vinculado(falso)
    assert _conectado_en_lista(client) is True
    # WhatsApp cierra la sesión desde el teléfono: deja de estar conectado solo.
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    (falso / "cerrar_sesion").write_text("")
    assert _esperar(lambda: _estado(falso) == "sesion_cerrada")
    assert _conectado_en_lista(client) is False
    assert tenant.config["integrations"]["whatsapp"]["via"] == "wacli"  # la marca sigue


# ---------- el server es dueño del proceso de wacli ----------

def _esperar(condicion, segundos=20.0):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.fixture()
def falso(monkeypatch, tmp_path):
    """El wacli falso como conector, con store y carpeta de datos temporales y los
    tiempos del supervisor acortados. Al terminar no queda ningún proceso."""
    datos = tmp_path / "datos"
    datos.mkdir()
    monkeypatch.setattr(settings, "wacli_bin", WACLI_FALSO)
    monkeypatch.setattr(settings, "wacli_store_root", str(tmp_path / "stores"))
    monkeypatch.setattr(wacli_sync, "default_data_dir", lambda: datos)
    monkeypatch.setattr(wacli_sync, "_TICK_S", 0.05)
    monkeypatch.setattr(wacli_sync, "_REANUDAR_S", 0.1)
    monkeypatch.setattr(wacli_sync, "_ESPERAS", (0.2, 0.2))
    monkeypatch.setattr(wacli_sync, "_ESPERA_EXTERNO", 0.3)
    monkeypatch.setenv("WACLI_FALSO_QR_ROTA", "0.3")
    wacli_sync._canales.clear()
    store = tmp_path / "stores" / "inst-a"
    store.mkdir(parents=True)
    yield store
    wacli_sync.detener_todo()
    wacli_sync._canales.clear()


def _vinculado(store) -> None:
    (store / "session.json").write_text(
        json.dumps({"authenticated": True, "phone": "5215511112222"})
    )


def _arranques(store) -> list[int]:
    try:
        return [int(x) for x in (store / "arranques.log").read_text().split()]
    except FileNotFoundError:
        return []


def _estado(store) -> str:
    return wacli_sync.estado("inst-a", str(store))["estado"]


def _pidfile(store) -> Path:
    return store.parent.parent / "datos" / "wacli.inst-a.pid"


def _candado_tomado(store) -> bool:
    out = subprocess.run(
        [WACLI_FALSO, "doctor", "--json", "--store", str(store)], capture_output=True, text=True
    )
    return json.loads(out.stdout)["data"]["lock_held"]


def test_sin_sesion_no_se_lanza_nada(falso):
    assert wacli_sync.arrancar("inst-a", str(falso)) == "sin_vincular"
    assert _arranques(falso) == []


def test_arrancar_conecta_y_no_lanza_dos(falso):
    _vinculado(falso)
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    wacli_sync.arrancar("inst-a", str(falso))  # idempotente
    wacli_sync.arrancar("inst-a", str(falso))
    assert len(_arranques(falso)) == 1
    nota = json.loads(_pidfile(falso).read_text())
    assert nota == {"pid": _arranques(falso)[0], "server": os.getpid()}
    assert wacli_sync.estado("inst-a", str(falso))["telefono"] == "5215511112222"


def test_emparejar_rota_el_qr_y_al_escanear_arranca_el_sync(falso):
    primero = wacli_sync.vincular("inst-a", str(falso))
    assert primero == "QR-FALSO-1"
    assert _estado(falso) == "vinculando"
    # wacli rota el QR: el estado trae siempre el vigente.
    assert _esperar(lambda: wacli_sync.estado("inst-a", str(falso))["qr"] not in (None, primero))
    (falso / "escanear").write_text("")
    assert _esperar(lambda: _estado(falso) == "conectado")
    assert wacli_sync.estado("inst-a", str(falso))["qr"] is None
    assert len(_arranques(falso)) == 1


def test_cancelar_el_emparejamiento_suelta_el_candado(falso):
    assert wacli_sync.vincular("inst-a", str(falso))
    assert _candado_tomado(falso)
    wacli_sync.cancelar_vinculacion("inst-a")
    assert not _candado_tomado(falso)
    assert _estado(falso) == "sin_vincular"


def _que_venza_el_qr() -> None:
    """Como si ya hubieran pasado los 3 minutos sin que nadie escaneara."""
    wacli_sync._canales["inst-a"].vence = time.monotonic()


def test_un_qr_que_nadie_escanea_no_se_queda_con_el_candado(falso):
    assert wacli_sync.vincular("inst-a", str(falso))
    _que_venza_el_qr()
    assert _esperar(lambda: not _candado_tomado(falso))
    assert _estado(falso) == "sin_vincular"


def test_pausar_para_enviar_y_reanudar(falso):
    _vinculado(falso)
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    (pid,) = _arranques(falso)
    with wacli_sync.pausado("inst-a"):
        assert not _vivo(pid)
        # El candado está libre: el envío entra sin esperar.
        out = subprocess.run(
            [WACLI_FALSO, "send", "text", "--to", "x", "--message", "hola", "--store", str(falso)],
            capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
    assert _esperar(lambda: len(_arranques(falso)) == 2 and _estado(falso) == "conectado")


def test_si_el_sync_muere_se_relanza(falso):
    _vinculado(falso)
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    (falso / "morir").write_text("")
    assert _esperar(lambda: len(_arranques(falso)) == 2 and _estado(falso) == "conectado")


def test_si_whatsapp_cierra_la_sesion_no_se_relanza(falso):
    _vinculado(falso)
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    (falso / "cerrar_sesion").write_text("")
    assert _esperar(lambda: _estado(falso) == "sesion_cerrada")
    time.sleep(0.6)  # más que la espera de relanzado
    assert len(_arranques(falso)) == 1
    assert _estado(falso) == "sesion_cerrada"


def test_un_wacli_ajeno_se_respeta_y_se_retoma_cuando_suelta(falso):
    _vinculado(falso)
    ajeno = subprocess.Popen(
        [WACLI_FALSO, "sync", "--follow", "--store", str(falso)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert _esperar(lambda: _candado_tomado(falso))
        wacli_sync.arrancar("inst-a", str(falso))
        assert _esperar(lambda: _estado(falso) == "externo")
        assert ajeno.poll() is None  # no se le quitó la sesión
    finally:
        ajeno.terminate()
        ajeno.wait(timeout=5)
    assert _esperar(lambda: _estado(falso) == "conectado")


def test_el_huerfano_de_un_aiuda_muerto_se_termina(falso):
    _vinculado(falso)
    huerfano = subprocess.Popen(
        [WACLI_FALSO, "sync", "--follow", "--store", str(falso)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    muerto = subprocess.Popen(["true"])
    muerto.wait()
    assert _esperar(lambda: _candado_tomado(falso))
    _pidfile(falso).write_text(json.dumps({"pid": huerfano.pid, "server": muerto.pid}))
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    assert huerfano.wait(timeout=5) is not None
    assert len(_arranques(falso)) == 2  # el huérfano y el nuestro


def test_detener_todo_no_deja_procesos(falso):
    _vinculado(falso)
    wacli_sync.arrancar("inst-a", str(falso))
    assert _esperar(lambda: _estado(falso) == "conectado")
    (pid,) = _arranques(falso)
    wacli_sync.detener_todo()
    assert not _vivo(pid)
    assert not _candado_tomado(falso)
    assert not _pidfile(falso).exists()


# ---------- la API encima del supervisor ----------

def _status(client) -> dict:
    return client.get("/v1/integrations/whatsapp/status").json()


def test_api_emparejar_de_punta_a_punta(client, tenant, falso):
    r = client.post("/v1/integrations/whatsapp/qr").json()
    assert r["connected"] is False and r["qr"].startswith("data:image/svg+xml")
    s = _status(client)
    assert s["estado"] == "vinculando" and s["connected"] is False and s["qr"]
    (falso / "escanear").write_text("")
    assert _esperar(lambda: _status(client)["estado"] == "conectado")
    s = _status(client)
    assert s["connected"] is True and s["qr"] is None and s["telefono"] == "5215500000001"
    assert tenant.config["integrations"]["whatsapp"] == {"via": "wacli", "instance": "inst-a"}


def test_api_cerrar_la_ventana_cancela_el_emparejamiento(client, tenant, falso):
    client.post("/v1/integrations/whatsapp/qr")
    assert _candado_tomado(falso)
    assert client.delete("/v1/integrations/whatsapp/qr").status_code == 200
    assert not _candado_tomado(falso)


def test_api_qr_que_caduca_lo_dice_en_espanol(client, tenant, falso):
    assert client.post("/v1/integrations/whatsapp/qr").status_code == 200
    _que_venza_el_qr()
    assert _esperar(lambda: _status(client)["estado"] == "sin_vincular")
    assert _status(client)["aviso"] == "El código QR caducó. Genera uno nuevo y escanéalo."


def test_api_qr_con_el_whatsapp_ocupado_por_otro_programa(client, tenant, falso):
    # Sin sesión todavía, pero otro wacli tiene el store (alguien emparejando a mano).
    ajeno = subprocess.Popen(
        [WACLI_FALSO, "auth", "--store", str(falso)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert _esperar(lambda: _candado_tomado(falso))
        r = client.post("/v1/integrations/whatsapp/qr")
        assert r.status_code == 502
        assert r.json()["detail"].startswith("WhatsApp está ocupado en esta computadora")
    finally:
        ajeno.terminate()
        ajeno.wait(timeout=5)


def test_api_sesion_vinculada_desde_fuera_se_reconoce_y_arranca(client, tenant, falso):
    _vinculado(falso)
    assert _status(client)["connected"] is True
    assert _esperar(lambda: _status(client)["estado"] == "conectado")
    assert len(_arranques(falso)) == 1


def test_api_desvincular_cierra_la_sesion_y_detiene_el_sync(client, tenant, falso):
    _vinculado(falso)
    _status(client)
    assert _esperar(lambda: _estado(falso) == "conectado")
    (pid,) = _arranques(falso)
    r = client.delete("/v1/integrations/whatsapp/session")
    assert r.status_code == 200 and r.json() == {"connected": False}
    assert not _vivo(pid)
    assert not (falso / "session.json").exists()
    assert "whatsapp" not in tenant.config["integrations"]
    assert _status(client)["estado"] == "sin_vincular"


def test_api_desvincular_que_falla_no_miente(client, tenant, falso, monkeypatch):
    _vinculado(falso)
    _status(client)
    assert _esperar(lambda: _estado(falso) == "conectado")
    monkeypatch.setattr(wacli_sync, "desvincular", lambda i, s: "not connected")
    r = client.delete("/v1/integrations/whatsapp/session")
    assert r.status_code == 502 and "No se pudo cerrar la sesión" in r.json()["detail"]
    assert tenant.config["integrations"]["whatsapp"]["via"] == "wacli"
