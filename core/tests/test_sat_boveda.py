"""La bóveda fiscal: importar CFDIs crea cartera SIN inflarla.

Reglas de producto que estos tests amarran (romperlas rompe el producto):
- Solo un ingreso (I) EMITIDO por una empresa del negocio y a crédito (PPD) es
  cuenta por cobrar. PUE se cobró al emitir: bóveda sí, cartera no.
- Un complemento de pago (P) NO es cartera nueva: abona o cierra su factura.
- Un egreso (E) resta de la factura que relaciona.
- Dedupe por UUID: re-subir no duplica.
- Hasta 3 empresas (RFCs) del mismo negocio; un CFDI entre dos de ellas es
  intercompañía: bóveda sí, cobranza no.
"""

from decimal import Decimal

from sqlalchemy import select

from aiuda_core.cfdi import parse_cfdi
from aiuda_core.engine.sync import importar_cfdis, sat_empresas
from aiuda_core.models import CfdiBoveda, Invoice

HANOVA = "HCO250213281"      # empresa 1: la S.A.
PERSONA = "GOBM980902FL1"    # empresa 2: la persona física
TERCERA = "LHE250604HT6"     # empresa 3
CLIENTE = "PIA210312BD3"     # un cliente de verdad (tercero)


def cfdi_xml(
    uuid: str,
    tipo: str = "I",
    metodo: str | None = "PPD",
    emisor: str = HANOVA,
    receptor: str = CLIENTE,
    total: str = "11600.00",
    serie: str = "A",
    folio: str = "1",
    relacionados: list[str] | None = None,
    pagos: list[tuple[str, str, str]] | None = None,  # (uuid, pagado, saldo)
) -> str:
    """Arma un CFDI 4.0 mínimo pero bien formado (timbre, emisor, receptor)."""
    metodo_attr = f'MetodoPago="{metodo}"' if metodo else ""
    rel = ""
    if relacionados:
        cuerpo = "".join(f'<cfdi:CfdiRelacionado UUID="{u}"/>' for u in relacionados)
        rel = f'<cfdi:CfdiRelacionados TipoRelacion="01">{cuerpo}</cfdi:CfdiRelacionados>'
    pago = ""
    if pagos:
        doctos = "".join(
            f'<pago20:DoctoRelacionado IdDocumento="{u}" ImpPagado="{p}" '
            f'ImpSaldoInsoluto="{s}"/>'
            for u, p, s in pagos
        )
        pago = (
            '<cfdi:Complemento><pago20:Pagos xmlns:pago20='
            '"http://www.sat.gob.mx/Pagos20" Version="2.0">'
            f'<pago20:Pago FechaPago="2026-06-20T10:00:00">{doctos}</pago20:Pago>'
            "</pago20:Pagos></cfdi:Complemento>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="{serie}" Folio="{folio}" Fecha="2026-06-10T11:30:13"
  TipoDeComprobante="{tipo}" {metodo_attr} Moneda="MXN" Total="{total}">
  {rel}
  <cfdi:Emisor Rfc="{emisor}" Nombre="Emisor {emisor}" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{receptor}" Nombre="Receptor {receptor}" UsoCFDI="G03"/>
  <cfdi:Conceptos><cfdi:Concepto Descripcion="Servicio"/></cfdi:Conceptos>
  {pago}
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="{uuid}" FechaTimbrado="2026-06-10T11:30:14"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


U1 = "AAAA0001-0000-4000-8000-000000000001"
U2 = "AAAA0002-0000-4000-8000-000000000002"
U3 = "AAAA0003-0000-4000-8000-000000000003"
U4 = "AAAA0004-0000-4000-8000-000000000004"


def con_empresas(tenant, *rfcs):
    tenant.config = {**(tenant.config or {}), "sat_empresas": [{"rfc": r} for r in rfcs]}
    return tenant


# ---------------------------------------------------------------- parse_cfdi


def test_parse_extrae_metodo_relacionados_y_pagos():
    d = parse_cfdi(cfdi_xml(U1, tipo="P", metodo=None, pagos=[(U2, "100", "0")]))
    assert d["tipo"] == "P"
    assert d["metodo_pago"] is None
    assert d["pagos"] == [
        {"id_documento": U2, "imp_pagado": 100.0, "imp_saldo_insoluto": 0.0}
    ]
    e = parse_cfdi(cfdi_xml(U3, tipo="E", relacionados=[U2]))
    assert e["relacionados"] == [{"uuid": U2, "tipo_relacion": "01"}]
    assert e["uuid"] == U3


def test_parse_normaliza_uuid_a_mayusculas():
    d = parse_cfdi(cfdi_xml(U1.lower()))
    assert d["uuid"] == U1


# ------------------------------------------------------------ cartera desde I


def test_ppd_emitida_crea_cuenta_por_cobrar(session, tenant):
    con_empresas(tenant, HANOVA)
    res = importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD")])
    assert res["facturas_creadas"] == 1
    inv = session.scalar(select(Invoice).where(Invoice.tenant_id == tenant.id))
    assert inv.status == "open"
    assert inv.source == "sat"
    assert inv.verified == "verificada"
    assert inv.folio == "A-1"
    assert inv.amount == Decimal("11600.00")
    assert inv.cfdi_xml and "Comprobante" in inv.cfdi_xml
    assert inv.cfdi["uuid"] == U1
    assert inv.meta["empresa_rfc"] == HANOVA
    assert "vencimiento_estimado" in inv.meta  # honesto: el CFDI no trae plazo
    assert (inv.due_date - inv.issued_date).days == 30


def test_pue_va_a_boveda_pero_no_infla_cartera(session, tenant):
    con_empresas(tenant, HANOVA)
    res = importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PUE")])
    assert res["nuevos"] == 1
    assert res["pue_en_boveda"] == 1
    assert res["facturas_creadas"] == 0
    assert session.scalar(select(Invoice)) is None


def test_complemento_de_pago_cierra_no_crea(session, tenant):
    con_empresas(tenant, HANOVA)
    lote = [
        cfdi_xml(U1, metodo="PPD"),
        cfdi_xml(U2, tipo="P", metodo=None, serie="CP", folio="9",
                 pagos=[(U1, "11600.00", "0")]),
    ]
    res = importar_cfdis(session, tenant, lote)
    assert res["facturas_creadas"] == 1
    assert res["pagos_aplicados"] == 1
    invoices = session.scalars(select(Invoice)).all()
    assert len(invoices) == 1  # el P jamás es cuenta nueva
    assert invoices[0].status == "paid"
    assert invoices[0].paid_source == "sat"
    assert invoices[0].meta["abonos"][0]["uuid_pago"] == U2


def test_abono_parcial_deja_el_saldo_vigente(session, tenant):
    con_empresas(tenant, HANOVA)
    importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD")])
    importar_cfdis(
        session, tenant,
        [cfdi_xml(U2, tipo="P", metodo=None, pagos=[(U1, "5000.00", "6600.00")])],
    )
    inv = session.scalar(select(Invoice))
    assert inv.status == "open"
    assert inv.amount == Decimal("6600.00")


def test_egreso_resta_y_en_cero_cancela(session, tenant):
    con_empresas(tenant, HANOVA)
    importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD", total="1000.00")])
    res = importar_cfdis(
        session, tenant,
        [cfdi_xml(U2, tipo="E", total="400.00", relacionados=[U1])],
    )
    assert res["egresos_aplicados"] == 1
    inv = session.scalar(select(Invoice))
    assert inv.amount == Decimal("600.00") and inv.status == "open"
    importar_cfdis(
        session, tenant,
        [cfdi_xml(U3, tipo="E", total="600.00", relacionados=[U1])],
    )
    assert inv.status == "cancelled"
    assert inv.meta["cerrada_por"] == "nota de crédito"


def test_uuid_repetido_no_duplica(session, tenant):
    con_empresas(tenant, HANOVA)
    importar_cfdis(session, tenant, [cfdi_xml(U1)])
    res = importar_cfdis(session, tenant, [cfdi_xml(U1)])
    assert res["duplicados"] == 1 and res["nuevos"] == 0
    assert len(session.scalars(select(CfdiBoveda)).all()) == 1
    assert len(session.scalars(select(Invoice)).all()) == 1


def test_recibida_y_nomina_no_son_cartera(session, tenant):
    con_empresas(tenant, HANOVA)
    res = importar_cfdis(
        session, tenant,
        [
            cfdi_xml(U1, emisor=CLIENTE, receptor=HANOVA),      # un gasto del negocio
            cfdi_xml(U2, tipo="N", metodo=None, receptor=HANOVA, emisor=HANOVA),
        ],
    )
    assert res["recibidas"] == 1
    assert res["facturas_creadas"] == 0
    # la nómina la emite y recibe la misma empresa: queda en bóveda, jamás cartera
    assert session.scalar(select(Invoice)) is None


def test_folio_existente_vincula_en_vez_de_duplicar(session, tenant, invoice):
    con_empresas(tenant, HANOVA)
    invoice.folio = "A-1"
    session.flush()
    res = importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD")])
    assert res["facturas_vinculadas"] == 1 and res["facturas_creadas"] == 0
    session.refresh(invoice)
    assert invoice.cfdi["uuid"] == U1
    assert invoice.cfdi_xml
    assert "sat" in invoice.presence


def test_sin_empresas_no_inventa_cartera_y_avisa(session, tenant):
    res = importar_cfdis(session, tenant, [cfdi_xml(U1)])
    assert res["sin_clasificar"] == 1
    assert res["facturas_creadas"] == 0
    assert any("RFC" in a for a in res["avisos"])


# ------------------------------------------------- hasta 3 empresas del negocio


def test_sat_empresas_junta_manuales_y_efirma(session, tenant):
    con_empresas(tenant, HANOVA, PERSONA)
    empresas = sat_empresas(session, tenant)
    assert [e["rfc"] for e in empresas] == [HANOVA, PERSONA]
    assert all(not e["efirma"] for e in empresas)


def test_intercompania_no_cuenta_como_cobranza(session, tenant):
    """La S.A. le factura a la persona física: mismo negocio, dos RFCs. El CFDI
    baja dos veces (emitido por una, recibido por la otra) pero es UNA fila y
    CERO cartera: es dinero moviéndose dentro de la misma casa."""
    con_empresas(tenant, HANOVA, PERSONA, TERCERA)
    entre = cfdi_xml(U1, metodo="PPD", emisor=HANOVA, receptor=PERSONA)
    res1 = importar_cfdis(session, tenant, [entre])           # bajó como emitida
    res2 = importar_cfdis(session, tenant, [entre])           # bajó como recibida
    assert res1["intercompania"] == 1
    assert res2["duplicados"] == 1
    assert len(session.scalars(select(CfdiBoveda)).all()) == 1
    assert session.scalar(select(CfdiBoveda)).direccion == "intercompania"
    assert session.scalar(select(Invoice)) is None  # cero cuentas por cobrar


def test_agregar_empresa_reclasifica_a_intercompania(session, tenant):
    """Si la segunda empresa se registra DESPUÉS, lo que parecía una venta normal
    se reclasifica y su cuenta por cobrar se cierra: si se queda, la cartera miente."""
    con_empresas(tenant, HANOVA)
    importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD", receptor=PERSONA)])
    inv = session.scalar(select(Invoice))
    assert inv.status == "open"  # de momento parece cobranza real
    con_empresas(tenant, HANOVA, PERSONA)
    importar_cfdis(session, tenant, [cfdi_xml(U1, metodo="PPD", receptor=PERSONA)])
    fila = session.scalar(select(CfdiBoveda))
    assert fila.direccion == "intercompania"
    session.refresh(inv)
    assert inv.status == "cancelled"
    assert "intercompañía" in inv.meta["cerrada_por"]


def test_cada_cfdi_queda_etiquetado_con_su_empresa(session, tenant):
    con_empresas(tenant, HANOVA, PERSONA)
    importar_cfdis(
        session, tenant,
        [
            cfdi_xml(U1, metodo="PPD", emisor=HANOVA, folio="1"),
            cfdi_xml(U2, metodo="PPD", emisor=PERSONA, folio="2"),
            cfdi_xml(U3, emisor=CLIENTE, receptor=PERSONA, folio="3"),
        ],
    )
    filas = {f.uuid: f for f in session.scalars(select(CfdiBoveda)).all()}
    assert filas[U1].rfc_emisor == HANOVA and filas[U1].direccion == "emitida"
    assert filas[U2].rfc_emisor == PERSONA and filas[U2].direccion == "emitida"
    assert filas[U3].rfc_receptor == PERSONA and filas[U3].direccion == "recibida"
    por_empresa = {
        (i.meta or {}).get("empresa_rfc") for i in session.scalars(select(Invoice)).all()
    }
    assert por_empresa == {HANOVA, PERSONA}


def test_lote_desordenado_aplica_bien(session, tenant):
    """El ZIP del SAT no viene ordenado: el pago puede venir antes que su factura.
    El importador ordena I -> E -> P para que el lote cierre bien."""
    con_empresas(tenant, HANOVA)
    lote = [
        cfdi_xml(U2, tipo="P", metodo=None, pagos=[(U1, "11600.00", "0")]),
        cfdi_xml(U4, tipo="E", total="100.00", relacionados=[U3]),
        cfdi_xml(U1, metodo="PPD"),
        cfdi_xml(U3, metodo="PPD", serie="B", folio="7", total="500.00"),
    ]
    res = importar_cfdis(session, tenant, lote)
    assert res["facturas_creadas"] == 2
    assert res["pagos_aplicados"] == 1
    assert res["egresos_aplicados"] == 1
    por_folio = {i.folio: i for i in session.scalars(select(Invoice)).all()}
    assert por_folio["A-1"].status == "paid"
    assert por_folio["B-7"].amount == Decimal("400.00")


def test_no_cfdi_avisa_sin_tronar(session, tenant):
    res = importar_cfdis(session, tenant, ["<no>es cfdi</no>", "ni siquiera xml <"])
    assert res["cfdis"] == 0 and res["nuevos"] == 0
    assert len(res["avisos"]) == 2
