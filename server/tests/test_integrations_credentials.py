"""API de integraciones con credenciales CIFRADAS por tenant.

Verifica el nuevo camino (IntegrationCredential): guardar cifra y deja de
escribir texto plano; leer enmascara los secretos; el placeholder conserva el
secreto previo; probar persiste el veredicto; desconectar borra la fila. Mantiene
la compatibilidad con la config legada en claro como fallback de lectura.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, IntegrationCredential, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("cryptography")  # el camino cifrado necesita la librería

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
def demo(db_session, client, demo_login):
    t = Tenant(
        name="Demo", owner_phone="52155", evolution_instance="demo",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño"}]},
    )
    db_session.add(t)
    db_session.flush()
    demo_login(client)
    return t


def _row(db_session, tenant, provider):
    return db_session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == provider,
        )
    )


def test_guardar_cifra_y_no_deja_texto_plano(client, db_session, demo):
    res = client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o", "db": "d", "username": "u", "api_key": "K-secreta"}},
    )
    assert res.status_code == 200 and res.json()["connected"] is True

    row = _row(db_session, demo, "odoo")
    assert row is not None and row.status == "configured"
    # El secreto va cifrado: NO aparece en claro en ningún lado.
    assert b"K-secreta" not in (row.secret_ciphertext or b"")
    assert row.public_config == {"url": "https://o", "db": "d", "username": "u"}
    # Ya NO se escribe en tenant.config['integrations'].
    db_session.refresh(demo)
    assert "odoo" not in (demo.config.get("integrations") or {})


def test_leer_enmascara_secretos_y_muestra_publico(client, db_session, demo):
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o", "db": "d", "username": "u", "api_key": "K"}},
    )
    cfg = client.get("/v1/integrations/odoo/config").json()
    assert cfg["configured"] is True
    assert cfg["values"]["url"] == "https://o"  # público en claro
    assert cfg["values"]["api_key"] == "••••••"  # secreto enmascarado
    assert "K" not in str(cfg["values"]["api_key"])


def test_placeholder_conserva_el_secreto_previo(client, db_session, demo):
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o", "db": "d", "username": "u", "api_key": "K-orig"}},
    )
    # Reguardar cambiando la URL pero mandando el placeholder en api_key.
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://nueva", "db": "d", "username": "u", "api_key": "••••••"}},
    )
    from aiuda_core.connectors import credentials as cred

    creds = cred.get_credential(db_session, demo.id, "odoo")
    assert creds["url"] == "https://nueva"  # se actualizó lo público
    assert creds["api_key"] == "K-orig"  # se conservó el secreto


def test_actualizar_un_secreto_no_borra_el_otro(client, db_session, demo):
    # WooCommerce tiene dos secretos: cambiar uno y mandar placeholder en el otro.
    client.put(
        "/v1/integrations/woocommerce/config",
        json={"values": {"base_url": "https://w", "consumer_key": "ck1", "consumer_secret": "cs1"}},
    )
    client.put(
        "/v1/integrations/woocommerce/config",
        json={"values": {"base_url": "https://w", "consumer_key": "ck2", "consumer_secret": "••••••"}},
    )
    from aiuda_core.connectors import credentials as cred

    creds = cred.get_credential(db_session, demo.id, "woocommerce")
    assert creds["consumer_key"] == "ck2"  # actualizado
    assert creds["consumer_secret"] == "cs1"  # conservado


def test_probar_persiste_el_veredicto(client, db_session, demo):
    # Guarda solo la URL de Odoo: el tester responde "Faltan datos" sin tocar red.
    client.put("/v1/integrations/odoo/config", json={"values": {"url": "https://o"}})
    res = client.post("/v1/integrations/odoo/test").json()
    assert res["ok"] is False
    row = _row(db_session, demo, "odoo")
    assert row.status == "error"
    assert row.last_test_at is not None
    assert row.last_error


def test_grafo_expone_el_semaforo_verificado(client, db_session, demo):
    # Configurada pero sin probar aún -> "untested" (sin fecha de prueba).
    client.put("/v1/integrations/hubspot/config", json={"values": {"token": "secret_xyz"}})
    hubspot = next(
        s for s in client.get("/v1/integrations").json()["systems"] if s["key"] == "hubspot"
    )
    assert hubspot["verified"] == "untested"
    assert hubspot["last_test_at"] is None
    assert hubspot["last_error"] is None

    # Guardar solo la URL de Odoo y probar -> el tester falla -> "error" con motivo.
    client.put("/v1/integrations/odoo/config", json={"values": {"url": "https://o"}})
    assert client.post("/v1/integrations/odoo/test").json()["ok"] is False
    odoo = next(
        s for s in client.get("/v1/integrations").json()["systems"] if s["key"] == "odoo"
    )
    assert odoo["verified"] == "error"
    assert odoo["last_error"]
    assert odoo["last_test_at"] is not None


def test_desconectar_borra_la_fila(client, db_session, demo):
    client.put("/v1/integrations/hubspot/config", json={"values": {"token": "secret_xyz"}})
    assert _row(db_session, demo, "hubspot") is not None
    client.delete("/v1/integrations/hubspot/config")
    assert _row(db_session, demo, "hubspot") is None
    graph = client.get("/v1/integrations").json()
    hubspot = next(s for s in graph["systems"] if s["key"] == "hubspot")
    assert hubspot["connected"] is False and hubspot["configured"] is False


def test_fila_cifrada_marca_conectado_en_el_grafo(client, db_session, demo):
    client.put("/v1/integrations/hubspot/config", json={"values": {"token": "tok"}})
    graph = client.get("/v1/integrations").json()
    hub = next(s for s in graph["systems"] if s["key"] == "hubspot")
    assert hub["connected"] is True and hub["configured"] is True


def test_no_pisa_secreto_si_la_clave_es_ilegible(client, db_session, demo, monkeypatch):
    # Guarda con la clave buena.
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o", "db": "d", "username": "u", "api_key": "K"}},
    )
    # La clave se vuelve ilegible (rotación/pérdida): editar solo lo público y
    # mandar el placeholder NO debe borrar el secreto; el guardado se rechaza.
    from aiuda_core.connectors import credentials as cred

    def boom(*_a, **_k):
        raise RuntimeError("clave ilegible")

    monkeypatch.setattr(cred, "read_stored", boom)
    res = client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://nueva", "db": "d", "username": "u", "api_key": "••••••"}},
    )
    assert res.status_code == 409
    # La fila NO se sobrescribió: el ciphertext original sigue intacto.
    row = _row(db_session, demo, "odoo")
    monkeypatch.undo()
    assert cred.get_credential(db_session, demo.id, "odoo")["api_key"] == "K"
    assert row.public_config == {"url": "https://o", "db": "d", "username": "u"}


def test_reemplazo_total_funciona_aunque_la_clave_vieja_sea_ilegible(client, db_session, demo, monkeypatch):
    client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o", "db": "d", "username": "u", "api_key": "K"}},
    )
    from aiuda_core.connectors import credentials as cred

    monkeypatch.setattr(cred, "read_stored", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    # Recaptura COMPLETA (todos los secretos frescos): se permite, no necesita lo previo.
    res = client.put(
        "/v1/integrations/odoo/config",
        json={"values": {"url": "https://o2", "db": "d2", "username": "u2", "api_key": "K2"}},
    )
    assert res.status_code == 200
    monkeypatch.undo()
    assert cred.get_credential(db_session, demo.id, "odoo")["api_key"] == "K2"


def test_fallback_legado_en_claro_se_sigue_leyendo(client, db_session, demo):
    # Credencial vieja en texto plano (sin fila): GET la enmascara y el grafo la
    # marca conectada — no se regresiona durante la transición.
    demo.config = {**demo.config, "integrations": {"slack": {"bot_token": "xoxb-legado"}}}
    db_session.add(demo)
    db_session.flush()
    cfg = client.get("/v1/integrations/slack/config").json()
    assert cfg["configured"] is True and cfg["values"]["bot_token"] == "••••••"
    graph = client.get("/v1/integrations").json()
    slack = next(s for s in graph["systems"] if s["key"] == "slack")
    assert slack["connected"] is True


# --- Secretos que se guardaban en texto plano (bug sistémico) -----------------
#
# Bastaba con que una llave del CATALOG no tuviera entrada en PROVIDERS para que su
# config cayera a la vía legada y se guardara SIN cifrar, mientras el resto iba con
# Fernet. Le pasaba a `whatsapp`, `excel` y `sat`, y el front lo empeoraba inventando
# un campo "token" secreto para toda llave que no declarara los suyos.


def test_via_legada_rechaza_secretos_en_vez_de_guardarlos_en_claro(client, db_session, demo):
    res = client.put(
        "/v1/integrations/whatsapp/config",
        json={"values": {"instance": "mi-negocio", "token": "EVO-SECRETA"}},
    )
    assert res.status_code == 400
    assert "token" in res.json()["detail"]

    # Y no quedó rastro del secreto por ninguna vía.
    db_session.refresh(demo)
    assert "EVO-SECRETA" not in str(demo.config)
    assert _row(db_session, demo, "whatsapp") is None


def test_via_legada_sigue_aceptando_lo_que_no_es_secreto(client, db_session, demo):
    res = client.put(
        "/v1/integrations/whatsapp/config",
        json={"values": {"instance": "mi-negocio", "via": "wacli"}},
    )
    assert res.status_code == 200
    db_session.refresh(demo)
    assert demo.config["integrations"]["whatsapp"] == {"instance": "mi-negocio", "via": "wacli"}


def test_purga_borra_lo_secreto_y_conserva_el_ruteo(db_session, demo):
    from aiuda_core.connectors.credentials import purgar_secretos_en_claro

    demo.config = {
        **demo.config,
        "integrations": {
            # via/instance NO son credencial: los lee resolve_whatsapp y se quedan.
            "whatsapp": {"via": "evolution", "instance": "mi-negocio", "token": "EVO-SECRETA"},
            "sat": {"token": "efirma-secreta"},
            "excel": {"api_key": "no-deberia-existir"},
        },
    }
    db_session.add(demo)
    db_session.flush()

    assert purgar_secretos_en_claro(db_session) == 3

    db_session.refresh(demo)
    integraciones = demo.config["integrations"]
    assert integraciones["whatsapp"] == {"via": "evolution", "instance": "mi-negocio"}
    assert integraciones["sat"] == {}
    assert integraciones["excel"] == {}
    assert "EVO-SECRETA" not in str(demo.config)
    assert "efirma-secreta" not in str(demo.config)


def test_purga_es_idempotente_y_no_toca_lo_limpio(db_session, demo):
    from aiuda_core.connectors.credentials import purgar_secretos_en_claro

    demo.config = {**demo.config, "integrations": {"whatsapp": {"via": "wacli"}}}
    db_session.add(demo)
    db_session.flush()

    assert purgar_secretos_en_claro(db_session) == 0
    assert purgar_secretos_en_claro(db_session) == 0
    db_session.refresh(demo)
    assert demo.config["integrations"] == {"whatsapp": {"via": "wacli"}}
