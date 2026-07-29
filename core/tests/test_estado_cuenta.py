"""Lector de estados de cuenta bancarios en PDF.

Los PDFs de prueba son SINTÉTICOS (pdf_sintetico.py): misma geometría que los
estados reales de BBVA y Banorte contra los que se verificó el parser, con datos
inventados. Ningún dato financiero real entra al repo.

Qué se cubre:
- Parseo determinista de Banorte y BBVA: columnas por coordenada, saldo corrido,
  cuadre exacto contra los saldos declarados.
- El camino de IA para cualquier banco: esquema fijo, red anti-invención (un
  monto que no está en el texto se rechaza) y cuadre obligatorio.
- Importar a conciliación: solo depósitos, dedup por fecha + monto + referencia
  (dos rentas del mismo importe NO se pisan), re-importar no duplica, y un
  estado que no cuadra no importa nada.
"""

import json
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aiuda_core.models import Base, Payment, Tenant
from aiuda_core.connectors.estado_cuenta import (
    EstadoCuenta,
    EstadoNoCuadra,
    EstadoNoLegible,
    Movimiento,
    analizar,
    extraer_con_ia,
    importar_movimientos,
)

from pdf_sintetico import (
    MOVS_BANORTE,
    MOVS_BBVA,
    MOVS_GENERICO,
    construir_pdf,
    estado_banorte,
    estado_bbva,
    estado_generico,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture()
def tenant(session):
    t = Tenant(name="Prueba SA", owner_phone="5215500000000", evolution_instance="t")
    session.add(t)
    session.flush()
    return t


# --- Parseo determinista -----------------------------------------------------


def test_banorte_parsea_y_cuadra():
    est = analizar(estado_banorte(MOVS_BANORTE, 10000.00))
    assert est.metodo == "banorte"
    assert est.banco == "Banorte"
    assert len(est.movimientos) == 5
    assert est.saldo_inicial == 10000.00
    assert est.total_abonos == 20200.00
    assert est.total_cargos == 1588.50
    ok, dif = est.cuadre()
    assert ok and dif == 0.0
    # El sentido de cada movimiento sale de la columna Y se verifica con el saldo.
    primero = est.movimientos[0]
    assert primero.fecha == date(2026, 3, 3)
    assert primero.abono == 8500.00 and primero.cargo is None
    assert "TLAPALERIA" in primero.concepto
    assert est.periodo_etiqueta() == "marzo 2026"


def test_bbva_parsea_y_cuadra():
    est = analizar(estado_bbva(MOVS_BBVA, 25000.00))
    assert est.metodo == "bbva"
    assert est.banco == "BBVA"
    assert len(est.movimientos) == 4
    assert est.total_abonos == 23200.00
    assert est.total_cargos == 4711.50
    assert est.cuadre() == (True, 0.0)
    # Las fechas no traen año en la fila: sale del periodo declarado.
    assert est.movimientos[0].fecha == date(2026, 3, 4)


def test_devolucion_con_guion_final_cuenta_al_reves():
    # "1,240.50-" en la columna de retiros es una devolución: dinero que ENTRA.
    movs = [
        ("03-MAR-26", "PAGO PROVEEDOR", 1240.50, None),
        ("04-MAR-26", "DEV.SPEI CUENTA CANCELADA", -1240.50, None),
    ]
    est = analizar(estado_banorte(movs, 5000.00))
    assert est.cuadre() == (True, 0.0)
    dev = est.movimientos[1]
    assert dev.abono == 1240.50 and dev.cargo is None


def test_banorte_que_no_cuadra_lo_dice_y_no_finge(monkeypatch):
    # Saldo final falso: el parseo lee bien pero el estado NO cuadra. Sin IA
    # conectada se devuelve lo leído, marcado con honestidad.
    est = analizar(estado_banorte(MOVS_BANORTE, 10000.00, saldo_final=99999.99))
    ok, dif = est.cuadre()
    assert not ok
    assert any("no cuadró" in a for a in est.avisos)


def test_pdf_escaneado_se_rechaza_con_mensaje_claro():
    vacio = construir_pdf([[]])  # una página sin capa de texto
    with pytest.raises(EstadoNoLegible, match="escaneado"):
        analizar(vacio)


def test_pdf_roto_se_rechaza():
    with pytest.raises(EstadoNoLegible):
        analizar(b"esto no es un pdf")


# --- Camino de IA (cualquier banco) ------------------------------------------


class RunnerFijo:
    """Contesta el JSON que se le dé, como lo haría la IA del dueño."""

    def __init__(self, respuesta: dict):
        self.respuesta = respuesta

    def model_for(self, role):
        return "fake"

    def complete(self, system, user, *, task, model=None, role="redaccion", max_tokens=1024):
        assert task == "leer_estado_cuenta"
        return json.dumps(self.respuesta)


def _respuesta_generica() -> dict:
    return {
        "banco": "Banco Regional del Golfo",
        "moneda": "MXN",
        "periodo_inicio": "2026-03-01",
        "periodo_fin": "2026-03-31",
        "saldo_inicial": 7000.00,
        "saldo_final": 17650.00,
        "movimientos": [
            {"fecha": "2026-03-04", "concepto": "DEPOSITO CLIENTE FACTURA F-77",
             "referencia": "", "cargo": None, "abono": 12500.00},
            {"fecha": "2026-03-09", "concepto": "RETIRO PAGO NOMINA",
             "referencia": "", "cargo": 6200.00, "abono": None},
            {"fecha": "2026-03-16", "concepto": "DEPOSITO CLIENTE FACTURA F-81",
             "referencia": "", "cargo": None, "abono": 4350.00},
        ],
    }


def test_ia_estandariza_cualquier_banco():
    runner = RunnerFijo(_respuesta_generica())
    est = analizar(estado_generico(MOVS_GENERICO, 7000.00), runner=runner)
    assert est.metodo == "ia"
    assert est.banco == "Banco Regional del Golfo"
    assert len(est.movimientos) == 3
    assert est.cuadre() == (True, 0.0)


def test_ia_no_puede_inventar_montos():
    # La IA reporta un depósito que NO está en el PDF: se rechaza completo.
    respuesta = _respuesta_generica()
    respuesta["movimientos"][0]["abono"] = 99999.99
    respuesta["saldo_final"] = 105149.99
    runner = RunnerFijo(respuesta)
    with pytest.raises(EstadoNoLegible, match="NO están en el PDF"):
        analizar(estado_generico(MOVS_GENERICO, 7000.00), runner=runner)


def test_ia_que_no_cuadra_no_pasa_como_buena():
    # La IA "pierde" un movimiento: los totales ya no cuadran y la previa lo dice.
    respuesta = _respuesta_generica()
    respuesta["movimientos"] = respuesta["movimientos"][:2]
    runner = RunnerFijo(respuesta)
    est = analizar(estado_generico(MOVS_GENERICO, 7000.00), runner=runner)
    ok, dif = est.cuadre()
    assert not ok and abs(dif) == 4350.00


def test_ia_movimiento_ambiguo_se_rechaza():
    respuesta = _respuesta_generica()
    respuesta["movimientos"][0]["cargo"] = 12500.00  # cargo Y abono a la vez
    with pytest.raises(EstadoNoLegible, match="cargo o abono"):
        extraer_con_ia("12,500.00 6,200.00 4,350.00 7,000.00 17,650.00", RunnerFijo(respuesta))


def test_ia_respuesta_sin_estructura_se_rechaza():
    with pytest.raises(EstadoNoLegible, match="estructurar"):
        extraer_con_ia("texto", RunnerFijo({"cualquier": "cosa"}))


# --- Importar a conciliación -------------------------------------------------


def _estado(movs: list[Movimiento], saldo_inicial=0.0, saldo_final=None) -> EstadoCuenta:
    est = EstadoCuenta(banco="Banorte", metodo="banorte", movimientos=movs)
    est.saldo_inicial = saldo_inicial
    total = sum(m.abono or 0 for m in movs) - sum(m.cargo or 0 for m in movs)
    est.saldo_final = saldo_final if saldo_final is not None else round(saldo_inicial + total, 2)
    return est


def test_importar_solo_depositos_con_procedencia(session, tenant):
    est = _estado(
        [
            Movimiento(fecha=date(2026, 3, 3), concepto="RENTA LOCAL 4", abono=8500.00),
            Movimiento(fecha=date(2026, 3, 5), concepto="PAGO LUZ", cargo=1240.50),
        ]
    )
    r = importar_movimientos(session, tenant.id, est, "marzo.pdf")
    assert r == {
        "creados": 1, "omitidos": 0, "cargos_ignorados": 1,
        "banco": "Banorte", "periodo": "marzo 2026",
    }
    pago = session.scalar(select(Payment))
    assert float(pago.amount) == 8500.00
    assert pago.source == "banco"
    assert pago.status == "pendiente"
    assert pago.counterparty == "RENTA LOCAL 4"
    assert pago.meta["estado_cuenta"] == {
        "archivo": "marzo.pdf", "banco": "Banorte", "periodo": "marzo 2026",
    }


def test_dos_rentas_del_mismo_importe_no_se_pisan(session, tenant):
    # El bug de Belvo que NO se reproduce: dedup por monto pisaba dos rentas
    # iguales. Aquí la fecha (o la referencia) las distingue.
    est = _estado(
        [
            Movimiento(fecha=date(2026, 3, 3), concepto="RENTA LOCAL 4", abono=8500.00),
            Movimiento(fecha=date(2026, 3, 10), concepto="RENTA LOCAL 7", abono=8500.00),
        ]
    )
    r = importar_movimientos(session, tenant.id, est, "marzo.pdf")
    assert r["creados"] == 2
    # Incluso el mismo día y el mismo importe: concepto distinto = pago distinto.
    est2 = _estado(
        [
            Movimiento(fecha=date(2026, 4, 1), concepto="RENTA LOCAL 4", abono=8500.00),
            Movimiento(fecha=date(2026, 4, 1), concepto="RENTA LOCAL 7", abono=8500.00),
        ]
    )
    r2 = importar_movimientos(session, tenant.id, est2, "abril.pdf")
    assert r2["creados"] == 2
    assert len(session.scalars(select(Payment)).all()) == 4


def test_reimportar_el_mismo_estado_no_duplica(session, tenant):
    movs = [
        Movimiento(fecha=date(2026, 3, 3), concepto="RENTA LOCAL 4", abono=8500.00),
        Movimiento(fecha=date(2026, 3, 10), concepto="RENTA LOCAL 7", abono=8500.00),
    ]
    r1 = importar_movimientos(session, tenant.id, _estado(movs), "marzo.pdf")
    r2 = importar_movimientos(session, tenant.id, _estado(movs), "marzo.pdf")
    assert r1["creados"] == 2
    assert r2["creados"] == 0 and r2["omitidos"] == 2
    assert len(session.scalars(select(Payment)).all()) == 2


def test_gemelos_identicos_en_un_mismo_estado_son_dos_pagos(session, tenant):
    # Dos depósitos idénticos (fecha, monto y concepto iguales) en el MISMO
    # estado: son dos pagos de verdad y la referencia sintética los separa.
    movs = [
        Movimiento(fecha=date(2026, 3, 3), concepto="DEPOSITO EFECTIVO", abono=600.00),
        Movimiento(fecha=date(2026, 3, 3), concepto="DEPOSITO EFECTIVO", abono=600.00),
    ]
    r = importar_movimientos(session, tenant.id, _estado(movs), "marzo.pdf")
    assert r["creados"] == 2
    r2 = importar_movimientos(session, tenant.id, _estado(movs), "marzo.pdf")
    assert r2["creados"] == 0 and r2["omitidos"] == 2


def test_estado_que_no_cuadra_no_importa_nada(session, tenant):
    est = _estado(
        [Movimiento(fecha=date(2026, 3, 3), concepto="RENTA", abono=8500.00)],
        saldo_inicial=1000.00,
        saldo_final=99999.99,
    )
    with pytest.raises(EstadoNoCuadra, match="No importo nada a ciegas"):
        importar_movimientos(session, tenant.id, est, "marzo.pdf")
    assert session.scalars(select(Payment)).all() == []


def test_referencia_del_banco_manda_sobre_la_sintetica(session, tenant):
    movs = [
        Movimiento(
            fecha=date(2026, 3, 3), concepto="SPEI RECIBIDO",
            referencia="BNET01002603030012345678", abono=8500.00,
        )
    ]
    importar_movimientos(session, tenant.id, _estado(movs), "marzo.pdf")
    pago = session.scalar(select(Payment))
    assert pago.reference == "BNET01002603030012345678"
