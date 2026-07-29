"""Ingesta de conexiones a la medida: la fuente REST que el dueño declaró entra al motor.

Tests de CONTRATO con respuestas grabadas (fixtures JSON estáticos en data/, la forma
real que devolvería una API de ejemplo): el mapeo declarativo produce entidades con
procedencia, tipos normalizados (Decimal, date, normalize_mx), dedupe por external_id
e idempotencia. Y el no-op honesto: fuente caída = aviso registrado, nada inventado.
"""

import base64
import io
import json
import urllib.error
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from aiuda_core.connectors import custom_api
from aiuda_core.engine.sync import _to_date, _to_decimal, sync_custom, sync_fuentes
from aiuda_core.models import Appointment, Customer, Invoice, Product
from aiuda_core.security import crypto

TODAY = date(2026, 7, 7)
DATA = Path(__file__).parent / "data"


def _serve(monkeypatch, payload=None, error=None):
    """urlopen falso: sirve `payload` como JSON (o lanza `error`). Registra (url, headers)."""
    llamadas = []

    @contextmanager
    def opener(req, timeout=15):
        llamadas.append((req.full_url, {k.lower(): v for k, v in req.headers.items()}))
        if error is not None:
            raise error
        yield io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(custom_api.urllib.request, "urlopen", opener)
    return llamadas


def _cifrado(secreto: str) -> tuple[str, int]:
    ct, ver = crypto.encrypt(secreto)
    return base64.b64encode(ct).decode(), ver


def _fuente(**extra) -> dict:
    """Una conexión guardada como la deja el builder (ver api/custom_connectors.py)."""
    base = {
        "id": "abc123",
        "name": "Mi ERP",
        "cap": "directorio_clientes",
        "base_url": "https://mi-erp.mx/api",
        "list_path": "clientes",
        "root": "data.clientes",
        "auth_type": "header",
        "auth_header": "X-API-Key",
        "secret_ct": "",
        "secret_ver": 0,
        "mapping": {
            "name": "razon_social",
            "phone": "contacto.celular",
            "email": "contacto.correo",
            "external_id": "id",
        },
    }
    base.update(extra)
    return base


def _config(tenant, session, *fuentes) -> None:
    tenant.config = {**(tenant.config or {}), "custom_sources": list(fuentes)}
    session.flush()


# ---------------------------------------------------------------------------
# Contrato: respuesta grabada → entidades con procedencia
# ---------------------------------------------------------------------------


def test_contrato_directorio_respuesta_grabada(session, tenant, monkeypatch):
    grabada = json.loads((DATA / "custom_api_clientes.json").read_text())
    ct, ver = _cifrado("clave-del-erp")
    _config(tenant, session, _fuente(secret_ct=ct, secret_ver=ver))
    llamadas = _serve(monkeypatch, grabada)

    report = sync_custom(session, tenant, today=TODAY)

    assert report.clientes_importados == 3
    assert report.fuentes == ["Mi ERP"] and report.avisos == []
    # El secreto guardado se descifró y viajó en el header declarado.
    assert llamadas[0][1]["x-api-key"] == "clave-del-erp"
    assert llamadas[0][0] == "https://mi-erp.mx/api/clientes"

    tornillo = session.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Ferretería El Tornillo SA")
    )
    # Teléfono normalizado (10 dígitos con espacios → 521+10) y correo mapeado.
    assert tornillo.phone == "5215512345678"
    assert tornillo.email == "pagos@eltornillo.mx"
    # Procedencia: el badge dice el nombre que el dueño le puso a SU conexión.
    assert tornillo.presence == {"Mi ERP": {"ref": "501"}}

    regia = session.scalar(select(Customer).where(Customer.name == "Constructora Regia"))
    assert regia.phone == "5218183561122"  # +52 81 ... → 521 + 10 dígitos

    # Idempotente: la re-corrida no duplica ni pisa.
    again = sync_custom(session, tenant, today=TODAY)
    assert again.clientes_importados == 0
    assert session.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all().__len__() == 3

    # El resultado queda registrado en la conexión (la lista dice la verdad).
    guardada = tenant.config["custom_sources"][0]
    assert guardada["last_sync_at"] and guardada["last_error"] == "" and guardada["last_count"] == 3


def test_contrato_cartera_respuesta_grabada(session, tenant, monkeypatch):
    grabada = json.loads((DATA / "custom_api_facturas.json").read_text())
    _config(
        tenant,
        session,
        _fuente(
            cap="cuentas_por_cobrar",
            list_path="facturas",
            root="result.items",
            auth_type="",
            auth_header="",
            mapping={
                "customer": "cliente.nombre",
                "phone": "cliente.celular",
                "folio": "folio",
                "amount": "saldo",
                "due_date": "vence",
                "external_id": "uid",
            },
        ),
    )
    _serve(monkeypatch, grabada)

    report = sync_custom(session, tenant, today=TODAY)
    assert report.pedidos_importados == 2  # la fila sin monto se omite: no se inventa

    inv = session.scalar(select(Invoice).where(Invoice.folio == "A-1091"))
    assert inv.amount == Decimal("12500.50")  # "$12,500.50" → Decimal
    assert inv.due_date == date(2026, 7, 20)
    assert inv.issued_date == TODAY
    assert inv.source == "custom"
    assert inv.presence == {"Mi ERP": {"ref": "fac-9001"}}
    assert inv.verified == "sin_verificar"  # una API arbitraria no es sistema de registro
    cliente = session.get(Customer, inv.customer_id)
    assert cliente.name == "Ferretería El Tornillo SA"
    assert cliente.phone == "5215512345678"  # el teléfono de la fila, normalizado

    inv2 = session.scalar(select(Invoice).where(Invoice.folio == "A-1102"))
    assert inv2.amount == Decimal("8300")
    assert inv2.due_date == date(2026, 7, 15)  # "15/07/2026" (DD/MM/YYYY) → date

    assert session.scalar(select(Invoice).where(Invoice.folio == "A-1110")) is None

    # Re-corrida: no duplica, la presencia sigue.
    again = sync_custom(session, tenant, today=TODAY)
    assert again.pedidos_importados == 0
    assert len(session.scalars(select(Invoice).where(Invoice.tenant_id == tenant.id)).all()) == 2


def test_catalogo_actualiza_por_external_id(session, tenant, monkeypatch):
    fuente = _fuente(
        cap="catalogo_productos",
        list_path="productos",
        root="",
        auth_type="",
        auth_header="",
        mapping={"name": "nombre", "sku": "clave", "price": "precio", "stock": "existencia", "external_id": "id"},
    )
    _config(tenant, session, fuente)
    _serve(monkeypatch, [{"id": 7, "nombre": "Tornillo 3/4", "clave": "T-34", "precio": "10.50", "existencia": 100}])
    report = sync_custom(session, tenant, today=TODAY)
    assert report.productos_importados == 1

    # Segunda corrida: mismo external_id, precio nuevo → actualiza, no duplica.
    _serve(monkeypatch, [{"id": 7, "nombre": "Tornillo 3/4 galv.", "clave": "T-34", "precio": "12.00", "existencia": 80}])
    again = sync_custom(session, tenant, today=TODAY)
    assert again.productos_importados == 0
    productos = session.scalars(select(Product).where(Product.tenant_id == tenant.id)).all()
    assert len(productos) == 1
    assert productos[0].price == Decimal("12.00") and productos[0].stock == Decimal("80")
    assert productos[0].presence["Mi ERP"]["ref"] == "7"
    assert productos[0].source == "custom"


def test_dedupe_por_external_id_no_duplica_aunque_cambie_el_nombre(session, tenant, monkeypatch):
    _config(tenant, session, _fuente(auth_type="", auth_header="", root="", list_path=""))
    _serve(monkeypatch, [{"razon_social": "ACME SA", "id": 9, "contacto": {"celular": "", "correo": ""}}])
    sync_custom(session, tenant, today=TODAY)
    # La fuente renombró al cliente pero el external_id es el mismo: rellena, no duplica.
    _serve(monkeypatch, [{"razon_social": "ACME SA de CV", "id": 9, "contacto": {"celular": "5512345678", "correo": ""}}])
    report = sync_custom(session, tenant, today=TODAY)
    assert report.clientes_importados == 0
    clientes = session.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all()
    assert len(clientes) == 1
    assert clientes[0].phone == "5215512345678"  # el dato faltante se rellenó


def test_prospeccion_entra_como_prospecto(session, tenant, monkeypatch):
    _config(
        tenant, session,
        _fuente(cap="prospeccion", auth_type="", auth_header="", root="", list_path="",
                mapping={"name": "n", "phone": "t", "external_id": "id"}),
    )
    _serve(monkeypatch, [{"n": "Posible Cliente SA", "t": "8110001111", "id": 44}])
    report = sync_custom(session, tenant, today=TODAY)
    assert report.clientes_importados == 1
    p = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    assert p.kind == "prospecto" and p.meta.get("origen") == "Mi ERP"


def test_agenda_crea_citas(session, tenant, monkeypatch):
    _config(
        tenant, session,
        _fuente(cap="agenda", auth_type="", auth_header="", root="", list_path="",
                mapping={"title": "titulo", "starts_at": "inicio", "customer": "cliente", "external_id": "id"}),
    )
    _serve(monkeypatch, [{"titulo": "Entrega pedido", "inicio": "2026-07-09T10:30:00", "cliente": "ACME", "id": 3}])
    report = sync_custom(session, tenant, today=TODAY)
    assert report.citas_importadas == 1
    cita = session.scalar(select(Appointment).where(Appointment.tenant_id == tenant.id))
    assert cita.title == "Entrega pedido" and cita.source == "custom"
    assert cita.starts_at.isoformat() == "2026-07-09T10:30:00"
    # Idempotente por (título, inicio).
    _serve(monkeypatch, [{"titulo": "Entrega pedido", "inicio": "2026-07-09T10:30:00", "cliente": "ACME", "id": 3}])
    assert sync_custom(session, tenant, today=TODAY).citas_importadas == 0


# ---------------------------------------------------------------------------
# No-op honesto y guardas
# ---------------------------------------------------------------------------


def test_fuente_caida_es_noop_honesto(session, tenant, monkeypatch):
    _config(tenant, session, _fuente())
    _serve(monkeypatch, error=urllib.error.URLError("conexión rechazada"))

    report = sync_custom(session, tenant, today=TODAY)

    # No truena, no inventa: cero entidades y el porqué queda registrado.
    assert session.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all() == []
    assert len(report.avisos) == 1 and report.avisos[0].startswith("Mi ERP:")
    assert report.fuentes == []
    guardada = tenant.config["custom_sources"][0]
    assert "No se pudo conectar" in guardada["last_error"]
    assert guardada["last_count"] == 0 and guardada["last_sync_at"]


def test_secreto_ilegible_avisa_sin_tronar(session, tenant, monkeypatch):
    _config(tenant, session, _fuente(secret_ct=base64.b64encode(b"basura").decode(), secret_ver=99))
    llamadas = _serve(monkeypatch, {"data": {"clientes": []}})
    report = sync_custom(session, tenant, today=TODAY)
    assert len(report.avisos) == 1 and "descifrar" in report.avisos[0]
    assert llamadas == []  # sin clave legible ni siquiera se intenta el GET


def test_fuente_prefs_apaga_la_capacidad_elegida_en_otro_lado(session, tenant, monkeypatch):
    _config(tenant, session, _fuente(cap="cuentas_por_cobrar", mapping={"folio": "f", "amount": "a"}))
    llamadas = _serve(monkeypatch, [])
    report = sync_custom(session, tenant, today=TODAY, fuente_prefs={"cuentas_por_cobrar": "odoo"})
    # El dueño eligió Odoo para su cartera: la conexión a la medida no la pisa.
    assert llamadas == [] and report.fuentes == [] and report.avisos == []


def test_cap_sin_entidad_se_marca_honesta(session, tenant, monkeypatch):
    _config(tenant, session, _fuente(cap="expedientes"))
    llamadas = _serve(monkeypatch, [])
    report = sync_custom(session, tenant, today=TODAY)
    assert llamadas == []  # no hay entidad destino: ni se lee
    assert "aún no se ingesta" in tenant.config["custom_sources"][0]["last_error"]
    assert report.avisos == []  # es una limitación dicha, no un error de corrida


def test_nombre_que_choca_con_sistema_de_registro_no_hereda_verificacion(session, tenant, monkeypatch):
    _config(tenant, session, _fuente(name="odoo", auth_type="", auth_header="", root="", list_path="",
                                     mapping={"name": "n", "external_id": "id"}))
    _serve(monkeypatch, [{"n": "Cliente X", "id": 1}])
    sync_custom(session, tenant, today=TODAY)
    c = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    assert "odoo (a la medida)" in c.presence  # no se disfraza de Odoo real


def test_sync_fuentes_corre_la_ingesta_custom(session, tenant, monkeypatch):
    """El criterio maestro a nivel motor: una conexión creada por el usuario entra a la
    corrida normal (sync_fuentes) y produce clientes con su procedencia."""
    grabada = json.loads((DATA / "custom_api_clientes.json").read_text())
    ct, ver = _cifrado("clave")
    _config(tenant, session, _fuente(secret_ct=ct, secret_ver=ver))
    _serve(monkeypatch, grabada)

    report = sync_fuentes(session, tenant, today=TODAY)

    assert report.clientes_importados == 3
    assert "Mi ERP" in report.fuentes
    c = session.scalar(select(Customer).where(Customer.name == "Abarrotes Doña Mary"))
    assert c is not None and c.presence.get("Mi ERP", {}).get("ref") == "503"


# ---------------------------------------------------------------------------
# Normalización de tipos (unidad)
# ---------------------------------------------------------------------------


def test_to_decimal_tolerante():
    assert _to_decimal("$1,234.50") == Decimal("1234.50")
    assert _to_decimal(8300) == Decimal("8300")
    assert _to_decimal(10.5) == Decimal("10.5")
    assert _to_decimal("") is None
    assert _to_decimal(None) is None
    assert _to_decimal("no-numero") is None
    assert _to_decimal(True) is None  # un bool no es un monto


def test_to_date_tolerante():
    assert _to_date("2026-07-20") == date(2026, 7, 20)
    assert _to_date("2026-07-20T10:00:00-06:00") == date(2026, 7, 20)
    assert _to_date("15/07/2026") == date(2026, 7, 15)
    assert _to_date("") is None
    assert _to_date("35/99/2026") is None
