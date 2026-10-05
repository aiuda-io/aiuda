"""El ciclo de Descarga Masiva del SAT en sync_cfdi, con estado PERSISTIDO.

Lo que amarra: nunca se re-pide un periodo a ciegas (el 5002 agota las
solicitudes de por vida para esos parámetros) ni se repite una solicitud
idéntica (una al día por empresa y dirección), el incremental arranca en la
última fecha menos 2 días, corre emitidas y recibidas por empresa, y una
empresa rota no tumba a las otras. El cliente es fake (misma interfaz que
SatDescargaClient); el SAT vivo queda para scripts/prueba-sat.sh.
"""

import io
import zipfile
from datetime import date, timedelta

from sqlalchemy import select

from aiuda_core.engine.sync import sync_cfdi
from aiuda_core.models import CfdiBoveda, Invoice

HANOVA = "HCO250213281"
PERSONA = "GOBM980902FL1"
HOY = date(2026, 7, 28)
MANANA = HOY + timedelta(days=1)


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

    def __init__(self, rfc=HANOVA, verificaciones=None, paquetes=None, rechazos=None,
                 cancelados=None):
        self.rfc = rfc
        # Lo que contesta verificar para las solicitudes de cancelados (ids "C…").
        self.verificaciones_cancelados = list(cancelados or [])
        self.cancelados_pedidos: list[tuple[str, str, str]] = []
        self.solicitudes: list[tuple[str, str, str]] = []  # (scope, desde, hasta)
        self.verificaciones = list(verificaciones or [])
        self.paquetes = dict(paquetes or {})
        self.rechazos = list(rechazos or [])  # respuestas del SAT sin IdSolicitud
        self.descargas: list[str] = []
        self._contador = 0

    def solicitar(self, scope, desde, hasta):
        self.solicitudes.append((scope, desde.isoformat(), hasta.isoformat()))
        if self.rechazos:
            return self.rechazos.pop(0)
        self._contador += 1
        return {"IdSolicitud": f"S{self._contador}", "CodEstatus": "5000"}

    def solicitar_cancelados(self, scope, desde, hasta):
        self.cancelados_pedidos.append((scope, desde.isoformat(), hasta.isoformat()))
        return {"IdSolicitud": f"C{len(self.cancelados_pedidos)}", "CodEstatus": "5000"}

    def verificar(self, id_solicitud):
        if id_solicitud.startswith("C"):
            if self.verificaciones_cancelados:
                return self.verificaciones_cancelados.pop(0)
            return {"EstadoSolicitud": 2}
        if self.verificaciones:
            return self.verificaciones.pop(0)
        return {"EstadoSolicitud": 2}

    def descargar(self, id_paquete):
        self.descargas.append(id_paquete)
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
    # Antes aquí se afirmaba que la tercera corrida DEL MISMO DÍA volvía a pedir.
    # Ese era el defecto: la corrida es horaria y repetía la misma solicitud
    # varias veces al día. Ahora el mismo día no pide nada...
    pedidas = len(fake.solicitudes)
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert len(fake.solicitudes) == pedidas
    # ...y al día siguiente pide el incremental: última fecha MENOS 2 días.
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})
    assert fake.solicitudes[-1][1].startswith("2026-07-26")
    assert fake.solicitudes[-1][2].startswith("2026-07-29")


def test_un_dia_de_corridas_horarias_no_repite_ninguna_solicitud(session, tenant):
    """24 corridas el mismo día, con el SAT entregando a la primera: una sola
    solicitud por dirección. Y en una semana no hay dos solicitudes iguales."""
    fake = FakeSat()
    fake.verificar = lambda _id: {"EstadoSolicitud": 3, "IdsPaquetes": []}
    for dia in range(7):
        for _hora in range(24):
            sync_cfdi(
                session, tenant, today=HOY + timedelta(days=dia),
                sat_clients={HANOVA: fake},
            )
    assert len(fake.solicitudes) == 14  # 7 días x (emitidas, recibidas)
    assert len(set(fake.solicitudes)) == len(fake.solicitudes)


def test_duplicada_5005_espera_a_manana_sin_insistir(session, tenant):
    """El SAT rechaza la solicitud porque ya tiene una igual en curso. No es un
    error de aiuda: queda dicho en español y hoy no se insiste."""
    fake = FakeSat(
        rechazos=[
            {"CodEstatus": "5005", "Mensaje": "Solicitud duplicada"},
            {"CodEstatus": "5005", "Mensaje": "Solicitud duplicada"},
        ]
    )
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    st = _estado(tenant, HANOVA)["emitidas"]
    assert "solicitud" not in st
    assert "ya tiene en curso una solicitud igual" in st["aviso"]
    assert not any("no se pudo" in a or "5005" in a for a in r.avisos)
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert len(fake.solicitudes) == 2  # hoy ya no se vuelve a pedir
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})
    assert len(fake.solicitudes) == 4
    assert fake.solicitudes[2] != fake.solicitudes[0]  # fechas nuevas


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
    # Antes el aviso era el código crudo ("código 5002"); ahora es un estado en
    # español que también se guarda para la pantalla.
    assert "ya no acepta otra solicitud" in st["aviso"]
    assert "ya no acepta otra solicitud" in " ".join(r.avisos)
    assert not any("5002" in a or "no se pudo" in a for a in r.avisos)
    # el mismo periodo exacto no se vuelve a pedir aunque no haya pendiente
    periodo_agotado = st["agotadas"][0]
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert all(
        f"{s[1]}|{s[2]}" != periodo_agotado or s[0] != "emitidas"
        for s in fake.solicitudes[2:]
    )
    # mañana sí pide: mismo inicio (la fecha no avanzó) pero otra fecha final
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})
    emitidas = [s for s in fake.solicitudes if s[0] == "emitidas"]
    assert len(emitidas) == 2 and emitidas[0][2] != emitidas[1][2]


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
    assert r.avisos == []  # periodo vacío no es error
    assert "no tiene comprobantes nuevos" in st["emitidas"]["aviso"]


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


def test_un_cfdi_que_la_base_rechaza_no_envenena_la_corrida(session, tenant, monkeypatch):
    """Pasó con el SAT real: la importación tronó a media vuelta (IntegrityError)
    y la sesión quedó inservible. La vuelta se deshace sola, la solicitud
    pendiente se conserva y la otra dirección sigue."""
    from aiuda_core.engine import sync as sync_mod
    from aiuda_core.models import Customer

    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    session.add(Customer(tenant_id=tenant.id, name="Ya estaba", phone="5215500000000"))
    session.flush()
    xml = cfdi_basico(uuid="CCCC0009-0000-4000-8000-000000000009", emisor=HANOVA)
    fake = FakeSat(
        verificaciones=[
            {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1},
            {"EstadoSolicitud": 2},
        ],
        paquetes={"P1": _zip(xml)},
    )
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita

    def importar_que_choca(session, tenant, xmls, **kw):
        session.add(Customer(tenant_id=tenant.id, name="Choca", phone="5215500000000"))
        session.flush()  # viola la unicidad (tenant, phone)

    monkeypatch.setattr(sync_mod, "importar_cfdis", importar_que_choca)
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})

    assert any("emitidas" in a and "no se pudo" in a for a in r.avisos)
    st = _estado(tenant, HANOVA)
    assert st["emitidas"]["solicitud"]["id"] == "S1"  # se reintenta, no se pierde
    assert st["recibidas"]["solicitud"]["id"] == "S2"  # la otra dirección siguió
    # La sesión sigue sirviendo: lo de antes de la vuelta está intacto.
    assert [c.name for c in session.scalars(select(Customer)).all()].count("Choca") == 0


def test_si_la_importacion_falla_no_se_vuelve_a_descargar(session, tenant, monkeypatch):
    """El SAT limita las descargas de cada paquete. Antes, si importar tronaba,
    la vuelta siguiente verificaba y bajaba el mismo paquete otra vez. Ahora el
    ZIP queda guardado (cifrado) y el reintento importa de esa copia."""
    from aiuda_core.engine import sync as sync_mod
    from aiuda_core.models import SatPaquete

    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    xml = cfdi_basico(uuid="CCCC0010-0000-4000-8000-000000000010", emisor=HANOVA)
    paquete = _zip(xml)
    fake = FakeSat(
        verificaciones=[{"EstadoSolicitud": 3, "IdsPaquetes": ["P1"], "NumeroCFDIs": 1}],
        paquetes={"P1": paquete},
    )
    fake.verificadas = 0
    verificar = fake.verificar

    def contar(id_solicitud):
        fake.verificadas += 1
        return verificar(id_solicitud)

    fake.verificar = contar
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita

    importar = sync_mod.importar_cfdis

    def importar_que_truena(*a, **kw):
        raise RuntimeError("la base rechazó un CFDI")

    monkeypatch.setattr(sync_mod, "importar_cfdis", importar_que_truena)
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert any("emitidas" in a and "no se pudo" in a for a in r.avisos)
    guardado = session.scalars(select(SatPaquete)).all()
    assert [g.id_paquete for g in guardado] == ["P1"]
    assert paquete not in guardado[0].contenido  # cifrado, no el ZIP en claro
    assert _estado(tenant, HANOVA)["emitidas"]["solicitud"]["paquetes"] == ["P1"]
    assert session.scalar(select(Invoice)) is None

    # La vuelta siguiente, ya con la importación sana: ni verifica ni descarga.
    monkeypatch.setattr(sync_mod, "importar_cfdis", importar)
    verificadas = fake.verificadas
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert fake.descargas == ["P1"]  # una sola descarga en total
    assert fake.verificadas == verificadas + 1  # solo la de recibidas
    assert r.cfdis_importados == 1
    assert session.scalar(select(Invoice)).folio == "S-0010"
    assert session.scalars(select(SatPaquete)).all() == []  # se limpia al terminar
    st = _estado(tenant, HANOVA)["emitidas"]
    assert "solicitud" not in st and st["ultima_fecha"] == "2026-07-28"


def test_varios_paquetes_solo_se_baja_el_que_falta(session, tenant):
    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    uno = cfdi_basico(uuid="CCCC0011-0000-4000-8000-000000000011", emisor=HANOVA)
    dos = cfdi_basico(uuid="CCCC0012-0000-4000-8000-000000000012", emisor=HANOVA)
    lista = {"EstadoSolicitud": 3, "IdsPaquetes": ["P1", "P2"], "NumeroCFDIs": 2}
    en_proceso = {"EstadoSolicitud": 2}
    fake = FakeSat(
        verificaciones=[lista, en_proceso, lista, en_proceso],
        paquetes={"P1": _zip(uno)},  # P2 todavía no se puede bajar
    )
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert fake.descargas == ["P1", "P2"]  # P2 falló
    assert any("emitidas" in a and "no se pudo" in a for a in r.avisos)
    assert session.scalar(select(Invoice)) is None  # nada a medias

    fake.paquetes["P2"] = _zip(dos)
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert fake.descargas == ["P1", "P2", "P2"]  # P1 no se volvió a pedir
    assert r.cfdis_importados == 2


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
    # al día siguiente el traslape de 2 días vuelve a traer el mismo CFDI
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})  # re-solicita
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})  # re-baja P1
    assert fake.descargas == ["P1", "P1"]
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


# --- Cancelaciones: la descarga normal no avisa de lo que se canceló después --- #

ENCABEZADO = (
    "Uuid~RfcEmisor~NombreEmisor~RfcReceptor~NombreReceptor~PacCertifico~"
    "FechaEmision~FechaCertificacionSat~Monto~EfectoComprobante~Estatus~FechaCancelacion"
)


def _metadata(*filas: tuple[str, str, str]) -> bytes:
    """Un paquete de Metadata como lo entrega el SAT: (uuid, estatus, cancelación)."""
    lineas = [ENCABEZADO] + [
        f"{uuid}~{HANOVA}~Emisor~PIA210312BD3~Receptor~PAC010101AAA~"
        f"2026-07-01 10:00:00~2026-07-01 10:00:01~1160~I~{estatus}~{cuando}"
        for uuid, estatus, cuando in filas
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.txt", "\n".join(lineas))
    return buf.getvalue()


def _con_factura_abierta(session, tenant, uuid):
    """La bóveda con un PPD emitido ya importado y su factura abierta."""
    from aiuda_core.engine.sync import importar_cfdis

    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    importar_cfdis(session, tenant, [cfdi_basico(uuid=uuid, emisor=HANOVA)], today=HOY)
    inv = session.scalar(select(Invoice))
    assert inv.status == "open"
    return inv


def test_metadata_se_lee_por_las_orillas():
    from aiuda_core.connectors.sat_descarga import leer_metadata

    u1 = "dddd0001-0000-4000-8000-000000000001"
    u2 = "DDDD0002-0000-4000-8000-000000000002"
    linea_rara = (  # una razón social con el separador adentro recorre las columnas
        f"{u2}~{HANOVA}~Emisor~XAXX010101000~TIENDAS ~ Y MAS~PAC010101AAA~"
        "2026-07-02 10:00:00~2026-07-02 10:00:01~500~I~0~2026-07-05 09:00:00"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("m.txt", "\n".join([ENCABEZADO,
                    f"{u1}~{HANOVA}~E~R~R~P~f~f~1~I~1~", linea_rara, ""]))
    assert leer_metadata(buf.getvalue()) == [
        {"uuid": u1.upper(), "cancelado": False, "fecha_cancelacion": None},
        {"uuid": u2, "cancelado": True, "fecha_cancelacion": "2026-07-05 09:00:00"},
    ]


def test_factura_cancelada_despues_sale_de_la_cartera(session, tenant):
    """El caso real: un PPD que aiuda ya había descargado se cancela en el SAT.
    La descarga normal nunca lo dice y la factura se quedaba abierta para
    siempre, con aiuda cobrando algo que ya no existe."""
    from aiuda_core.models import Reminder

    uuid = "CCCC0020-0000-4000-8000-000000000020"
    inv = _con_factura_abierta(session, tenant, uuid)
    pendiente = Reminder(
        tenant_id=tenant.id, invoice_id=inv.id, bucket="vencida", tone="firme",
        message="Le recordamos su pago", status="pending_approval",
    )
    aprobado = Reminder(
        tenant_id=tenant.id, invoice_id=inv.id, bucket="vencida", tone="firme",
        message="Aprobado, esperando horario", status="approved",
    )
    enviado = Reminder(
        tenant_id=tenant.id, invoice_id=inv.id, bucket="vencida", tone="firme",
        message="Ya salió", status="sent",
    )
    session.add_all([pendiente, aprobado, enviado])
    session.flush()
    fake = FakeSat(
        cancelados=[{"EstadoSolicitud": 3, "IdsPaquetes": ["M1"], "NumeroCFDIs": 1}],
        paquetes={"M1": _metadata((uuid, "0", "2026-07-20 11:54:11"))},
    )

    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # pide la lista
    assert fake.cancelados_pedidos == [
        ("emitidas", "2026-07-01T00:00:00", "2026-07-28T23:59:59")
    ]
    assert inv.status == "open"
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # la aplica

    assert inv.status == "cancelled"
    assert inv.meta["cerrada_por"] == "cancelada en el SAT"
    assert inv.meta["cancelada_sat_el"] == "2026-07-20 11:54:11"
    assert inv.cfdi["status"] == "cancelado"
    fila = session.scalar(select(CfdiBoveda))
    assert fila.meta == {"cancelado": True, "cancelado_el": "2026-07-20 11:54:11"}
    assert pendiente.status == "rejected" and aprobado.status == "rejected"
    assert pendiente.meta["retirado"] == "La factura se canceló en el SAT."
    assert enviado.status == "sent"  # lo que ya salió no se reescribe
    assert any("S-0020" in a and "canceló en el SAT" in a for a in r.avisos)
    assert fake.descargas == ["M1"]


def test_la_lista_de_cancelados_se_pide_una_vez_al_dia(session, tenant):
    fake = FakeSat()
    fake.verificar = lambda _id: {"EstadoSolicitud": 3, "IdsPaquetes": []}
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert fake.cancelados_pedidos == []  # bóveda vacía: no hay qué cancelar
    _con_factura_abierta(session, tenant, "CCCC0021-0000-4000-8000-000000000021")
    for dia in range(3):
        for _hora in range(24):
            sync_cfdi(
                session, tenant, today=HOY + timedelta(days=dia),
                sat_clients={HANOVA: fake},
            )
    # una al día, solo de emitidas (de recibidas no hay nada en la bóveda)
    assert [p[0] for p in fake.cancelados_pedidos] == ["emitidas"] * 3
    assert len(set(fake.cancelados_pedidos)) == 3


def test_un_vigente_en_la_lista_no_cancela_nada(session, tenant):
    from aiuda_core.engine.sync import aplicar_cancelaciones

    uuid = "CCCC0022-0000-4000-8000-000000000022"
    inv = _con_factura_abierta(session, tenant, uuid)
    res = aplicar_cancelaciones(
        session, tenant,
        [
            {"uuid": uuid, "cancelado": False, "fecha_cancelacion": None},
            {"uuid": "FFFF0000-0000-4000-8000-000000000000", "cancelado": True,
             "fecha_cancelacion": "2026-07-20 10:00:00"},  # uno que aiuda no tiene
        ],
    )
    assert inv.status == "open" and res["cancelados"] == 0


def test_cancelar_dos_veces_no_reabre_ni_duplica(session, tenant):
    from aiuda_core.engine.sync import aplicar_cancelaciones, importar_cfdis

    uuid = "CCCC0023-0000-4000-8000-000000000023"
    inv = _con_factura_abierta(session, tenant, uuid)
    fila = {"uuid": uuid, "cancelado": True, "fecha_cancelacion": "2026-07-20 10:00:00"}
    assert aplicar_cancelaciones(session, tenant, [fila])["facturas_cerradas"] == 1
    assert aplicar_cancelaciones(session, tenant, [fila])["cancelados"] == 0
    # volver a subir el XML tampoco la regresa a la cartera
    importar_cfdis(session, tenant, [cfdi_basico(uuid=uuid, emisor=HANOVA)], today=HOY)
    assert inv.status == "cancelled"
    assert len(session.scalars(select(Invoice)).all()) == 1


def test_no_cierra_la_factura_de_otra_fuente_con_otro_comprobante(session, tenant):
    """Una factura de otra fuente que solo comparte folio con el CFDI cancelado
    (su comprobante adjunto es otro) no se cierra por esa cancelación."""
    from aiuda_core.engine.sync import aplicar_cancelaciones
    from aiuda_core.models import Customer

    uuid = "CCCC0024-0000-4000-8000-000000000024"
    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    cliente = Customer(tenant_id=tenant.id, name="Receptor")
    session.add(cliente)
    session.flush()
    otra = Invoice(
        tenant_id=tenant.id, customer_id=cliente.id, folio="S-0024", amount=1160,
        issued_date=date(2026, 7, 1), due_date=date(2026, 7, 31), source="odoo",
        cfdi={"uuid": "AAAA9999-0000-4000-8000-000000000000"},
    )
    session.add(otra)
    session.flush()
    from aiuda_core.engine.sync import importar_cfdis

    importar_cfdis(session, tenant, [cfdi_basico(uuid=uuid, emisor=HANOVA)], today=HOY)
    aplicar_cancelaciones(
        session, tenant,
        [{"uuid": uuid, "cancelado": True, "fecha_cancelacion": "2026-07-20 10:00:00"}],
    )
    assert otra.status == "open"
    assert session.scalar(select(CfdiBoveda)).meta["cancelado"] is True


# --- Un paquete que no se puede leer no detiene la dirección para siempre ------ #


def test_un_paquete_ilegible_se_suelta_y_se_pide_otro_dia(session, tenant):
    """El SAT entrega algo que no es un ZIP. No se guarda, se intenta bajar una
    vez más (el SAT entrega cada paquete dos veces) y se suelta: al día
    siguiente se pide con fechas nuevas. Antes esa dirección no volvía a pedir."""
    from aiuda_core.models import SatPaquete

    fake = FakeSat(paquetes={"P1": b""})
    fake.verificar = lambda _id: {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"]}
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert session.scalars(select(SatPaquete)).all() == []  # no se guarda basura
    assert _estado(tenant, HANOVA)["emitidas"]["solicitud"]["fallos"] == 1
    assert not any("zip" in a.lower() for a in r.avisos)  # nada en inglés al dueño
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    st = _estado(tenant, HANOVA)["emitidas"]
    assert "solicitud" not in st and "mañana" in st["aviso"]
    assert st.get("ultima_fecha") is None  # ese periodo no quedó cubierto
    descargas = len(fake.descargas)
    for _hora in range(5):  # el resto del día: ni pide ni baja
        sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    assert len(fake.descargas) == descargas
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})
    emitidas = [s for s in fake.solicitudes if s[0] == "emitidas"]
    assert len(emitidas) == 2 and emitidas[1][2].startswith("2026-07-29")


def test_una_importacion_que_siempre_falla_se_suelta(session, tenant, monkeypatch):
    """La copia guardada no se puede aplicar (llave cambiada, base que la
    rechaza). Tres intentos y se suelta: se borra la copia y otro día se pide de
    nuevo. Antes se reintentaba la misma copia para siempre."""
    from aiuda_core.engine import sync as sync_mod
    from aiuda_core.models import SatPaquete

    tenant.config = {"sat_empresas": [{"rfc": HANOVA}]}
    xml = cfdi_basico(uuid="CCCC0013-0000-4000-8000-000000000013", emisor=HANOVA)
    fake = FakeSat(paquetes={"P1": _zip(xml)})
    fake.verificar = lambda _id: {"EstadoSolicitud": 3, "IdsPaquetes": ["P1"]}

    def truena(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sync_mod, "importar_cfdis", truena)
    sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})  # solicita
    for intento in (1, 2):
        r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
        assert _estado(tenant, HANOVA)["emitidas"]["solicitud"]["fallos"] == intento
        assert len(session.scalars(select(SatPaquete)).all()) == 1
    assert not any("locked" in a for a in r.avisos)  # el error crudo va a la bitácora
    r = sync_cfdi(session, tenant, today=HOY, sat_clients={HANOVA: fake})
    st = _estado(tenant, HANOVA)["emitidas"]
    assert "solicitud" not in st and "mañana" in st["aviso"]
    assert session.scalars(select(SatPaquete)).all() == []
    assert any("emitidas" in a and "mañana" in a for a in r.avisos)
    assert fake.descargas == ["P1"]  # y nunca se volvió a bajar
    sync_cfdi(session, tenant, today=MANANA, sat_clients={HANOVA: fake})
    assert len([s for s in fake.solicitudes if s[0] == "emitidas"]) == 2
