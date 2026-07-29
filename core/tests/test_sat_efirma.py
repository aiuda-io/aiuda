"""La e.firma del SAT: validación antes de guardar y cifrado por RFC.

La Descarga Masiva EXIGE e.firma (FIEL): un CSD se rechaza aquí con mensaje
claro. La credencial se guarda UNA por RFC (hasta 3 empresas del mismo negocio),
cada fila cifrada aparte; el secreto jamás queda en claro en la base.

Los certificados se GENERAN en el test (RSA + X.509 con el RFC en
x500UniqueIdentifier, como los del SAT): así se prueba la validación de verdad
sin usar la e.firma de nadie.
"""

import zipfile
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.sat_descarga import (
    SatCredencialInvalida,
    extraer_xmls,
    validar_efirma,
)
from aiuda_core.models import IntegrationCredential

pytest.importorskip("satcfdi")

RFC = "HCO250213281"
PASSWORD = "una-clave-de-prueba"


def efirma_prueba(
    rfc: str = RFC,
    nombre: str = "HANOVA CONSULTING SAPI DE CV",
    password: str = PASSWORD,
    tipo: str = "fiel",
    dias: int = 365,
    desde_dias: int = -1,
) -> tuple[bytes, bytes]:
    """Genera un (.cer DER, .key DER cifrada) como los del SAT. `tipo='csd'`
    replica las señales de un CSD: 2 extensiones y nombre de sucursal (OU)."""
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
            _type=x509.name._ASN1Type.UTF8String,  # noqa: SLF001 — como los emite el SAT
        ),
    ]
    if tipo == "csd":
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "SUCURSAL MATRIZ"))
    subject = x509.Name(attrs)
    now = datetime.now(timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=desde_dias))
        .not_valid_after(now + timedelta(days=dias))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, True, True, False, False, False, False, False, False),
            critical=True,
        )
    )
    if tipo == "fiel":  # una FIEL real trae 4 extensiones; un CSD solo 2
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


@pytest.fixture(scope="module")
def fiel():
    return efirma_prueba()


@pytest.fixture(scope="module")
def csd():
    return efirma_prueba(tipo="csd")


def test_valida_fiel_y_devuelve_lo_publico(fiel):
    cer, key = fiel
    info = validar_efirma(cer, key, PASSWORD)
    assert info["rfc"] == RFC
    assert info["titular"] == "HANOVA CONSULTING"  # sin el régimen societario
    assert info["vigente_hasta"] > datetime.now(timezone.utc).date().isoformat()
    # lo público jamás incluye material secreto
    assert set(info) == {"rfc", "titular", "vigente_desde", "vigente_hasta"}


def test_rechaza_csd_con_mensaje_claro(csd):
    cer, key = csd
    with pytest.raises(SatCredencialInvalida) as exc:
        validar_efirma(cer, key, PASSWORD)
    assert "CSD" in str(exc.value)
    assert "e.firma" in str(exc.value)


def test_rechaza_vencida():
    cer, key = efirma_prueba(desde_dias=-400, dias=-5)
    with pytest.raises(SatCredencialInvalida) as exc:
        validar_efirma(cer, key, PASSWORD)
    assert "venció" in str(exc.value)


def test_rechaza_contrasena_equivocada(fiel):
    cer, key = fiel
    with pytest.raises(SatCredencialInvalida) as exc:
        validar_efirma(cer, key, "no-es-la-contrasena")
    assert "contraseña" in str(exc.value)


def test_rechaza_llave_de_otra_efirma(fiel, csd):
    cer, _ = fiel
    _, otra_llave = csd
    with pytest.raises(SatCredencialInvalida) as exc:
        validar_efirma(cer, otra_llave, PASSWORD)
    assert "pareja" in str(exc.value)


def test_rechaza_archivos_que_no_son_certificado(fiel):
    _, key = fiel
    with pytest.raises(SatCredencialInvalida):
        validar_efirma(b"esto no es un certificado", key, PASSWORD)


# ------------------------------------------- la credencial cifrada, una por RFC


def test_credencial_por_rfc_cifra_y_resuelve(session, tenant, fiel):
    """`sat_efirma:<RFC>` usa la spec de `sat_efirma`: los tres campos secretos
    van al blob cifrado y NADA queda en claro en la fila."""
    cer, key = fiel
    import base64 as b64

    valores = {
        "cer": b64.b64encode(cer).decode(),
        "key": b64.b64encode(key).decode(),
        "password": PASSWORD,
        "rfc": RFC,
        "titular": "HANOVA CONSULTING",
        "vigente_hasta": "2030-01-01",
    }
    cred.set_credential(session, tenant.id, f"sat_efirma:{RFC}", valores)
    row = session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.provider == f"sat_efirma:{RFC}"
        )
    )
    assert row is not None
    # el blob cifrado no contiene ni la contraseña ni la llave en claro
    assert PASSWORD.encode() not in row.secret_ciphertext
    assert valores["key"][:24].encode() not in row.secret_ciphertext
    # lo público de la fila no trae secretos
    assert set(row.public_config) == {"rfc", "titular", "vigente_hasta"}
    # y el resolver la regresa completa, descifrada solo en memoria
    leidas = cred.get_credential(session, tenant.id, f"sat_efirma:{RFC}")
    assert leidas["password"] == PASSWORD
    assert leidas["cer"] == valores["cer"]


def test_cada_rfc_tiene_su_fila_y_se_borra_sola(session, tenant):
    cred.set_credential(session, tenant.id, "sat_efirma:AAA010101AAA", {"cer": "x", "key": "y", "password": "z"})
    cred.set_credential(session, tenant.id, "sat_efirma:BBB020202BBB", {"cer": "x2", "key": "y2", "password": "z2"})
    rows = session.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.provider.like("sat_efirma:%")
        )
    ).all()
    assert len(rows) == 2
    session.delete(rows[0])
    session.flush()
    assert cred.get_credential(session, tenant.id, "sat_efirma:BBB020202BBB")["password"] == "z2"
    assert cred.get_credential(session, tenant.id, "sat_efirma:AAA010101AAA") is None


def test_extraer_xmls_solo_lee_en_memoria():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("uno.xml", "<Comprobante/>")
        zf.writestr("dos.XML", "<Comprobante/>")
        zf.writestr("meta.txt", "no")
    assert len(extraer_xmls(buf.getvalue())) == 2
