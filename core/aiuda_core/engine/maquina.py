"""Qué computadora es esta y qué IA local le cabe.

El dueño de un negocio no sabe (ni tiene por qué saber) cuántos gigas pide un
modelo de 8 mil millones de parámetros. Este módulo mira la máquina de verdad
(chip, sistema, memoria), ve qué hay instalado (Ollama, modelos, CLIs de IA) y
traduce todo a una recomendación en su idioma: "este te queda bien", "este te
queda justo", "este no te cabe".

Reglas de la casa que aplican aquí:

- Solo stdlib. Nada de dependencias nuevas para leer un dato del sistema.
- Honestidad brutal: lo que no se puede detectar se devuelve ``None`` o
  "desconocido". Nunca se adivina un chip ni una cantidad de memoria.
- Sin HTTP propio: esto es dominio puro y testeable; el router del server lo
  expone en /v1/setup/maquina.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

# El Ollama local. Se pega a 127.0.0.1 (no "localhost") para no depender de que
# la resolución de nombres de la máquina esté sana.
OLLAMA_HOST = "http://127.0.0.1:11434"
TIMEOUT_S = 2.0

# Cuánta memoria puede dedicarle esta computadora a un modelo, como fracción de
# la RAM total. POR QUÉ 65%: en Apple Silicon la memoria es UNIFICADA (CPU y GPU
# comparten la misma RAM), así que el modelo compite con el sistema, el
# navegador y el propio aiuda; macOS además limita por default cuánta memoria
# puede "cablear" la GPU (iogpu.wired_limit ronda el 65-75% en equipos de 16-36
# GB). En PCs con GPU dedicada el número real sería el de la VRAM, que no
# podemos leer con stdlib: 65% de la RAM es una cota prudente que no promete de
# más. Es una heurística, no una medición: por eso el campo se llama
# "memoria_ia_gb" y no "memoria_disponible".
FRACCION_MEMORIA_IA = 0.65

# Qué tan holgado queda un modelo contra esa memoria. Debajo del 60% corre con
# espacio para el contexto y para que el dueño siga usando su computadora;
# hasta el 90% corre pero apretado (el equipo se va a sentir lento); arriba de
# ahí no cabe y decirlo es más útil que dejarlo intentar.
UMBRAL_BIEN = 0.60
UMBRAL_JUSTO = 0.90

# Nombre de modelo aceptable para pasárselo a `ollama pull`. Se valida aunque el
# comando corre sin shell: un nombre que empiece con "-" se colaría como bandera.
NOMBRE_MODELO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


@dataclass(frozen=True)
class ModeloLocal:
    """Un modelo del catálogo curado: nombre en Ollama, peso y para qué sirve."""

    nombre: str
    tam_gb: float
    para: str


# Catálogo curado, EN ORDEN DE PREFERENCIA (el primero que quepa bien es el
# recomendado). El filtro duro es TOOL CALLING: aiuda no chatea, sus ayudantes
# llaman herramientas (leer cartera, redactar recordatorio, registrar pago), y
# un modelo que no sabe llamar herramientas no sirve aquí por bonito que escriba.
# Por eso NO está la familia Gemma: en Ollama no trae plantilla de tools.
# Los tamaños son los que publica la librería de Ollama (GB decimales, igual que
# los reporta `ollama list`); el peso real varía por cuantización.
CATALOGO: tuple[ModeloLocal, ...] = (
    ModeloLocal(
        nombre="qwen2.5:32b",
        tam_gb=19.9,
        para="El más capaz de la lista: pide una computadora con mucha memoria.",
    ),
    ModeloLocal(
        nombre="qwen2.5:14b",
        tam_gb=9.0,
        para="El fuerte: entiende instrucciones largas y se equivoca menos con números.",
    ),
    ModeloLocal(
        nombre="llama3.1:8b",
        tam_gb=4.9,
        para="El equilibrado: redacta bien en español y sabe usar herramientas.",
    ),
    ModeloLocal(
        nombre="qwen2.5:7b",
        tam_gb=4.7,
        para="El rápido de todos los días: contesta ágil sin exigirle tanto al equipo.",
    ),
    ModeloLocal(
        nombre="mistral-nemo:12b",
        tam_gb=7.1,
        para="El de memoria larga: aguanta conversaciones y documentos grandes.",
    ),
    ModeloLocal(
        nombre="qwen2.5-coder:7b",
        tam_gb=4.7,
        para="El ordenado con datos: bueno para archivos, tablas y formatos.",
    ),
    ModeloLocal(
        nombre="llama3.2:3b",
        tam_gb=2.0,
        para="El ligero: cabe en casi cualquier computadora, aunque razona menos.",
    ),
)

ORDEN_CABE = {"bien": 0, "justo": 1, "desconocido": 2, "no": 3}


# --- La computadora -------------------------------------------------------------------


def _sysctl(clave: str) -> str | None:
    """Un dato del kernel de macOS. None si no es macOS o el comando falla."""
    if platform.system() != "Darwin":
        return None
    try:
        salida = subprocess.run(
            ["sysctl", "-n", clave], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    valor = (salida.stdout or "").strip()
    return valor or None


def chip() -> str | None:
    """El procesador, con el nombre que el dueño ve en "Acerca de esta Mac"."""
    sistema = platform.system()
    if sistema == "Darwin":
        return _sysctl("machdep.cpu.brand_string")
    if sistema == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for linea in f:
                    if linea.lower().startswith(("model name", "hardware")):
                        return linea.split(":", 1)[1].strip() or None
        except OSError:
            return None
        return None
    # Windows y el resto: platform.processor() a veces trae el modelo, a veces
    # una cadena vacía. Si viene vacía se dice que no se sabe.
    return (platform.processor() or "").strip() or None


def sistema_operativo() -> str | None:
    """El sistema y su versión, tal cual lo nombraría el dueño."""
    sistema = platform.system()
    if sistema == "Darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    if sistema == "Windows":
        return f"Windows {platform.release()}".strip()
    if sistema == "Linux":
        return f"Linux {platform.release()}".strip()
    return sistema or None


def ram_gb() -> float | None:
    """RAM total en GB (base 1024, como la anuncia el fabricante). None si no se puede leer."""
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        total = 0
    if not total:
        # macOS siempre tiene sysconf; esto cubre kernels raros y a Windows,
        # donde sin dependencias no hay forma limpia de leer la RAM.
        crudo = _sysctl("hw.memsize")
        total = int(crudo) if crudo and crudo.isdigit() else 0
    if not total:
        return None
    return round(total / (1024**3), 1)


def memoria_para_ia(ram: float | None) -> float | None:
    """Cuánta memoria se le puede dedicar a un modelo. None si no sabemos la RAM."""
    if not ram:
        return None
    return round(ram * FRACCION_MEMORIA_IA)


def equipo() -> dict:
    """Ficha honesta de esta computadora."""
    ram = ram_gb()
    return {
        "chip": chip(),
        "so": sistema_operativo(),
        "ram_gb": ram,
        "memoria_ia_gb": memoria_para_ia(ram),
        "arquitectura": platform.machine() or None,
    }


# --- Ollama ---------------------------------------------------------------------------

# Ollama se instala de dos formas: el binario en el PATH (brew, script oficial) o
# la app de escritorio, que a veces no deja el binario en el PATH del proceso que
# nos lanzó. Por eso, además del PATH, se miran las rutas conocidas.
RUTAS_OLLAMA = (
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
    os.path.expanduser("~/.ollama/bin/ollama"),
)


def ruta_ollama() -> str | None:
    """Dónde está el binario de Ollama. None = no lo encontramos."""
    en_path = shutil.which("ollama")
    if en_path:
        return en_path
    for ruta in RUTAS_OLLAMA:
        if os.path.isfile(ruta) and os.access(ruta, os.X_OK):
            return ruta
    return None


def _pedir_json(url: str) -> dict | None:
    """GET a la API local de Ollama. None = no contestó (no está corriendo)."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as res:
            return json.loads(res.read() or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _version_por_cli(ruta: str) -> str | None:
    """`ollama --version` imprime "ollama version is 0.5.4"."""
    try:
        salida = subprocess.run([ruta, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    texto = f"{salida.stdout or ''} {salida.stderr or ''}"
    m = re.search(r"version is ([0-9][\w.\-+]*)", texto)
    return m.group(1) if m else None


def modelos_de_tags(tags: dict | None) -> list[dict]:
    """Modelos instalados, tal como los reporta /api/tags. Sin Ollama corriendo, lista vacía."""
    if not tags:
        return []
    modelos = []
    for m in tags.get("models") or []:
        nombre = (m.get("name") or "").strip()
        if not nombre:
            continue
        tam = m.get("size")
        modelos.append(
            {
                "nombre": nombre,
                # GB decimales: es la unidad en la que Ollama publica y lista sus
                # modelos, y con la que se compara el catálogo.
                "tam_gb": round(tam / 1_000_000_000, 1) if isinstance(tam, (int, float)) else None,
            }
        )
    return sorted(modelos, key=lambda m: m["nombre"])


def detectar_ollama() -> tuple[dict, list[dict]]:
    """Estado de Ollama y los modelos que ya tiene bajados.

    Devuelve (ollama, modelos_instalados) juntos porque salen de la misma
    consulta: preguntar dos veces sería pegarle dos veces a la API.
    """
    ruta = ruta_ollama()
    tags = _pedir_json(f"{OLLAMA_HOST}/api/tags")
    corriendo = tags is not None
    version = None
    if corriendo:
        datos = _pedir_json(f"{OLLAMA_HOST}/api/version") or {}
        version = (datos.get("version") or "").strip() or None
    if version is None and ruta:
        version = _version_por_cli(ruta)
    return (
        {
            # Puede estar corriendo sin binario visible (app de escritorio) y
            # puede estar instalado sin correr (nunca lo abrieron). Se reportan
            # los dos hechos por separado, sin inventar uno a partir del otro.
            "instalado": bool(ruta) or corriendo,
            "corriendo": corriendo,
            "version": version,
            "ruta": ruta,
        },
        modelos_de_tags(tags),
    )


# --- Recomendación --------------------------------------------------------------------


def _normalizar(nombre: str) -> str:
    """Para Ollama, llama3.1 y llama3.1:latest son el mismo modelo."""
    nombre = (nombre or "").strip()
    return nombre if ":" in nombre else f"{nombre}:latest"


def como_cabe(tam_gb: float, memoria_ia_gb: float | None) -> str:
    """Qué tan holgado queda: bien, justo, no, o desconocido si no se leyó la memoria."""
    if not memoria_ia_gb:
        return "desconocido"
    proporcion = tam_gb / memoria_ia_gb
    if proporcion < UMBRAL_BIEN:
        return "bien"
    if proporcion < UMBRAL_JUSTO:
        return "justo"
    return "no"


def recomendar_modelos(
    memoria_ia_gb: float | None, instalados: list[str] | None = None
) -> list[dict]:
    """El catálogo ordenado para esta computadora: primero lo que le queda bien.

    Marca UNO como ``recomendado``: el mejor del catálogo que quepa bien. Si nada
    cabe bien, se marca el mejor que quepa justo; si nada cabe, ninguno (mentir
    con una recomendación imposible sería peor que no recomendar).
    """
    ya = {_normalizar(n) for n in (instalados or [])}
    lista = []
    for orden, modelo in enumerate(CATALOGO):
        lista.append(
            {
                "nombre": modelo.nombre,
                "tam_gb": modelo.tam_gb,
                "cabe": como_cabe(modelo.tam_gb, memoria_ia_gb),
                "instalado": _normalizar(modelo.nombre) in ya,
                "recomendado": False,
                "para": modelo.para,
                "_orden": orden,
            }
        )
    lista.sort(key=lambda m: (ORDEN_CABE.get(m["cabe"], 9), m["_orden"]))
    for cabida in ("bien", "justo"):
        elegido = next((m for m in lista if m["cabe"] == cabida), None)
        if elegido is not None:
            elegido["recomendado"] = True
            break
    for m in lista:
        m.pop("_orden", None)
    return lista


# --- CLIs de IA ya instalados ---------------------------------------------------------

# Los agentes de terminal que aiuda puede aprovechar como proveedor de IA: si el
# dueño ya paga Claude o ChatGPT y tiene su CLI, no necesita API key ni modelo local.
CLIS = ("claude", "codex")


def detectar_clis() -> dict:
    """Qué CLIs de IA puede ejecutar aiuda en esta computadora.

    No basta con el PATH: la app de escritorio arranca con el PATH mínimo de
    macOS, así que se buscan también los lugares donde estos CLIs de verdad se
    instalan (ver ``cli_runner.detectar``). Un alias o función de shell no
    cuenta: no es un binario que se pueda lanzar.
    """
    from aiuda_core.engine.cli_runner import detectar

    detectados = {}
    for nombre in CLIS:
        ruta = detectar(nombre)
        detectados[nombre] = {"instalado": ruta is not None, "ruta": ruta}
    return detectados


def detectar_maquina() -> dict:
    """Todo junto: el equipo, Ollama, lo instalado, lo recomendado y los CLIs."""
    eq = equipo()
    ollama, instalados = detectar_ollama()
    return {
        "equipo": eq,
        "ollama": ollama,
        "modelos_instalados": instalados,
        "recomendados": recomendar_modelos(eq["memoria_ia_gb"], [m["nombre"] for m in instalados]),
        "clis": detectar_clis(),
    }


# --- Descarga de un modelo ------------------------------------------------------------

# `ollama pull` pinta una barra de progreso pensada para una terminal: reescribe
# la misma línea con \r y códigos ANSI. Aquí se limpia y se traduce a números.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_CAPA = re.compile(r"^([0-9a-f]{6,}):\s+(\d+)%(.*)$")
_TAMANO = re.compile(r"([\d.]+)\s*(B|KB|MB|GB|TB)\b")
# Ollama reporta tamaños en base 1000 (su paquete format), no en base 1024.
_UNIDADES = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000, "TB": 1_000_000_000_000}


def _limpiar(texto: str) -> str:
    return _ANSI.sub("", texto).strip()


def _a_bytes(texto: str) -> int | None:
    m = _TAMANO.search(texto)
    if not m:
        return None
    try:
        return int(float(m.group(1)) * _UNIDADES[m.group(2)])
    except ValueError:
        return None


def _humano(cantidad: int | None) -> str:
    if not cantidad:
        return "?"
    for unidad, factor in (("GB", 1_000_000_000), ("MB", 1_000_000), ("KB", 1_000)):
        if cantidad >= factor:
            valor = cantidad / factor
            return f"{valor:.1f} {unidad}" if valor < 10 else f"{round(valor)} {unidad}"
    return f"{cantidad} B"


def nuevo_avance() -> dict:
    return {"capas": {}, "fase": "", "error": None, "listo": False}


def aplicar_segmento(avance: dict, segmento: str) -> dict:
    """Absorbe una línea (ya limpia) de `ollama pull` en el avance acumulado."""
    if not segmento:
        return avance
    bajo = segmento.lower()
    if bajo.startswith("error"):
        avance["error"] = segmento.split(":", 1)[1].strip() if ":" in segmento else segmento
        return avance
    # Un mismo cuadro de la terminal puede traer varias capas pegadas, porque
    # ollama mueve el cursor hacia arriba para repintarlas todas.
    for pieza in segmento.split("pulling ")[1:]:
        m = _CAPA.match(pieza.strip())
        if not m:
            continue
        digest, porcentaje, resto = m.group(1), int(m.group(2)), m.group(3)
        tamanos = _TAMANO.findall(resto)
        hecho = total = None
        if len(tamanos) >= 2:
            # "294 KB/ 45 MB": lo bajado y el total de la capa.
            hecho = _a_bytes(f"{tamanos[0][0]} {tamanos[0][1]}")
            total = _a_bytes(f"{tamanos[1][0]} {tamanos[1][1]}")
        elif len(tamanos) == 1:
            # Capa terminada: ollama deja solo el total.
            total = _a_bytes(f"{tamanos[0][0]} {tamanos[0][1]}")
            hecho = total if porcentaje >= 100 else None
        avance["capas"][digest] = {"pct": porcentaje, "hecho": hecho, "total": total}
    if "success" in bajo:
        avance["listo"] = True
    elif "writing manifest" in bajo:
        avance["fase"] = "guardando"
    elif "verifying" in bajo:
        avance["fase"] = "verificando"
    elif "pulling manifest" in bajo and not avance["capas"]:
        avance["fase"] = "preparando"
    return avance


def resumen_avance(avance: dict) -> dict:
    """El avance acumulado, en los términos del contrato: estado, porcentaje, detalle."""
    capas = avance["capas"]
    # La capa más pesada es la de los pesos del modelo: su avance es el que el
    # dueño reconoce como "cuánto falta". Las otras capas pesan bytes y terminan
    # al instante; promediarlas daría un número más bonito pero menos cierto.
    pesada = max(capas.values(), key=lambda c: c["total"] or 0, default=None)
    porcentaje = pesada["pct"] if pesada else 0
    if avance["error"]:
        return {
            "estado": "error",
            "porcentaje": porcentaje,
            "detalle": f"Ollama no pudo descargarlo: {avance['error']}",
        }
    if avance["listo"]:
        return {
            "estado": "listo",
            "porcentaje": 100,
            "detalle": "Listo: el modelo ya está en esta computadora.",
        }
    if avance["fase"] == "guardando":
        return {
            "estado": "descargando",
            "porcentaje": porcentaje,
            "detalle": "Guardando el modelo.",
        }
    if avance["fase"] == "verificando":
        return {
            "estado": "descargando",
            "porcentaje": porcentaje,
            "detalle": "Verificando lo que se descargó.",
        }
    if pesada:
        detalle = f"Descargando el modelo: {_humano(pesada['hecho'])} de {_humano(pesada['total'])}"
        return {"estado": "descargando", "porcentaje": porcentaje, "detalle": detalle}
    return {"estado": "descargando", "porcentaje": 0, "detalle": "Preparando la descarga."}


def parsear_salida_pull(salida: str) -> dict:
    """La salida completa de `ollama pull` traducida a estado/porcentaje/detalle."""
    avance = nuevo_avance()
    for segmento in re.split(r"[\r\n]", salida or ""):
        aplicar_segmento(avance, _limpiar(segmento))
    return resumen_avance(avance)


def _segmentos(flujo) -> "list[str]":
    """Lee el pipe de `ollama pull` y va soltando cada cuadro ya limpio.

    Se lee por trozos y no por líneas porque la barra de progreso NO manda saltos
    de línea: reescribe la misma con \\r, así que readline() se quedaría esperando
    hasta el final de la descarga.
    """
    # read1 devuelve lo que ya llegó del pipe; read(n) esperaría a juntar n bytes
    # y el progreso llegaría a saltos.
    leer = flujo.read1 if hasattr(flujo, "read1") else flujo.read
    resto = b""
    while True:
        trozo = leer(4096)
        if not trozo:
            break
        partes = re.split(rb"[\r\n]", resto + trozo)
        resto = partes.pop()
        for parte in partes:
            yield _limpiar(parte.decode("utf-8", "replace"))
    if resto:
        yield _limpiar(resto.decode("utf-8", "replace"))


# Descargas vivas de ESTE proceso: {modelo: {estado, porcentaje, detalle}}. Vive
# en memoria a propósito: si aiuda se reinicia, el progreso se pierde pero el
# modelo no (Ollama guarda lo bajado en disco y `progreso` vuelve a preguntarle).
_descargas: dict[str, dict] = {}
_candado = threading.Lock()


def _guardar(nombre: str, estado: dict) -> None:
    with _candado:
        _descargas[nombre] = estado


def _esta_instalado(nombre: str) -> bool:
    tags = _pedir_json(f"{OLLAMA_HOST}/api/tags")
    instalados = {_normalizar(m["nombre"]) for m in modelos_de_tags(tags)}
    return _normalizar(nombre) in instalados


def _correr_pull(nombre: str) -> None:
    """El hilo: corre `ollama pull` y publica su avance mientras baja."""
    ruta = ruta_ollama()
    if not ruta:
        _guardar(
            nombre,
            {
                "estado": "error",
                "porcentaje": 0,
                "detalle": "No encontramos Ollama en esta computadora.",
            },
        )
        return
    try:
        proceso = subprocess.Popen(
            [ruta, "pull", nombre],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _guardar(
            nombre,
            {"estado": "error", "porcentaje": 0, "detalle": f"No se pudo ejecutar ollama: {e}"},
        )
        return
    avance = nuevo_avance()
    for segmento in _segmentos(proceso.stdout):
        aplicar_segmento(avance, segmento)
        _guardar(nombre, resumen_avance(avance))
    codigo = proceso.wait()
    resumen = resumen_avance(avance)
    if codigo != 0 and resumen["estado"] != "error":
        resumen = {
            "estado": "error",
            "porcentaje": resumen["porcentaje"],
            "detalle": f"La descarga terminó mal (ollama salió con código {codigo}).",
        }
    elif resumen["estado"] == "descargando":
        # Terminó sin decir "success". En vez de dar por buena la descarga, se le
        # pregunta a Ollama si el modelo quedó.
        if _esta_instalado(nombre):
            resumen = {
                "estado": "listo",
                "porcentaje": 100,
                "detalle": "Listo: el modelo ya está en esta computadora.",
            }
        else:
            resumen = {
                "estado": "error",
                "porcentaje": resumen["porcentaje"],
                "detalle": "La descarga terminó sin confirmar que el modelo quedó instalado.",
            }
    _guardar(nombre, resumen)


def descargar_modelo(nombre: str) -> dict:
    """Arranca `ollama pull` en un hilo. Idempotente: si ya va, no lanza otro.

    Lanza ``ValueError`` si el nombre no parece un modelo de Ollama.
    """
    nombre = (nombre or "").strip()
    if not NOMBRE_MODELO.match(nombre):
        raise ValueError("Ese no parece el nombre de un modelo de Ollama.")
    with _candado:
        actual = _descargas.get(nombre)
        if actual and actual["estado"] == "descargando":
            return dict(actual)
        inicial = {"estado": "descargando", "porcentaje": 0, "detalle": "Preparando la descarga."}
        _descargas[nombre] = inicial
    threading.Thread(
        target=_correr_pull, args=(nombre,), name=f"aiuda-pull-{nombre}", daemon=True
    ).start()
    return dict(inicial)


def progreso_descarga(nombre: str) -> dict:
    """Cómo va la descarga de ese modelo. "desconocido" si nadie la pidió aquí."""
    nombre = (nombre or "").strip()
    with _candado:
        actual = _descargas.get(nombre)
    if actual:
        return dict(actual)
    if nombre and _esta_instalado(nombre):
        return {
            "estado": "listo",
            "porcentaje": 100,
            "detalle": "Ya estaba instalado en esta computadora.",
        }
    return {
        "estado": "desconocido",
        "porcentaje": 0,
        "detalle": "Nadie ha pedido descargar este modelo en esta sesión.",
    }
