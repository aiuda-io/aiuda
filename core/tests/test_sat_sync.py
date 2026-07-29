"""El ciclo de Descarga Masiva del SAT en sync_cfdi, con estado PERSISTIDO.

Lo que amarra: nunca se re-pide un periodo a ciegas (el 5002 agota las
solicitudes de por vida para esos parámetros), el incremental arranca en la
última fecha menos 2 días, corre emitidas y recibidas por empresa, y una
empresa rota no tumba a las otras. El cliente es fake (misma interfaz que
SatDescargaClient); el SAT vivo queda para scripts/prueba-sat.sh.
"""

import io
import zipfile
from datetime import date

from sqlalchemy import select

from aiuda_core.engine.sync import sync_cfdi
from aiuda_core.models import CfdiBoveda, Invoice

HANOVA = "HCO250213281"
PERSONA = "GOBM980902FL1"
HOY = date(2026, 7, 28)


def cfdi_basico(uuid: str, emisor: str = HANOVA, receptor: str = "PIA210312BD3") -> str:
    """Un ingreso PPD 4.0 mínimo, timbrado, emitido por `emisor`."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="S" Folio="{uuid[-4:]}" Fecha="2026-07-01T10:00:00"
  TipoDeComprobante="I" MetodoPago="PPD" Moneda="MXN" Total="1160.00">
  <cfdi:Emisor Rfc="{emisor}" Nombre="Emisor" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="{receptor}" Nombre="Receptor" UsoCFDI="G03"/>
  <cfdi:Conceptos><cfdi:Concepto Descripcion="Servicio"/></cfdi:Conceptos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital UUID="{uuid}" FechaTimbrado="2026-07-01T10:00:01"/>
  </cfdi:Complemento>
</cfdi:Comprobante>"""


def _zip(*xmls: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, x in enumerate(xmls):
            zf.writestr(f"{i}.xml", x)
    return buf.getvalue()


class FakeSat:
    """La interfaz de SatDescargaClient, con guion: qué contesta verificar y qué
    trae cada paquete."""

    def __init__(self, rfc=HANOVA, verificaciones=None, paquetes=None):
        self.rfc = rfc
        self.solicitudes: list[tuple[str, str, str]] = []  # (scope, desde, hasta)
        self.verificaciones = list(verificaciones or [])
        self.paquetes = dict(paquetes or {})
        self._contador = 0

    def solicitar(self, scope, desde, hasta):
        self._contador += 1
        self.solicitudes.append((scope, desde.isoformat(), hasta.isoformat()))
        return {"IdSolicitud": f"S{self._contador}", "CodEstatus": "5000"}

    def verificar(self, id_solicitud):
        if self.verificaciones:
            return self.verificaciones.pop(0)
        return {"EstadoSolicitud": 2}

    def descargar(self, id_paquete):
        return self.paquetes[id_paquete]


def _estado(tenant, rfc):
    return ((tenant.config or {}).get("sat_descarga") or {}).get(rfc) or {}


def test_primera_corrida_solicita_90_dias_y_persiste(session, tenant):
    fake = FakeSat()
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    # emitidas y recibidas, cada una con su solicitud
    assert [s[0] for s in fake.solicitudes] == ["emitidas", "recibidas"]
    assert fake.solicitudes[0][1].startswith("2026-04-29")  # hoy - 90 días
    st = _estado(tenant, HANOVA)
    assert st["emitidas"]["solicitud"]["id"] == "S1"
    assert st["recibidas"]["solicitud"]["id"] == "S2"


def test_no_repide_mientras_el_sat_prepara(session, tenant):
    fake = FakeSat()
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    pedidas = len(fake.solicitudes)
    # segunda corrida: el SAT sigue en proceso -> se verifica, NO se re-pide
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert len(fake.solicitudes) == pedidas
    assert _estado(tenant, HANOVA)["emitidas"]["solicitud"]["id"] == "S1"


def test_terminada_descarga_importa_y_avanza_la_fecha(session, tenant):
    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    xml = cfdi_basico(uuid="CCCC0001-0000-4000-8000-000000000001", emisor=HANOVA)
    fake = FakeSat(
        verificaciones=[
            {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1},
            {"EstadoSolicitud": 3, "IdsPaquetes": [], "NumeroCFDIs": 0},
        ],
        paquetes={"P1": _zip(xml)},
    )
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # baja
    assert r.cfdis_importados == 1
    assert r.pedidos_importados == 1  # el PPD emitido entró a cartera
    inv = session.scalar(select(Invoice))
    assert inv is not None and inv.source == "sat"
    st = _estado(tenant, HANOVA)["emitidas"]
    assert "solicitud" not in st
    assert st["ultima_fecha"] == "2026-07-28"
    # tercera corrida: incremental desde la última fecha MENOS 2 días
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert fake.solicitudes[-1][1].startswith("2026-07-26")


def test_5002_queda_registrado_y_jamas_se_repide_igual(session, tenant):
    fake = FakeSat(
        verificaciones=[
            {"EstadoSolicitud": 5, "CodigoEstadoSolicitud": "5002"},
        ]
    )
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    st = _estado(tenant, HANOVA)["emitidas"]
    assert len(st["agotadas"]) == 1
    assert "5002" in " ".join(r.avisos)
    # el mismo periodo exacto no se vuelve a pedir aunque no haya pendiente
    periodo_agotado = st["agotadas"][0]
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert all(
        f"{s[1]}|{s[2]}" != periodo_agotado or s[0] != "emitidas"
        for s in fake.solicitudes[2:]
    )


def test_5004_sin_cfdis_avanza_sin_ruido(session, tenant):
    fake = FakeSat(
        verificaciones=[
            {"EstadoSolicitud": 5, "CodigoEstadoSolicitud": "5004"},
            {"EstadoSolicitud": 5, "CodigoEstadoSolicitud": "5004"},
        ]
    )
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    st = _estado(tenant, HANOVA)
    assert st["emitidas"]["ultima_fecha"] == "2026-07-28"
    assert not any("5004" in a for a in r.avisos)  # periodo vacío no es error


def test_una_empresa_rota_no_tumba_a_la_otra(session, tenant):
    class Roto(FakeSat):
        def solicitar(self, *a):
            raise RuntimeError("el SAT no contesta")

    roto, sano = Roto(rfc=PERSONA), FakeSat(rfc=HANOVA)
    r = sync_cfdi(
        session, tenant, today=HOY, sat_clients={PERSONA: roto, HANOVA: sano}
    )
    assert len(sano.solicitudes) == 2  # la sana trabajó completa
    assert any(PERSONA in a and "no se pudo" in a for a in r.avisos)


def test_redescargar_el_mismo_paquete_no_duplica(session, tenant):
    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    xml = cfdi_basico(uuid="CCCC0002-0000-4000-8000-000000000002", emisor=HANOVA)
    verifs = [
        {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1},
        {"EstadoSolicitud": 3, "IdsPaquetes": [], "NumeroCFDIs": 0},
        {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1},
        {"EstadoSolicitud": 3, "IdsPaquetes": [], "NumeroCFDIs": 0},
    ]
    fake = FakeSat(verificaciones=verifs, paquetes={"P1": _zip(xml)})
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # re-solicita
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # re-baja P1
    assert len(session.scalars(select(CfdiBoveda)).all()) == 1
    assert len(session.scalars(select(Invoice)).all()) == 1


def test_respeta_al_dueno_que_eligio_otra_fuente_de_cartera(session, tenant):
    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    xml = cfdi_basico(uuid="CCCC0003-0000-4000-8000-000000000003", emisor=HANOVA)
    fake = FakeSat(
        verificaciones=[
            {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1},
            {"EstadoSolicitud": 3, "IdsPaquetes": [], "NumeroCFDIs": 0},
        ],
        paquetes={"P1": _zip(xml)},
    )
    prefs = {"cuentas_por_cobrar": "odoo"}
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake}, fuente_prefs=prefs)
    r = sync_cfdi(
        session, tenant, today=HOY, sat_clients={HANOVA: fake}, fuente_prefs=prefs
    )
    assert r.cfdis_importados == 1  # la bóveda sí
    assert session.scalar(select(Invoice)) is None  # la cartera del dueño no se pisa
