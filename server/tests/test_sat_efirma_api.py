"""API de la e.firma: subir valida y cifra; nada secreto sale jamás.

Las promesas que estos tests amarran:
- Subir una e.firma la valida (FIEL sí, CSD no, vencida no) ANTES de guardar.
- Se guarda CIFRADA (una fila por RFC); en la base no queda nada en claro.
- Ningún endpoint devuelve la llave, el certificado ni la contraseña.
- Hasta 3 empresas; el tope responde claro.
- Borrar la e.firma borra la fila de verdad.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, IntegrationCredential, Tenant
from aiuda_server.api.main import app, get_db

pytest.importorskip("satcfdi")

RFC = "HCO250213281"
PASSWORD = "clave-de-prueba"


def efirma_prueba(rfc=RFC, nombre="HANOVA CONSULTING SAPI DE CV",
                  password=PASSWORD, tipo="fiel"):
    """Certificado y llave DER como los del SAT (ver core/tests/test_sat_efirma.py)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [
        x509.NameAttribute(NameOID.COMMON_NAME, nombre),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, nombre),
        x509.NameAttribute(
            NameOID.X500_UNIQUE_IDENTIFIER, rfc,
            _type=x509.name._ASN1Type.UTF8String,  # noqa: SLF001
        ),
    ]
    if tipo == "csd":
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "SUCURSAL UNO"))
    subject = x509.Name(attrs)
    now = datetime.now(timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, True, True, False, False, False, False, False, False),
            critical=True,
        )
    )
    if tipo == "fiel":
        b = b.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
    cert = b.sign(key, hashes.SHA256())
    return (
        cert.public_bytes(serialization.Encoding.DER),
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode()),
        ),
    )


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
        name="Demo", owner_phone="52155", evolution_instance="demo-efirma",
        config={"demo": True, "members": [{"email": "demo@aiuda.mx", "role": "dueño"}]},
    )
    db_session.add(t)
    db_session.flush()
    demo_login(client)
    return t


def _subir_efirma(client, cer: bytes, key: bytes, password=PASSWORD, plazo_dias=30):
    return client.post(
        "/v1/sat/efirma",
        files={
            "cer": ("firma.cer", cer, "application/octet-stream"),
            "key": ("firma.key", key, "application/octet-stream"),
        },
        data={"password": password, "plazo_dias": plazo_dias},
    )


@pytest.fixture(scope="module")
def fiel():
    return efirma_prueba()


def test_conectar_efirma_valida_y_guarda_cifrado(client, db_session, demo, fiel):
    cer, key = fiel
    r = _subir_efirma(client, cer, key)
    assert r.status_code == 201, r.text
    empresa = r.json()["empresa"]
    assert empresa["rfc"] == RFC and empresa["efirma"] is True
    # la respuesta jamás trae material secreto
    assert "password" not in empresa and "key" not in empresa and "cer" not in empresa

    row = db_session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.provider == f"sat_efirma:{RFC}"
        )
    )
    assert row is not None
    assert PASSWORD.encode() not in row.secret_ciphertext  # cifrada de verdad
    assert set(row.public_config) == {"rfc", "titular", "vigente_desde", "vigente_hasta"}


def test_estado_enseña_lo_publico_y_nada_mas(client, demo, fiel):
    cer, key = fiel
    _subir_efirma(client, cer, key, plazo_dias=45)
    r = client.get("/v1/sat/estado")
    empresa = r.json()["empresas"][0]
    assert empresa["rfc"] == RFC and empresa["efirma"] is True
    assert empresa["vigente_hasta"]
    assert empresa["plazo_dias"] == 45
    plano = r.text.lower()
    assert PASSWORD not in plano
    assert "password" not in plano and '"cer"' not in plano and '"key"' not in plano


def test_el_config_generico_no_expone_la_efirma(client, demo, fiel):
    """La ruta genérica de integraciones no conoce filas con sufijo: ni
    enmascarada sale por ahí."""
    cer, key = fiel
    _subir_efirma(client, cer, key)
    r = client.get(f"/v1/integrations/sat_efirma:{RFC}/config")
    assert r.status_code == 404


def test_rechaza_csd_con_mensaje_de_producto(client, db_session, demo):
    cer, key = efirma_prueba(tipo="csd")
    r = _subir_efirma(client, cer, key)
    assert r.status_code == 422
    assert "CSD" in r.json()["detail"] and "e.firma" in r.json()["detail"]
    assert db_session.scalar(select(IntegrationCredential)) is None  # nada se guardó


def test_rechaza_contrasena_mala_sin_guardar(client, db_session, demo, fiel):
    cer, key = fiel
    r = _subir_efirma(client, cer, key, password="equivocada")
    assert r.status_code == 422
    assert "contraseña" in r.json()["detail"]
    assert db_session.scalar(select(IntegrationCredential)) is None


def test_tope_de_tres_empresas_tambien_con_efirma(client, demo, fiel):
    client.post("/v1/sat/empresas", json={"rfc": "AAA010101AAA"})
    client.post("/v1/sat/empresas", json={"rfc": "BBB020202BBB"})
    client.post("/v1/sat/empresas", json={"rfc": "CCC030303CCC"})
    cer, key = fiel
    r = _subir_efirma(client, cer, key)  # sería la cuarta empresa
    assert r.status_code == 409
    assert "tope" in r.json()["detail"]


def test_efirma_reemplaza_su_registro_manual_sin_duplicar(client, demo, fiel):
    client.post("/v1/sat/empresas", json={"rfc": RFC, "nombre": "Hanova"})
    cer, key = fiel
    r = _subir_efirma(client, cer, key)
    assert r.status_code == 201  # mismo RFC: no cuenta doble contra el tope
    empresas = client.get("/v1/sat/estado").json()["empresas"]
    assert [e["rfc"] for e in empresas] == [RFC]
    assert empresas[0]["efirma"] is True


def test_efirma_convierte_empresa_existente_aunque_ya_haya_tres(client, demo, fiel):
    for rfc in (RFC, "AAA010101AAA", "BBB020202BBB"):
        assert client.post("/v1/sat/empresas", json={"rfc": rfc}).status_code == 201
    cer, key = fiel
    r = _subir_efirma(client, cer, key)
    assert r.status_code == 201
    empresas = client.get("/v1/sat/estado").json()["empresas"]
    assert len(empresas) == 3
    assert next(e for e in empresas if e["rfc"] == RFC)["efirma"] is True


def test_borrar_efirma_borra_la_fila_de_verdad(client, db_session, demo, fiel):
    cer, key = fiel
    _subir_efirma(client, cer, key)
    r = client.delete(f"/v1/sat/efirma/{RFC}")
    assert r.status_code == 200
    assert db_session.scalar(select(IntegrationCredential)) is None
    assert client.get("/v1/sat/estado").json()["empresas"] == []


def test_no_se_puede_quitar_empresa_sin_borrar_su_efirma(client, demo, fiel):
    cer, key = fiel
    _subir_efirma(client, cer, key)
    r = client.delete(f"/v1/sat/empresas/{RFC}")
    assert r.status_code == 409
    assert "e.firma" in r.json()["detail"]


def test_probar_efirma_autentica_sin_exponer_secretos(
    client, demo, fiel, monkeypatch
):
    cer, key = fiel
    _subir_efirma(client, cer, key)

    class SatFalso:
        def __init__(self, cer_bytes, key_bytes, password):
            assert cer_bytes == cer
            assert key_bytes == key
            assert password == PASSWORD

        def probar(self):
            return {"ok": True, "rfc": RFC, "mensaje": "El SAT aceptó la e.firma."}

    monkeypatch.setattr("aiuda_server.api.sat.SatDescargaClient", SatFalso)
    r = client.post(f"/v1/sat/efirma/{RFC}/probar")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert PASSWORD not in r.text
