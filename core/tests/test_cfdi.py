"""Lector de CFDI: extrae datos fiscales del XML (robusto a namespace)."""

import pytest

from aiuda_core.cfdi import parse_cfdi

CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Folio="3" Fecha="2026-05-20T17:29:09" TipoDeComprobante="I"
  Moneda="MXN" SubTotal="100.00" Total="116.00">
  <cfdi:Emisor Rfc="XIA190128J61" Nombre="HANOVA CONSULTING" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="GOBM980902FL1" Nombre="JOSE MARIA GONZALEZ" UsoCFDI="G03"/>
  <cfdi:Conceptos>
    <cfdi:Concepto Descripcion="Servicio"/>
    <cfdi:Concepto Descripcion="Otro"/>
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="16.00"/>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="09136fba-e156-4f79-b482-37cc5285eb7d"
      FechaTimbrado="2026-05-20T17:29:10"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


def test_parse_cfdi_extrae_datos_fiscales():
    d = parse_cfdi(CFDI)
    # El UUID se normaliza a MAYÚSCULAS (la forma canónica del SAT): es la
    # identidad del comprobante y el dedupe de la bóveda depende de una sola forma.
    assert d["uuid"] == "09136FBA-E156-4F79-B482-37CC5285EB7D"
    assert d["version"] == "4.0"
    assert d["total"] == 116.0
    assert d["subtotal"] == 100.0
    assert d["iva"] == 16.0
    assert d["emisor"]["rfc"] == "XIA190128J61"
    assert d["emisor"]["nombre"] == "HANOVA CONSULTING"
    assert d["receptor"]["rfc"] == "GOBM980902FL1"
    assert d["conceptos"] == 2
    assert d["moneda"] == "MXN"


def test_parse_cfdi_acepta_bytes():
    d = parse_cfdi(CFDI.encode("utf-8"))
    assert d["uuid"]


def test_parse_cfdi_rechaza_no_cfdi():
    with pytest.raises(ValueError):
        parse_cfdi("<root><x/></root>")
    with pytest.raises(ValueError):
        parse_cfdi("no es xml {")


NOMINA = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:nomina12="http://www.sat.gob.mx/nomina12"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="NOMINA" Folio="10" Fecha="2026-09-18T19:08:10"
  TipoDeComprobante="N" MetodoPago="PUE" Moneda="MXN" Total="10892.25">
  <cfdi:Emisor Rfc="HCO250213281" Nombre="HANOVA CONSULTING" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XAXX010101000" Nombre="EMPLEADO DE PRUEBA" UsoCFDI="CN01"/>
  <cfdi:Conceptos><cfdi:Concepto Descripcion="Pago de nómina"/></cfdi:Conceptos>
  <cfdi:Complemento>
    <nomina12:Nomina Version="1.2" TipoNomina="O">
      <nomina12:Emisor RegistroPatronal="A1234567890"/>
      <nomina12:Receptor Curp="XEXX010101HNEXXXA4" NumEmpleado="1"/>
    </nomina12:Nomina>
    <tfd:TimbreFiscalDigital UUID="b78c124b-0000-4000-8000-000000000001"
      FechaTimbrado="2026-09-18T19:08:11"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


def test_emisor_y_receptor_son_los_del_comprobante_no_los_del_complemento():
    """Un recibo de nómina real trae nomina12:Emisor y nomina12:Receptor sin RFC:
    no deben pisar a los del comprobante (así llegaron los del SAT)."""
    d = parse_cfdi(NOMINA)
    assert d["tipo"] == "N"
    assert d["emisor"]["rfc"] == "HCO250213281"
    assert d["receptor"]["rfc"] == "XAXX010101000"
    assert d["receptor"]["nombre"] == "EMPLEADO DE PRUEBA"
