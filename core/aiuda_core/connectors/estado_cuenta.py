"""Estados de cuenta bancarios en PDF: el papel que el banco ya le manda al dueño.

Un negocio sin open banking sí tiene su estado de cuenta de cada mes. Aquí se lee
ese PDF y los depósitos entran a la MISMA bandeja de conciliación que alimentan
Belvo o Stripe, con procedencia visible. Tres caminos:

1. BBVA y Banorte se parsean DETERMINISTA (verificados contra estados reales):
   las columnas cargo/abono/saldo se distinguen por coordenada de palabra y cada
   fila se verifica contra el saldo corrido. Sin IA, sin costo, sin invenciones.
2. Cualquier otro banco (o un BBVA/Banorte que no cuadre) se lee con la IA que
   el dueño ya conectó: el texto del PDF se le pasa y devuelve movimientos en un
   esquema fijo. Cada monto que la IA reporte se verifica contra el texto del
   PDF: un monto que no está en el papel NO se acepta.
3. Un PDF escaneado (pura imagen, sin capa de texto) se rechaza con honestidad:
   todavía no se puede leer.

Regla dura en todos los caminos: saldo inicial + depósitos - retiros tiene que
cuadrar con el saldo final. Si no cuadra, se le dice al dueño y NO se importa.
El humano ve la previa y aprueba antes de que entre nada (HITL, como todo aquí).
"""

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiuda_core.engine.llm import parse_json_block
from aiuda_core.engine.runner import ProviderRunner, make_runner
from aiuda_core.models import Payment

# Tolerancia del cuadre: un centavo. Los montos vienen con dos decimales del
# propio PDF; una diferencia mayor es un movimiento perdido o inventado.
_TOL = 0.01

# Distancia máxima (pt) entre el borde derecho de un monto y el de su encabezado
# de columna. Los números en descripción ("20.00 USD") quedan lejos y se ignoran.
_UMBRAL_COLUMNA = 40.0

MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}
MES_NOMBRE = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# El guion FINAL es convención bancaria de negativo: "12,194.00-" es una
# devolución (el monto regresa, en la columna contraria a su signo).
_MONTO_RE = re.compile(r"^\$?\d{1,3}(?:,\d{3})*\.\d{2}-?$")
_FECHA_BANORTE_RE = re.compile(r"^(\d{2})-([A-Z]{3})-(\d{2})(.*)$")
_FECHA_BBVA_RE = re.compile(r"^\d{2}/[A-Z]{3}$")


class EstadoNoLegible(ValueError):
    """El PDF no se puede leer (escaneado, cifrado, vacío). Mensaje para el dueño."""


class EstadoNoCuadra(ValueError):
    """Los movimientos no cuadran contra los saldos: no se importa a ciegas."""


@dataclass
class Movimiento:
    fecha: date
    concepto: str = ""
    referencia: str = ""
    cargo: float | None = None  # dinero que salió
    abono: float | None = None  # dinero que entró
    saldo: float | None = None  # saldo después del movimiento, si el PDF lo trae


@dataclass
class EstadoCuenta:
    banco: str = ""
    metodo: str = ""  # bbva | banorte | ia
    moneda: str = "MXN"
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    saldo_inicial: float | None = None
    saldo_final: float | None = None
    movimientos: list[Movimiento] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def total_abonos(self) -> float:
        return round(sum(m.abono or 0.0 for m in self.movimientos), 2)

    @property
    def total_cargos(self) -> float:
        return round(sum(m.cargo or 0.0 for m in self.movimientos), 2)

    def cuadre(self) -> tuple[bool, float]:
        """(cuadra, diferencia). Sin saldos declarados no hay contra qué cuadrar."""
        if self.saldo_inicial is None or self.saldo_final is None:
            return False, 0.0
        esperado = round(self.saldo_inicial + self.total_abonos - self.total_cargos, 2)
        diferencia = round(esperado - self.saldo_final, 2)
        return abs(diferencia) <= _TOL, diferencia

    def periodo_etiqueta(self) -> str:
        """"enero 2026": para la procedencia que ve el dueño."""
        ancla = self.periodo_fin or self.periodo_inicio
        if ancla is None and self.movimientos:
            ancla = max(m.fecha for m in self.movimientos)
        if ancla is None:
            return ""
        return f"{MES_NOMBRE[ancla.month]} {ancla.year}"


# --- Lectura del PDF (texto y palabras con coordenadas) ----------------------


def _abrir_pdf(content: bytes):
    import pdfplumber

    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise EstadoNoLegible(
            "No pude abrir el PDF. Verifica que sea el estado de cuenta tal como "
            "lo descargaste de tu banco (sin contraseña)."
        ) from exc


def _paginas_lineas(pdf) -> list[list[list[dict]]]:
    """Por página, las palabras agrupadas en renglones (por coordenada vertical),
    cada renglón ordenado de izquierda a derecha. La coordenada es lo que permite
    saber si un monto está en la columna de cargos o en la de abonos."""
    paginas = []
    for page in pdf.pages:
        words = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
        lineas: list[list[dict]] = []
        for w in words:
            if lineas and abs(w["top"] - lineas[-1][0]["top"]) <= 2.0:
                lineas[-1].append(w)
            else:
                lineas.append([w])
        paginas.append([sorted(ln, key=lambda w: w["x0"]) for ln in lineas])
    return paginas


def _texto_linea(linea: list[dict]) -> str:
    return " ".join(w["text"] for w in linea)


def _texto_completo(paginas: list[list[list[dict]]]) -> str:
    return "\n".join(
        _texto_linea(linea) for pagina in paginas for linea in pagina
    )


def _parse_monto(texto: str) -> float | None:
    if not _MONTO_RE.match(texto):
        return None
    valor = float(texto.lstrip("$").rstrip("-").replace(",", ""))
    return -valor if texto.endswith("-") else valor


def detectar_banco(texto: str) -> str | None:
    """Por la razón social del pie de página, que es inconfundible. No se usa la
    palabra "BBVA" a secas: un SPEI de Banorte también la menciona."""
    t = _sin_acentos(texto.upper())
    if "BANCO MERCANTIL DEL NORTE" in t:
        return "banorte"
    if "GRUPO FINANCIERO BBVA" in t or "BBVA MEXICO, S.A" in t:
        return "bbva"
    return None


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _clasificar_montos(
    linea: list[dict], columnas: dict[str, float]
) -> dict[str, float]:
    """Asigna cada palabra-monto del renglón a su columna por cercanía del borde
    derecho (los montos van alineados a la derecha bajo su encabezado). Lo que
    queda lejos de toda columna es un número de la descripción y se ignora."""
    encontrados: dict[str, float] = {}
    for w in linea:
        monto = _parse_monto(w["text"])
        if monto is None:
            continue
        col, dist = None, _UMBRAL_COLUMNA + 1
        for nombre, x1 in columnas.items():
            d = abs(w["x1"] - x1)
            if d < dist:
                col, dist = nombre, d
        if col is not None and dist <= _UMBRAL_COLUMNA and col not in encontrados:
            encontrados[col] = monto
    return encontrados


def _cargo_abono(montos: dict[str, float]) -> tuple[float | None, float | None]:
    """Cargo y abono de la fila, con la convención del guion final resuelta: un
    monto negativo en una columna es una devolución y cuenta en la contraria."""
    cargo, abono = montos.get("cargo"), montos.get("abono")
    if cargo is not None and cargo < 0:
        cargo, abono = None, -cargo
    elif abono is not None and abono < 0:
        abono, cargo = None, -abono
    return cargo, abono


def _referencia_de(texto_mov: str) -> str:
    """La clave de rastreo del SPEI si viene; es la referencia natural del banco."""
    m = re.search(r"CVE\.?\s*RAST(?:REO)?:?\s*([A-Z0-9]{8,})", texto_mov, re.IGNORECASE)
    return m.group(1) if m else ""


# --- Banorte (determinista, verificado con estados reales) -------------------


def _fecha_banorte(dd: str, mes: str, yy: str) -> date | None:
    if mes not in MESES:
        return None
    return date(2000 + int(yy), MESES[mes], int(dd))


def _totales_banorte(paginas) -> dict:
    """Del resumen de la página 1: saldo inicial, totales y saldo final."""
    totales: dict[str, float] = {}
    patrones = {
        "saldo_inicial": r"SALDO INICIAL DEL PERIODO\s+\$?\s*([\d,]+\.\d{2})",
        "depositos": r"TOTAL DE DEPOSITOS\s+\$?\s*([\d,]+\.\d{2})",
        "retiros": r"TOTAL DE RETIROS\s+\$?\s*([\d,]+\.\d{2})",
        "saldo_final": r"SALDO ACTUAL\s+\$?\s*([\d,]+\.\d{2})",
    }
    for pagina in paginas:
        for linea in pagina:
            texto = _sin_acentos(_texto_linea(linea).upper())
            for clave, patron in patrones.items():
                if clave in totales:
                    continue
                m = re.search(patron, texto)
                if m:
                    totales[clave] = float(m.group(1).replace(",", ""))
        if len(totales) == 4:
            break
    return totales


def _periodo(texto: str) -> tuple[date | None, date | None]:
    """El periodo declarado, en cualquiera de las dos formas que usan los bancos:
    "Del 01/Enero/2026 al 31/Enero/2026" (Banorte) o "DEL 01/01/2026 AL
    31/01/2026" (BBVA)."""
    t = _sin_acentos(texto.upper())
    m = re.search(
        r"DEL?\s+(\d{1,2})/([A-Z]+)/(\d{4})\s+AL\s+(\d{1,2})/([A-Z]+)/(\d{4})", t
    )
    if m:
        meses = {_sin_acentos(n.upper()): i for i, n in enumerate(MES_NOMBRE) if n}
        mi, mf = meses.get(m.group(2)), meses.get(m.group(5))
        if mi and mf:
            return (
                date(int(m.group(3)), mi, int(m.group(1))),
                date(int(m.group(6)), mf, int(m.group(4))),
            )
    m = re.search(r"DEL?\s+(\d{2})/(\d{2})/(\d{4})\s+AL\s+(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return (
            date(int(m.group(3)), int(m.group(2)), int(m.group(1))),
            date(int(m.group(6)), int(m.group(5)), int(m.group(4))),
        )
    return None, None


def _columnas_banorte(linea: list[dict]) -> dict[str, float] | None:
    """El renglón de encabezados de la tabla de movimientos, si es este renglón.
    Devuelve el borde derecho de cada columna: DEPOSITO -> abono, RETIRO -> cargo."""
    palabras = {_sin_acentos(w["text"].upper()).rstrip(":"): w for w in linea}
    if "DEPOSITO" in palabras and "RETIRO" in palabras and "SALDO" in palabras:
        return {
            "abono": palabras["DEPOSITO"]["x1"],
            "cargo": palabras["RETIRO"]["x1"],
            "saldo": palabras["SALDO"]["x1"],
        }
    return None


def parsear_banorte(paginas: list[list[list[dict]]]) -> EstadoCuenta:
    """Cuenta Enlace de Banorte. Cada fila trae su saldo: el saldo corrido
    verifica cada clasificación cargo/abono, fila por fila."""
    estado = EstadoCuenta(banco="Banorte", metodo="banorte")
    estado.periodo_inicio, estado.periodo_fin = _periodo(_texto_completo(paginas))
    totales = _totales_banorte(paginas)
    estado.saldo_inicial = totales.get("saldo_inicial")
    estado.saldo_final = totales.get("saldo_final")

    saldo_corrido: float | None = None
    mov_textos: list[str] = []  # texto acumulado del movimiento en curso (referencia)
    descuadres = 0

    def cerrar_movimiento():
        if estado.movimientos and mov_textos:
            estado.movimientos[-1].referencia = _referencia_de(" ".join(mov_textos))
            mov_textos.clear()

    for pagina in paginas:
        columnas: dict[str, float] | None = None
        for linea in pagina:
            if columnas is None:
                columnas = _columnas_banorte(linea)
                continue
            cabecera = _columnas_banorte(linea)
            if cabecera is not None:
                continue  # encabezado repetido (continuación)
            primero = linea[0]
            m = _FECHA_BANORTE_RE.match(primero["text"])
            texto = _texto_linea(linea)
            if m:
                cerrar_movimiento()
                fecha = _fecha_banorte(m.group(1), m.group(2), m.group(3))
                if fecha is None:
                    continue
                montos = _clasificar_montos(linea, columnas)
                if "SALDO ANTERIOR" in _sin_acentos(texto.upper()):
                    saldo_corrido = montos.get("saldo", saldo_corrido)
                    continue
                concepto_palabras = [m.group(4)] + [
                    w["text"]
                    for w in linea[1:]
                    if _parse_monto(w["text"]) is None
                    or abs(
                        min((abs(w["x1"] - x) for x in columnas.values()), default=1e9)
                    )
                    > _UMBRAL_COLUMNA
                ]
                cargo, abono = _cargo_abono(montos)
                mov = Movimiento(
                    fecha=fecha,
                    concepto=" ".join(p for p in concepto_palabras if p).strip(),
                    cargo=cargo,
                    abono=abono,
                    saldo=montos.get("saldo"),
                )
                # Verificación por saldo corrido: si la columna engañó (texto
                # encimado), el saldo delata el sentido real y se corrige.
                if saldo_corrido is not None and mov.saldo is not None:
                    esperado = round(
                        saldo_corrido + (mov.abono or 0) - (mov.cargo or 0), 2
                    )
                    if abs(esperado - mov.saldo) > _TOL:
                        monto = mov.abono if mov.abono is not None else mov.cargo
                        if monto is not None and abs(
                            round(saldo_corrido + monto, 2) - mov.saldo
                        ) <= _TOL:
                            mov.abono, mov.cargo = monto, None
                        elif monto is not None and abs(
                            round(saldo_corrido - monto, 2) - mov.saldo
                        ) <= _TOL:
                            mov.cargo, mov.abono = monto, None
                        else:
                            descuadres += 1
                if mov.saldo is not None:
                    saldo_corrido = mov.saldo
                estado.movimientos.append(mov)
                mov_textos.append(texto)
            elif estado.movimientos and primero["x0"] > 78:
                # Renglón de continuación (indentado): descripción larga del
                # movimiento anterior. El pie de página va al margen y no entra.
                mov_textos.append(texto)
                mov = estado.movimientos[-1]
                if len(mov.concepto) < 220:
                    mov.concepto = f"{mov.concepto} {texto}".strip()[:220]
    cerrar_movimiento()
    _cerrar_deterministico(estado, totales, descuadres)
    return estado


# --- BBVA (determinista, verificado con estados reales) ----------------------


def _totales_bbva(paginas) -> dict:
    totales: dict[str, float] = {}
    patrones = {
        "saldo_inicial": r"SALDO ANTERIOR\s+([\d,]+\.\d{2})",
        "n_abonos": r"ABONOS \(\+\)\s+(\d+)\s+[\d,]+\.\d{2}",
        "depositos": r"ABONOS \(\+\)\s+\d+\s+([\d,]+\.\d{2})",
        "n_cargos": r"CARGOS \(-\)\s+(\d+)\s+[\d,]+\.\d{2}",
        "retiros": r"CARGOS \(-\)\s+\d+\s+([\d,]+\.\d{2})",
        "saldo_final": r"SALDO FINAL \(\+\)\s+([\d,]+\.\d{2})",
    }
    for pagina in paginas:
        for linea in pagina:
            texto = _sin_acentos(_texto_linea(linea).upper())
            for clave, patron in patrones.items():
                if clave in totales:
                    continue
                m = re.search(patron, texto)
                if m:
                    totales[clave] = float(m.group(1).replace(",", ""))
        if len(totales) == len(patrones):
            break
    return totales


def _columnas_bbva(linea: list[dict]) -> dict[str, float] | None:
    """Encabezado de la tabla: CARGOS / ABONOS / OPERACION / LIQUIDACION."""
    cols: dict[str, float] = {}
    for w in linea:
        t = _sin_acentos(w["text"].upper())
        if t == "CARGOS":
            cols["cargo"] = w["x1"]
        elif t == "ABONOS":
            cols["abono"] = w["x1"]
        elif t.startswith("OPERACION"):
            cols["saldo"] = w["x1"]
        elif t.startswith("LIQUIDACION"):
            cols["saldo_liq"] = w["x1"]
    return cols if {"cargo", "abono"} <= set(cols) else None


def parsear_bbva(paginas: list[list[list[dict]]]) -> EstadoCuenta:
    """Cuenta Maestra de BBVA. Las filas no siempre traen saldo: el saldo de
    OPERACION aparece como cortes de caja y se usa para verificar el corrido."""
    estado = EstadoCuenta(banco="BBVA", metodo="bbva")
    estado.periodo_inicio, estado.periodo_fin = _periodo(_texto_completo(paginas))
    anio = (estado.periodo_fin or date.today()).year
    anio_inicio = (estado.periodo_inicio or estado.periodo_fin or date.today()).year
    totales = _totales_bbva(paginas)
    estado.saldo_inicial = totales.get("saldo_inicial")
    estado.saldo_final = totales.get("saldo_final")

    saldo_corrido = estado.saldo_inicial
    mov_textos: list[str] = []
    descuadres = 0

    def cerrar_movimiento():
        if estado.movimientos and mov_textos:
            estado.movimientos[-1].referencia = _referencia_de(" ".join(mov_textos))
            mov_textos.clear()

    for pagina in paginas:
        columnas: dict[str, float] | None = None
        for linea in pagina:
            if columnas is None:
                columnas = _columnas_bbva(linea)
                continue
            if _columnas_bbva(linea) is not None:
                continue
            primero = linea[0]
            texto = _texto_linea(linea)
            es_fecha = (
                len(linea) >= 2
                and _FECHA_BBVA_RE.match(primero["text"])
                and _FECHA_BBVA_RE.match(linea[1]["text"])
            )
            if es_fecha:
                cerrar_movimiento()
                dd, mes = primero["text"].split("/")
                if mes not in MESES:
                    continue
                # El año no viene en la fila: sale del periodo. Si el periodo
                # cruza de diciembre a enero, diciembre es del año inicial.
                a = anio_inicio if (anio_inicio != anio and MESES[mes] == 12) else anio
                fecha = date(a, MESES[mes], int(dd))
                montos = _clasificar_montos(linea, columnas)
                concepto = " ".join(
                    w["text"]
                    for w in linea[2:]
                    if _parse_monto(w["text"]) is None
                    or min((abs(w["x1"] - x) for x in columnas.values()), default=1e9)
                    > _UMBRAL_COLUMNA
                )
                cargo, abono = _cargo_abono(montos)
                mov = Movimiento(
                    fecha=fecha,
                    concepto=concepto.strip(),
                    cargo=cargo,
                    abono=abono,
                    saldo=montos.get("saldo"),
                )
                if saldo_corrido is not None:
                    saldo_corrido = round(
                        saldo_corrido + (mov.abono or 0) - (mov.cargo or 0), 2
                    )
                    if mov.saldo is not None and abs(saldo_corrido - mov.saldo) > _TOL:
                        # El corte de caja no coincide: ¿la fila está volteada?
                        monto = mov.abono if mov.abono is not None else mov.cargo
                        base = round(
                            saldo_corrido - (mov.abono or 0) + (mov.cargo or 0), 2
                        )
                        if monto is not None and abs(
                            round(base + monto, 2) - mov.saldo
                        ) <= _TOL:
                            mov.abono, mov.cargo = monto, None
                            saldo_corrido = mov.saldo
                        elif monto is not None and abs(
                            round(base - monto, 2) - mov.saldo
                        ) <= _TOL:
                            mov.cargo, mov.abono = monto, None
                            saldo_corrido = mov.saldo
                        else:
                            descuadres += 1
                estado.movimientos.append(mov)
                mov_textos.append(texto)
            elif estado.movimientos and primero["x0"] > 60:
                mov_textos.append(texto)
                mov = estado.movimientos[-1]
                if len(mov.concepto) < 220:
                    mov.concepto = f"{mov.concepto} {texto}".strip()[:220]
    cerrar_movimiento()
    if "n_abonos" in totales:
        n_abonos = sum(1 for m in estado.movimientos if m.abono is not None)
        n_cargos = sum(1 for m in estado.movimientos if m.cargo is not None)
        if n_abonos != int(totales["n_abonos"]) or n_cargos != int(totales["n_cargos"]):
            estado.avisos.append(
                f"El PDF declara {int(totales['n_abonos'])} abonos y "
                f"{int(totales['n_cargos'])} cargos; leí {n_abonos} y {n_cargos}."
            )
            descuadres += 1
    _cerrar_deterministico(estado, totales, descuadres)
    return estado


def _cerrar_deterministico(estado: EstadoCuenta, totales: dict, descuadres: int) -> None:
    """Verifica el parseo contra los totales que el propio PDF declara. Si algo
    no cuadra se dice; el que decide si cae a la IA es el orquestador."""
    if not estado.movimientos:
        estado.avisos.append("No encontré la tabla de movimientos en el PDF.")
        return
    if descuadres:
        estado.avisos.append(
            f"{descuadres} movimientos no cuadraron contra el saldo corrido."
        )
    # Los totales declarados son diagnóstico, no el juez: Banorte, por ejemplo,
    # separa comisiones del "Total de retiros" del resumen. El juez es el cuadre
    # contra saldo inicial y final; solo si ese falla se enseña la comparación.
    if not estado.cuadre()[0]:
        for clave, valor in (
            ("depósitos", estado.total_abonos),
            ("retiros", estado.total_cargos),
        ):
            declarado = totales.get("depositos" if clave == "depósitos" else clave)
            if declarado is not None and abs(declarado - valor) > _TOL:
                estado.avisos.append(
                    f"El PDF declara {clave} por ${declarado:,.2f}; leí ${valor:,.2f}."
                )


# --- Cualquier banco, con la IA del dueño ------------------------------------

_PROMPT_ESTADO = """\
Un negocio mexicano subió su estado de cuenta bancario en PDF. Este es el texto
extraído del PDF, tal cual:

{texto}

Extrae los datos EXACTOS del estado de cuenta. Reglas duras:
- NO inventes movimientos ni montos: todo debe venir del texto de arriba.
- cargo = dinero que SALIÓ de la cuenta; abono = dinero que ENTRÓ.
- Cada movimiento lleva exactamente uno de los dos (el otro va en null).
- referencia: la clave de rastreo o referencia del banco si viene; si no, "".
- Los montos van como número con dos decimales, sin signo, sin comas.
- saldo_inicial y saldo_final son los que el estado declara para el periodo.

Responde ÚNICAMENTE un objeto JSON con esta forma:
{{"banco": "nombre del banco", "moneda": "MXN",
 "periodo_inicio": "AAAA-MM-DD", "periodo_fin": "AAAA-MM-DD",
 "saldo_inicial": 0.00, "saldo_final": 0.00,
 "movimientos": [{{"fecha": "AAAA-MM-DD", "concepto": "...", "referencia": "",
   "cargo": null, "abono": 0.00}}]}}
"""

# Hasta dónde se le pasa texto a la IA. Un estado normal cabe sobrado; uno más
# largo se corta con aviso (mejor decirlo que mandar medio movimiento).
_MAX_TEXTO_IA = 60_000


def _monto_en_texto(monto: float, crudo: str, plano: str) -> bool:
    """¿El monto está de verdad en el PDF? Se busca con y sin separador de miles.
    Es la red anti-invención del camino de IA."""
    con_comas = f"{monto:,.2f}"
    simple = f"{monto:.2f}"
    return con_comas in crudo or simple in plano


def _fecha_iso(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def extraer_con_ia(texto: str, runner: ProviderRunner) -> EstadoCuenta:
    """Le pasa el texto del PDF a la IA del dueño y valida SU respuesta contra el
    propio texto: montos que no están en el papel se rechazan completos."""
    recortado = texto[:_MAX_TEXTO_IA]
    raw = runner.complete(
        system=(
            "Extraes datos de estados de cuenta bancarios mexicanos. "
            "Respondes solo JSON, sin comentarios."
        ),
        user=_PROMPT_ESTADO.format(texto=recortado),
        role="redaccion",
        task="leer_estado_cuenta",
        max_tokens=8000,
    )
    data = parse_json_block(raw)
    if not data or not isinstance(data.get("movimientos"), list) or not data["movimientos"]:
        raise EstadoNoLegible(
            "Tu IA no pudo estructurar este estado de cuenta. Verifica que el PDF "
            "sea el original del banco e inténtalo de nuevo."
        )
    estado = EstadoCuenta(
        banco=str(data.get("banco") or "tu banco")[:40],
        metodo="ia",
        moneda=str(data.get("moneda") or "MXN")[:8],
        periodo_inicio=_fecha_iso(data.get("periodo_inicio")),
        periodo_fin=_fecha_iso(data.get("periodo_fin")),
    )
    try:
        estado.saldo_inicial = round(float(data["saldo_inicial"]), 2)
        estado.saldo_final = round(float(data["saldo_final"]), 2)
    except (KeyError, TypeError, ValueError):
        raise EstadoNoLegible(
            "Tu IA no encontró el saldo inicial y final del periodo, y sin ellos "
            "no puedo verificar que los movimientos cuadren."
        ) from None

    crudo = texto  # tal cual, con comas
    plano = texto.replace(",", "")  # sin separador de miles
    inventados: list[str] = []
    for i, m in enumerate(data["movimientos"], start=1):
        fecha = _fecha_iso(m.get("fecha"))
        if fecha is None:
            raise EstadoNoLegible(f"El movimiento {i} trae una fecha ilegible.")
        cargo = m.get("cargo")
        abono = m.get("abono")
        try:
            cargo = round(float(cargo), 2) if cargo not in (None, "", 0) else None
            abono = round(float(abono), 2) if abono not in (None, "", 0) else None
        except (TypeError, ValueError):
            raise EstadoNoLegible(f"El movimiento {i} trae un monto ilegible.") from None
        if (cargo is None) == (abono is None):
            raise EstadoNoLegible(
                f"El movimiento {i} debe ser cargo o abono, no ambos ni ninguno."
            )
        monto = cargo if cargo is not None else abono
        if monto is not None and not _monto_en_texto(monto, crudo, plano):
            inventados.append(f"${monto:,.2f} ({str(m.get('concepto') or '')[:40]})")
        estado.movimientos.append(
            Movimiento(
                fecha=fecha,
                concepto=str(m.get("concepto") or "").strip()[:220],
                referencia=str(m.get("referencia") or "").strip()[:64],
                cargo=cargo,
                abono=abono,
            )
        )
    if inventados:
        raise EstadoNoLegible(
            "Tu IA reportó montos que NO están en el PDF: "
            + ", ".join(inventados[:3])
            + ". No importo nada así; vuelve a intentar."
        )
    for clave in ("saldo_inicial", "saldo_final"):
        valor = getattr(estado, clave)
        if valor is not None and valor != 0 and not _monto_en_texto(valor, crudo, plano):
            raise EstadoNoLegible(
                f"Tu IA reportó un {clave.replace('_', ' ')} (${valor:,.2f}) "
                "que no está en el PDF. No importo nada así."
            )
    if len(texto) > _MAX_TEXTO_IA:
        estado.avisos.append(
            "El PDF es muy largo y se leyó recortado; revisa que no falten movimientos."
        )
    return estado


# --- Orquestador -------------------------------------------------------------


def analizar(
    content: bytes, runner: ProviderRunner | None = None
) -> EstadoCuenta:
    """Lee el PDF y devuelve la previa: banco, periodo, saldos, movimientos y si
    cuadra. NO escribe nada; el dueño aprueba después. Determinista para BBVA y
    Banorte; la IA del dueño para lo demás y de respaldo si el parseo no cuadra."""
    with _abrir_pdf(content) as pdf:
        paginas = _paginas_lineas(pdf)
    texto = _texto_completo(paginas)
    if len(texto.strip()) < 40:
        raise EstadoNoLegible(
            "Este PDF parece escaneado (pura imagen, sin texto). Todavía no puedo "
            "leer estados escaneados: descarga el PDF original desde tu banca en "
            "línea e inténtalo con ese."
        )

    banco = detectar_banco(texto)
    estado: EstadoCuenta | None = None
    if banco == "banorte":
        estado = parsear_banorte(paginas)
    elif banco == "bbva":
        estado = parsear_bbva(paginas)

    if estado is not None and estado.movimientos and estado.cuadre()[0]:
        return estado

    # Sin banco conocido, o el parseo directo no cuadró: la IA del dueño.
    avisos_previos = list(estado.avisos) if estado is not None else []
    try:
        estado_ia = extraer_con_ia(texto, runner or make_runner(None))
    except EstadoNoLegible:
        if estado is not None and estado.movimientos:
            # Se enseña lo que sí se leyó, marcado como que no cuadra.
            return estado
        raise
    except Exception as exc:  # la IA no está conectada o falló: honesto
        if estado is not None and estado.movimientos:
            estado.avisos.append(
                "El parseo directo no cuadró y tu IA tampoco pudo leerlo."
            )
            return estado
        raise EstadoNoLegible(
            "Este banco se lee con tu IA y no pudo responder. Revisa tu proveedor "
            "de IA en la consola e inténtalo de nuevo."
        ) from exc
    if avisos_previos:
        estado_ia.avisos = avisos_previos + [
            "El parseo directo no cuadró; esta lectura la hizo tu IA."
        ] + estado_ia.avisos
    return estado_ia


# --- Importar a conciliación (tras la aprobación del dueño) ------------------


def _referencia_estable(mov: Movimiento, banco: str, repeticion: int) -> str:
    """Referencia sintética cuando el banco no dio una: estable entre subidas
    (mismo archivo dos veces no duplica) y distinta entre movimientos gemelos
    dentro del mismo estado (dos depósitos iguales el mismo día sí son dos)."""
    base = f"{banco}|{mov.fecha.isoformat()}|{(mov.abono or 0):.2f}|{mov.concepto[:80]}|{repeticion}"
    return "ec-" + hashlib.sha1(base.encode()).hexdigest()[:16]


def importar_movimientos(
    session: Session,
    tenant_id: str,
    estado: EstadoCuenta,
    archivo: str,
) -> dict:
    """Los DEPÓSITOS del estado aprobado entran como pagos por conciliar, por el
    mismo camino que Belvo/Stripe: el ayudante propone factura y el humano
    confirma. Los cargos no entran (no son cobros); solo se cuentan.

    Regla dura: si el estado no cuadra, aquí NO entra nada.
    Dedup por fecha + monto + referencia: dos rentas del mismo importe en fechas
    o referencias distintas son DOS pagos (no como el dedup por monto de Belvo)."""
    cuadra, diferencia = estado.cuadre()
    if not cuadra:
        raise EstadoNoCuadra(
            "Los movimientos no cuadran contra el saldo del estado "
            f"(diferencia de ${abs(diferencia):,.2f}). No importo nada a ciegas: "
            "revisa que el PDF esté completo."
        )
    origen = {
        "archivo": archivo,
        "banco": estado.banco,
        "periodo": estado.periodo_etiqueta(),
    }
    creados = omitidos = cargos = 0
    vistas: dict[str, int] = {}
    for mov in estado.movimientos:
        if mov.abono is None or mov.abono <= 0:
            if mov.cargo:
                cargos += 1
            continue
        ref = mov.referencia
        if not ref:
            llave = f"{mov.fecha}|{mov.abono:.2f}|{mov.concepto[:80]}"
            vistas[llave] = vistas.get(llave, 0) + 1
            ref = _referencia_estable(mov, estado.banco, vistas[llave])
        existe = session.scalar(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.paid_at == mov.fecha,
                Payment.amount == Decimal(f"{mov.abono:.2f}"),
                Payment.reference == ref[:128],
            )
        )
        if existe is not None:
            omitidos += 1
            continue
        session.add(
            Payment(
                tenant_id=tenant_id,
                amount=round(mov.abono, 2),
                currency=estado.moneda or "MXN",
                paid_at=mov.fecha,
                source="banco",
                reference=ref[:128],
                counterparty=(mov.concepto or None) and mov.concepto[:255],
                status="pendiente",
                meta={"estado_cuenta": origen},
            )
        )
        creados += 1
    session.flush()
    return {
        "creados": creados,
        "omitidos": omitidos,
        "cargos_ignorados": cargos,
        "banco": estado.banco,
        "periodo": origen["periodo"],
    }
