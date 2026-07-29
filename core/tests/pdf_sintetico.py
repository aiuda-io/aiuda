"""PDFs sintéticos de estados de cuenta, para pruebas.

Los estados de cuenta reales son datos financieros de una persona y NO entran al
repo. Aquí se FABRICAN PDFs con la misma geometría que los reales (columnas por
coordenada, fechas fusionadas, totales en la página 1, pie legal del banco) pero
con datos inventados. Un escritor de PDF mínimo alcanza: texto Helvetica
posicionado, que es lo único que el lector necesita ver.
"""

from datetime import date

# Anchos Helvetica (unidades/1000 del tamaño de fuente). Exactos para lo que va
# alineado a la derecha (montos); aproximados para el resto, que va a la izquierda.
_ANCHOS = {
    " ": 278, "$": 556, "%": 889, "(": 333, ")": 333, "*": 389, "+": 584,
    ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "=": 584,
}
_ANCHOS.update({d: 556 for d in "0123456789"})
_ANCHOS.update(
    dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
        667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
        722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611,
    ]))
)
_ANCHOS.update(
    dict(zip("abcdefghijklmnopqrstuvwxyz", [
        556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
        556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,
    ]))
)


def _ancho(texto: str, tam: float) -> float:
    return sum(_ANCHOS.get(c, 556) for c in texto) * tam / 1000.0


def _escapar(texto: str) -> str:
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


# Una celda: (x, y_desde_arriba, texto) o (x_derecho, y, texto, "der") para
# alinear el borde derecho del texto en x (como van los montos en un estado).
Celda = tuple


def construir_pdf(paginas: list[list[Celda]], tam: float = 7.0) -> bytes:
    """Un PDF real (abre en cualquier visor) con puro texto posicionado."""
    objetos: list[bytes] = []  # cuerpo de cada objeto, en orden 1..n
    n_paginas = len(paginas)
    kids = " ".join(f"{3 + i} 0 R" for i in range(n_paginas))
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objetos.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_paginas} >>".encode())
    contenido_base = 3 + n_paginas + 1  # tras catálogo, pages, páginas y fuente
    for i in range(n_paginas):
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {3 + n_paginas} 0 R >> >> "
                f"/Contents {contenido_base + i} 0 R >>"
            ).encode()
        )
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for celdas in paginas:
        partes = []
        for celda in celdas:
            x, y, texto = celda[0], celda[1], str(celda[2])
            if len(celda) > 3 and celda[3] == "der":
                x = x - _ancho(texto, tam)
            baseline = 792.0 - y - tam
            partes.append(
                f"BT /F1 {tam} Tf 1 0 0 1 {x:.2f} {baseline:.2f} Tm "
                f"({_escapar(texto)}) Tj ET"
            )
        stream = "\n".join(partes).encode("latin-1", errors="replace")
        objetos.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    salida = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, cuerpo in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode()
    salida += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(salida)


def _fmt(monto: float) -> str:
    # Convención bancaria: el negativo lleva el guion AL FINAL ("1,240.50-").
    if monto < 0:
        return f"{-monto:,.2f}-"
    return f"{monto:,.2f}"


# --- Banorte sintético -------------------------------------------------------

# Bordes derechos de columna, como en los estados reales de Banorte (con más
# aire entre columnas: el ancho Helvetica aquí es estimado y no deben tocarse).
_BAN_DEP, _BAN_RET, _BAN_SALDO = 390.0, 480.0, 570.0


def estado_banorte(
    movimientos: list[tuple[str, str, float | None, float | None]],
    saldo_inicial: float,
    saldo_final: float | None = None,
    periodo: str = "Del 01/Marzo/2026 al 31/Marzo/2026",
) -> bytes:
    """Un estado tipo Banorte con datos inventados. `movimientos` son tuplas
    (fecha "05-MAR-26", concepto, cargo, abono). Si no se da `saldo_final`, se
    calcula para que cuadre; darlo distinto fabrica un estado que NO cuadra."""
    total_dep = round(sum(a or 0 for _, _, _, a in movimientos), 2)
    total_ret = round(sum(c or 0 for _, _, c, _ in movimientos), 2)
    if saldo_final is None:
        saldo_final = round(saldo_inicial + total_dep - total_ret, 2)

    pagina1: list[Celda] = [
        (55, 30, "ESTADO DE CUENTA / CTA ENLACE NEGOCIO"),
        (55, 55, "PERSONA MORAL DE PRUEBA SA DE CV"),
        (300, 70, f"Periodo {periodo}"),
        (55, 110, "RESUMEN INTEGRAL"),
        (55, 130, "Resumen del periodo"),
        (55, 145, "Saldo inicial del periodo"), (300, 145, f"$ {_fmt(saldo_inicial)}"),
        (55, 160, "+ Total de depositos"), (300, 160, f"$ {_fmt(total_dep)}"),
        (55, 175, "- Total de retiros"), (300, 175, f"$ {_fmt(total_ret)}"),
        (55, 190, "Saldo actual"), (300, 190, f"$ {_fmt(saldo_final)}"),
        (55, 760, "Banco Mercantil del Norte S.A. Institucion de Banca Multiple Grupo Financiero Banorte"),
    ]

    filas: list[Celda] = [
        (59, 40, "FECHA"), (87, 40, "DESCRIPCION / ESTABLECIMIENTO"),
        (_BAN_DEP, 40, "MONTO DEL DEPOSITO", "der"),
        (_BAN_RET, 40, "MONTO DEL RETIRO", "der"),
        (_BAN_SALDO, 40, "SALDO", "der"),
    ]
    y = 55.0
    saldo = saldo_inicial
    filas.append((55, y, "01-MAR-26SALDO ANTERIOR"))
    filas.append((_BAN_SALDO, y, _fmt(saldo_inicial), "der"))
    y += 13
    for fecha, concepto, cargo, abono in movimientos:
        saldo = round(saldo + (abono or 0) - (cargo or 0), 2)
        filas.append((55, y, f"{fecha}{concepto}"))
        if abono is not None:
            filas.append((_BAN_DEP, y, _fmt(abono), "der"))
        if cargo is not None:
            filas.append((_BAN_RET, y, _fmt(cargo), "der"))
        filas.append((_BAN_SALDO, y, _fmt(saldo), "der"))
        y += 13
    filas.append((55, 760, "Banco Mercantil del Norte S.A. Institucion de Banca Multiple Grupo Financiero Banorte"))
    return construir_pdf([pagina1, filas])


# --- BBVA sintético ----------------------------------------------------------

_BBVA_CARGOS, _BBVA_ABONOS, _BBVA_OPER, _BBVA_LIQ = 406.0, 463.0, 526.0, 598.0
_PIE_BBVA = "BBVA MEXICO, S.A., INSTITUCION DE BANCA MULTIPLE, GRUPO FINANCIERO BBVA MEXICO"


def estado_bbva(
    movimientos: list[tuple[str, str, float | None, float | None]],
    saldo_inicial: float,
    saldo_final: float | None = None,
    periodo: str = "DEL 01/03/2026 AL 31/03/2026",
) -> bytes:
    """Un estado tipo BBVA con datos inventados. `movimientos` son tuplas
    (fecha "05/MAR", concepto, cargo, abono); el saldo de OPERACION se pinta
    cada dos filas, como cortes de caja (en los reales no viene en cada fila)."""
    abonos = [a for _, _, _, a in movimientos if a is not None]
    cargos = [c for _, _, c, _ in movimientos if c is not None]
    total_dep, total_ret = round(sum(abonos), 2), round(sum(cargos), 2)
    if saldo_final is None:
        saldo_final = round(saldo_inicial + total_dep - total_ret, 2)

    pagina1: list[Celda] = [
        (480, 25, "Estado de Cuenta"),
        (480, 35, "MAESTRA PYME BBVA"),
        (330, 60, "Periodo"), (430, 60, periodo),
        (33, 100, "Informacion Financiera"),
        (320, 115, "Saldo Anterior"), (560, 115, _fmt(saldo_inicial), "der"),
        (320, 130, "Depositos / Abonos (+)"), (460, 130, str(len(abonos))),
        (560, 130, _fmt(total_dep), "der"),
        (320, 145, "Retiros / Cargos (-)"), (460, 145, str(len(cargos))),
        (560, 145, _fmt(total_ret), "der"),
        (320, 160, "Saldo Final (+)"), (560, 160, _fmt(saldo_final), "der"),
        (16, 760, _PIE_BBVA),
    ]

    filas: list[Celda] = [
        (33, 30, "FECHA"), (517, 30, "SALDO"),
        (18, 42, "OPER"), (57, 42, "LIQ"), (82, 42, "DESCRIPCION"),
        (216, 42, "REFERENCIA"),
        (_BBVA_CARGOS, 42, "CARGOS", "der"), (_BBVA_ABONOS, 42, "ABONOS", "der"),
        (_BBVA_OPER, 42, "OPERACION", "der"), (_BBVA_LIQ, 42, "LIQUIDACION", "der"),
    ]
    y = 56.0
    saldo = saldo_inicial
    for i, (fecha, concepto, cargo, abono) in enumerate(movimientos):
        saldo = round(saldo + (abono or 0) - (cargo or 0), 2)
        filas.append((16, y, fecha))
        filas.append((51, y, fecha))
        filas.append((82, y, concepto))
        if cargo is not None:
            filas.append((_BBVA_CARGOS, y, _fmt(cargo), "der"))
        if abono is not None:
            filas.append((_BBVA_ABONOS, y, _fmt(abono), "der"))
        if i % 2 == 1 or i == len(movimientos) - 1:  # corte de caja intermitente
            filas.append((_BBVA_OPER, y, _fmt(saldo), "der"))
        y += 13
    filas.append((16, 760, _PIE_BBVA))
    return construir_pdf([pagina1, filas])


# --- Un banco cualquiera (camino de IA) --------------------------------------


def estado_generico(
    movimientos: list[tuple[str, str, float | None, float | None]],
    saldo_inicial: float,
    saldo_final: float | None = None,
    banco: str = "Banco Regional del Golfo",
) -> bytes:
    """Un estado de un banco que aiuda NO parsea directo: obliga el camino de la
    IA. `movimientos` son tuplas (fecha "2026-03-05", concepto, cargo, abono)."""
    total_dep = round(sum(a or 0 for _, _, _, a in movimientos), 2)
    total_ret = round(sum(c or 0 for _, _, c, _ in movimientos), 2)
    if saldo_final is None:
        saldo_final = round(saldo_inicial + total_dep - total_ret, 2)
    celdas: list[Celda] = [
        (55, 30, banco.upper()),
        (55, 45, "ESTADO DE CUENTA DEL 01/03/2026 AL 31/03/2026"),
        (55, 65, f"SALDO INICIAL: {_fmt(saldo_inicial)}"),
        (55, 80, f"SALDO FINAL: {_fmt(saldo_final)}"),
        (55, 100, "FECHA / CONCEPTO / RETIRO / DEPOSITO"),
    ]
    y = 115.0
    for fecha, concepto, cargo, abono in movimientos:
        celdas.append((55, y, fecha))
        celdas.append((120, y, concepto))
        if cargo is not None:
            celdas.append((420, y, _fmt(cargo), "der"))
        if abono is not None:
            celdas.append((500, y, _fmt(abono), "der"))
        y += 14
    return construir_pdf([celdas])


# --- Juegos de datos listos (los usan tests y el script E2E) -----------------

MOVS_BANORTE = [
    ("03-MAR-26", "SPEI RECIBIDO RENTA LOCAL 4 TLAPALERIA EL CLAVO", None, 8500.00),
    ("05-MAR-26", "PAGO SERVICIO LUZ CFE", 1240.50, None),
    ("10-MAR-26", "SPEI RECIBIDO RENTA LOCAL 7 ABARROTES DONA MARI", None, 8500.00),
    ("12-MAR-26", "COMISION MANEJO DE CUENTA", 348.00, None),
    ("18-MAR-26", "DEPOSITO EFECTIVO VENTA MOSTRADOR", None, 3200.00),
]

MOVS_BBVA = [
    ("04/MAR", "SPEI ENVIADO PROVEEDOR FERRETERO", 4640.00, None),
    ("07/MAR", "SPEI RECIBIDO FACTURA A-118 CONSTRUCTORA RIO", None, 17400.00),
    ("11/MAR", "PAGO CUENTA DE TERCERO ANTICIPO B-204", None, 5800.00),
    ("21/MAR", "SERV BANCA INTERNET", 71.50, None),
]

MOVS_GENERICO = [
    ("2026-03-04", "DEPOSITO CLIENTE FACTURA F-77", None, 12500.00),
    ("2026-03-09", "RETIRO PAGO NOMINA", 6200.00, None),
    ("2026-03-16", "DEPOSITO CLIENTE FACTURA F-81", None, 4350.00),
]


def guardar(ruta: str, contenido: bytes) -> None:
    with open(ruta, "wb") as f:
        f.write(contenido)


if __name__ == "__main__":
    # Uso desde el script E2E: python pdf_sintetico.py <carpeta destino>
    import sys

    destino = sys.argv[1] if len(sys.argv) > 1 else "."
    hoy = date.today().isoformat()
    guardar(f"{destino}/banorte-sintetico.pdf", estado_banorte(MOVS_BANORTE, 10000.00))
    guardar(f"{destino}/bbva-sintetico.pdf", estado_bbva(MOVS_BBVA, 25000.00))
    guardar(f"{destino}/generico-sintetico.pdf", estado_generico(MOVS_GENERICO, 7000.00))
    guardar(
        f"{destino}/banorte-no-cuadra.pdf",
        estado_banorte(MOVS_BANORTE, 10000.00, saldo_final=99999.99),
    )
    print(f"PDFs sintéticos en {destino} ({hoy})")
