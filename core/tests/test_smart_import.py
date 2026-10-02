"""Importador universal: clasifica la hoja y la carga a su lugar."""

import json

from sqlalchemy import func, select

from aiuda_core.connectors.smart_import import smart_import
from aiuda_core.models import Appointment, Customer, Invoice, Product


class StubRunner:
    """ClaudeRunner falso: devuelve el tipo y el mapeo que le digamos, sin red."""

    def __init__(self, tipo: str, mapping: dict):
        self.tipo = tipo
        self.mapping = mapping

    def complete(self, system, user, model=None, role=None, task=None, max_tokens=None):
        if task == "clasificar_archivo":
            return json.dumps({"tipo": self.tipo, "confianza": 0.95})
        if task == "mapear_archivo":
            return json.dumps(self.mapping)
        return "{}"


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_detecta_y_carga_clientes(session, tenant):
    content = _csv("Nombre,Tel,Correo\nJuana Pérez,5512345678,juana@x.com\n")
    runner = StubRunner(
        "clientes",
        {"nombre": "Nombre", "telefono": "Tel", "correo": "Correo", "empresa": None},
    )
    report = smart_import(session, tenant.id, content, "mis_clientes.csv", runner)
    assert report.entity == "clientes"
    assert report.created == 1
    cust = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    assert cust.name == "Juana Pérez"
    assert cust.phone == "5215512345678"  # 10 dígitos -> formato WhatsApp
    assert cust.kind == "cliente"


def test_detecta_y_carga_productos(session, tenant):
    content = _csv("Producto,Clave,Precio,Stock\nAnillo oro,A-1,4500,3\nCadena,C-2,2200,5\n")
    runner = StubRunner(
        "productos",
        {
            "nombre": "Producto",
            "sku": "Clave",
            "precio": "Precio",
            "existencia": "Stock",
            "unidad": None,
        },
    )
    report = smart_import(session, tenant.id, content, "catalogo.csv", runner)
    assert report.entity == "productos"
    assert report.created == 2
    prod = session.scalar(select(Product).where(Product.sku == "A-1"))
    assert prod.name == "Anillo oro"
    assert float(prod.price) == 4500.0
    assert float(prod.stock) == 3.0


def test_detecta_y_carga_citas(session, tenant):
    content = _csv("Asunto,Cliente,Cuando\nValuación,Ana,2026-06-20 10:30\n")
    runner = StubRunner(
        "citas",
        {"titulo": "Asunto", "cliente": "Cliente", "fecha": "Cuando", "telefono": None, "notas": None},
    )
    report = smart_import(session, tenant.id, content, "agenda.csv", runner)
    assert report.entity == "citas"
    assert report.created == 1
    cita = session.scalar(select(Appointment).where(Appointment.tenant_id == tenant.id))
    assert cita.title == "Valuación"
    assert cita.starts_at.hour == 10 and cita.starts_at.minute == 30


def test_prospectos_van_a_customer_con_kind(session, tenant):
    content = _csv("Nombre,WhatsApp,Origen\nLuis Roca,5598765432,Feria Joyera\n")
    runner = StubRunner(
        "prospectos",
        {"nombre": "Nombre", "telefono": "WhatsApp", "origen": "Origen", "correo": None, "empresa": None},
    )
    report = smart_import(session, tenant.id, content, "prospectos.csv", runner)
    assert report.entity == "prospectos"
    assert report.created == 1
    p = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    assert p.kind == "prospecto"
    assert p.meta.get("origen") == "Feria Joyera"


def test_facturas_siguen_funcionando(session, tenant):
    content = _csv(
        "Folio,Cliente,Tel,Total,Vence\n"
        "F-100,Tienda Sol,5511112222,1500,2026-07-01\n"
    )
    runner = StubRunner(
        "facturas",
        {
            "folio": "Folio",
            "cliente": "Cliente",
            "telefono": "Tel",
            "monto": "Total",
            "fecha_vencimiento": "Vence",
            "fecha_emision": None,
        },
    )
    report = smart_import(session, tenant.id, content, "cartera.csv", runner)
    assert report.entity == "facturas"
    assert report.created == 1
    assert session.scalar(select(func.count(Invoice.id))) == 1


def test_resubir_no_duplica(session, tenant):
    content = _csv("Nombre,Tel\nJuana,5512345678\n")
    runner = StubRunner("clientes", {"nombre": "Nombre", "telefono": "Tel", "correo": None, "empresa": None})
    smart_import(session, tenant.id, content, "c.csv", runner)
    r2 = smart_import(session, tenant.id, content, "c.csv", runner)
    assert r2.created == 0 and r2.skipped == 1
    assert session.scalar(select(func.count(Customer.id))) == 1


def test_sin_telefono_se_carga_no_se_pierde(session, tenant):
    """Un cliente sin teléfono NO se pierde: se carga marcado 'sin contacto'."""
    content = _csv("Nombre,Tel\nSin Tel,\nCon Tel,5512345678\n")
    runner = StubRunner("clientes", {"nombre": "Nombre", "telefono": "Tel", "correo": None, "empresa": None})
    report = smart_import(session, tenant.id, content, "c.csv", runner)
    assert report.created == 2  # ambos cargados, ninguno perdido
    sin_tel = session.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Sin Tel")
    )
    assert sin_tel is not None and sin_tel.phone is None
    # Se informa (no es error duro) que aún no se les puede escribir.
    assert any("sin teléfono" in e for e in report.errors)


def test_sin_telefono_no_duplica_en_recarga(session, tenant):
    """Re-subir el mismo archivo deduplica los sin-teléfono por nombre."""
    content = _csv("Nombre,Tel\nAna Lopez,\nBeto Ruiz,\n")
    mapping = {"nombre": "Nombre", "telefono": "Tel", "correo": None, "empresa": None}
    smart_import(session, tenant.id, content, "c.csv", StubRunner("clientes", mapping))
    smart_import(session, tenant.id, content, "c.csv", StubRunner("clientes", mapping))
    total = session.scalar(
        select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant.id)
    )
    assert total == 2  # no se duplican


def test_encabezados_repetidos_no_se_pierden():
    """Dos columnas con el mismo nombre se conservan (la 2da se renombra)."""
    from aiuda_core.connectors.smart_import import read_table

    content = _csv("Empresa,Empresa,Tel\nAurora,Boutique,5512345678\n")
    headers, rows = read_table(content, "x.csv")
    assert headers == ["Empresa", "Empresa (2)", "Tel"]
    assert rows[0]["Empresa"] == "Aurora"
    assert rows[0]["Empresa (2)"] == "Boutique"  # no se colapsó


def test_tipo_desconocido_no_rompe(session, tenant):
    content = _csv("a,b\n1,2\n")
    runner = StubRunner("desconocido", {})
    report = smart_import(session, tenant.id, content, "x.csv", runner)
    assert report.entity == "desconocido"
    assert report.created == 0
    assert report.errors


def test_analyze_propone_tipo_y_mapeo():
    from aiuda_core.connectors.smart_import import analyze

    content = _csv("Nombre,Cel,RFC\nJuana,5512345678,PEPJ800101\n")
    runner = StubRunner("clientes", {"nombre": "Nombre", "telefono": "Cel", "correo": None, "empresa": None})
    res = analyze(content, "c.csv", runner)
    assert res["entity"] == "clientes"
    assert res["columns"] == ["Nombre", "Cel", "RFC"]
    assert res["mapping"]["nombre"] == "Nombre"
    assert "nombre" in res["fields"]
    assert res["row_count"] == 1


def test_analyze_respeta_tipo_forzado():
    from aiuda_core.connectors.smart_import import analyze

    content = _csv("Articulo,Precio\nAnillo,4500\n")
    # El usuario fuerza 'productos' aunque la IA diría otra cosa: no clasifica.
    runner = StubRunner("clientes", {"nombre": "Articulo", "precio": "Precio"})
    res = analyze(content, "x.csv", runner, entity="productos")
    assert res["entity"] == "productos"
    assert res["confidence"] == 1.0


def test_commit_guarda_extras(session, tenant):
    from aiuda_core.connectors.smart_import import commit

    content = _csv("Nombre,Cel,RFC,Zona\nJuana Pérez,5512345678,PEPJ800101,Norte\n")
    mapping = {"nombre": "Nombre", "telefono": "Cel"}
    report = commit(session, tenant.id, content, "c.csv", "clientes", mapping, ["RFC", "Zona"])
    assert report.created == 1
    c = session.scalar(select(Customer).where(Customer.tenant_id == tenant.id))
    assert c.meta.get("RFC") == "PEPJ800101"
    assert c.meta.get("Zona") == "Norte"


def test_commit_tipo_invalido_no_importa():
    from aiuda_core.connectors.smart_import import commit

    report = commit(None, "t", _csv("a,b\n1,2\n"), "x.csv", "desconocido", {}, [])
    assert report.created == 0
    assert report.errors


def test_commit_guarda_procedencia(session, tenant):
    """Cada registro recuerda de qué archivo y cuándo se subió (no solo 'Excel')."""
    from datetime import datetime

    from aiuda_core.connectors.smart_import import commit

    at = datetime(2026, 6, 15, 9, 30)
    inv_csv = _csv("Folio,Cliente,Tel,Total,Vence\nA-1,Tienda,5511112222,100,2026-07-01\n")
    commit(
        session, tenant.id, inv_csv, "cartera_junio.csv", "facturas",
        {"folio": "Folio", "cliente": "Cliente", "telefono": "Tel", "monto": "Total", "fecha_vencimiento": "Vence"},
        [], at,
    )
    inv = session.scalar(select(Invoice).where(Invoice.tenant_id == tenant.id))
    assert inv.presence["excel"]["file"] == "cartera_junio.csv"
    assert inv.presence["excel"]["at"].startswith("2026-06-15")

    cl_csv = _csv("Nombre,Tel\nAna,5598765432\n")
    commit(
        session, tenant.id, cl_csv, "clientes_junio.csv", "clientes",
        {"nombre": "Nombre", "telefono": "Tel"}, [], at,
    )
    ana = session.scalar(select(Customer).where(Customer.name == "Ana"))
    assert ana.presence["excel"]["file"] == "clientes_junio.csv"


# --- Nada de no-ops mudos --------------------------------------------------
#
# El camino más publicitado para el dueño no técnico es "sube tu Excel". Si no entra
# nada, tiene que decirle por qué: created=0, skipped=N, errors=[] lo dejaba mirando
# una pantalla que no hizo nada y no explicaba nada.


def test_commit_sin_mapeo_explica_en_vez_de_callarse(session, tenant):
    from aiuda_core.connectors.smart_import import commit

    contenido = _csv("Cliente,Telefono\nRefaccionaria del Golfo,2291234567\n")
    rep = commit(session, tenant.id, contenido, "clientes.csv", "clientes", {}, [])

    assert rep.created == 0
    assert rep.skipped == 1, "cuenta los renglones que no pudo cargar"
    assert rep.errors, "y NO se queda callado"
    assert "no quedó claro qué columna es cuál" in rep.errors[0]
    # El mensaje le sirve al dueño: nombra sus columnas y lo que falta decidir.
    assert "Cliente" in rep.errors[0] and "nombre" in rep.errors[0]


def test_commit_con_mapeo_si_carga(session, tenant):
    from aiuda_core.connectors.smart_import import commit

    contenido = _csv("Cliente,Telefono\nRefaccionaria del Golfo,2291234567\n")
    rep = commit(
        session, tenant.id, contenido, "clientes.csv", "clientes",
        {"nombre": "Cliente", "telefono": "Telefono"}, [],
    )
    assert rep.created == 1 and not rep.errors
    assert session.scalar(
        select(Customer).where(Customer.tenant_id == tenant.id, Customer.name == "Refaccionaria del Golfo")
    ) is not None


def test_si_no_entra_nada_siempre_hay_motivo(session, tenant):
    """Red de seguridad: aunque el ingestor no explique, el reporte explica."""
    from aiuda_core.connectors.smart_import import commit

    contenido = _csv("Cliente,Telefono\nRefaccionaria del Golfo,2291234567\n")
    mapeo = {"nombre": "Cliente", "telefono": "Telefono"}
    commit(session, tenant.id, contenido, "clientes.csv", "clientes", mapeo, [])
    # La segunda vez ya existe: skipped, y el dueño merece saberlo.
    rep = commit(session, tenant.id, contenido, "clientes.csv", "clientes", mapeo, [])
    assert rep.created == 0 and rep.skipped == 1
    assert rep.errors and "No se cargó ninguno" in rep.errors[0]
