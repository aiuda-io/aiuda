"""Buscar una IA en la red local, sin que el dueño escriba una dirección IP.

El caso real de una PyME mexicana: hay UNA computadora buena (la Mac del dueño,
la del contador) y varias flojas. Correr un modelo en cada una es imposible;
compartir la buena es lo natural. Técnicamente eso ya funciona hoy — Ollama o
LM Studio escuchando en la red — pero exige que alguien averigüe y teclee
`http://192.168.1.37:11434/v1`, y ahí se acaba el camino para quien no es
técnico.

Esto lo resuelve: barre la red local preguntando "¿hay una IA aquí?" y devuelve
lo que encontró con nombre de equipo y modelos, listo para conectar de un clic.

Decisiones que vale la pena conocer:

- **Nunca automático.** Escanear la red del usuario es intrusivo y en macOS
  dispara el permiso de red local. Se hace solo cuando él pulsa "buscar", nunca
  al arrancar.
- **Solo la subred /24 local.** Ni internet ni rangos ajenos: la casa u oficina
  donde está la máquina.
- **Se prueba lo que aiuda de verdad usa**: el endpoint OpenAI-compatible. Si
  además responde la API nativa de Ollama, se aprovecha para dar nombres de
  modelos más limpios.
- **Sin credenciales adivinadas.** Si un servidor pide autenticación (LM Studio
  puede), se reporta como protegido y el dueño pega su clave; no se intenta
  entrar.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

# Puertos donde vive una IA local: Ollama y LM Studio son el 99% de los casos.
PUERTOS = (11434, 1234)

# Presupuestos de tiempo: el barrido completo debe sentirse como "un momento",
# no como "se colgó". 254 direcciones por 2 puertos con 64 hilos y 300 ms de
# tope por intento cabe en unos pocos segundos.
# 0.5 s y no menos: una computadora ocupada (o que atiende varias conexiones a
# la vez, como cuando 64 hilos tocan su puerto) tarda en aceptar, y un barrido
# demasiado impaciente reporta "no hay nada" cuando sí había.
TIMEOUT_PUERTO_S = 0.5
TIMEOUT_HTTP_S = 2.5
HILOS = 64


@dataclass
class ServidorIA:
    """Una IA encontrada en la red, en términos del dueño."""

    ip: str
    puerto: int
    equipo: str  # nombre del equipo si se pudo resolver, o la IP
    base_url: str  # lo que se guarda como credencial: http://ip:puerto/v1
    programa: str  # "Ollama" | "LM Studio" | "compatible"
    modelos: list[str] = field(default_factory=list)
    protegido: bool = False  # pide autenticación: el dueño tendrá que pegar su clave

    def como_dict(self) -> dict:
        return {
            "ip": self.ip,
            "puerto": self.puerto,
            "equipo": self.equipo,
            "base_url": self.base_url,
            "programa": self.programa,
            "modelos": self.modelos,
            "protegido": self.protegido,
        }


def ip_local() -> str | None:
    """La IP de esta computadora en su red. None si no hay red.

    El truco del socket UDP no envía nada: solo hace que el sistema elija la
    interfaz por la que saldría el tráfico, que es justo la red del usuario."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def subred(ip: str) -> list[str]:
    """Las direcciones de la /24 de esa IP, sin la propia ni las reservadas."""
    partes = ip.split(".")
    if len(partes) != 4:
        return []
    base = ".".join(partes[:3])
    propia = partes[3]
    return [f"{base}.{n}" for n in range(1, 255) if str(n) != propia]


def _puerto_abierto(ip: str, puerto: int, timeout: float = TIMEOUT_PUERTO_S) -> bool:
    try:
        with socket.create_connection((ip, puerto), timeout=timeout):
            return True
    except OSError:
        return False


def _nombre_equipo(ip: str) -> str:
    """Nombre legible del equipo (reverse DNS). Cae a la IP si no resuelve."""
    try:
        socket.setdefaulttimeout(0.6)
        nombre = socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror, socket.gaierror):
        return ip
    finally:
        socket.setdefaulttimeout(None)
    # "MacBook-de-Jose.local." -> "MacBook de Jose"
    limpio = nombre.rstrip(".").removesuffix(".local").replace("-", " ")
    return limpio or ip


def _consultar(url: str, timeout: float = TIMEOUT_HTTP_S) -> tuple[int, dict | None]:
    """(status, json). status 0 = no respondió."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            try:
                return res.status, json.loads(res.read() or "{}")
            except ValueError:
                return res.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None


def inspeccionar(ip: str, puerto: int) -> ServidorIA | None:
    """¿Hay una IA usable en ip:puerto? Devuelve qué es, o None."""
    raiz = f"http://{ip}:{puerto}"

    # La API nativa de Ollama da los nombres tal como los conoce el dueño
    # ("llama3.1:8b"), así que se prueba primero.
    status, datos = _consultar(f"{raiz}/api/tags")
    if status == 200 and isinstance(datos, dict) and "models" in datos:
        modelos = [m.get("name", "") for m in datos.get("models") or [] if m.get("name")]
        return ServidorIA(
            ip=ip,
            puerto=puerto,
            equipo=_nombre_equipo(ip),
            base_url=f"{raiz}/v1",
            programa="Ollama",
            modelos=modelos,
        )

    # Si no es Ollama, lo que importa es que hable OpenAI-compatible: es lo
    # único que aiuda necesita para trabajar. Se exige la lista `data` del
    # contrato: cualquier servicio devuelve 200 con algún JSON, y confundirlo
    # con una IA le daría al dueño una opción que no funciona.
    status, datos = _consultar(f"{raiz}/v1/models")
    if status == 200 and isinstance(datos, dict) and isinstance(datos.get("data"), list):
        modelos = [m.get("id", "") for m in datos["data"] if isinstance(m, dict) and m.get("id")]
        return ServidorIA(
            ip=ip,
            puerto=puerto,
            equipo=_nombre_equipo(ip),
            base_url=f"{raiz}/v1",
            programa="LM Studio" if puerto == 1234 else "compatible",
            modelos=modelos,
        )
    if status in (401, 403):
        # Servidor con contraseña (LM Studio lo permite). Se reporta honesto en
        # vez de esconderlo: el dueño solo tiene que pegar su clave.
        return ServidorIA(
            ip=ip,
            puerto=puerto,
            equipo=_nombre_equipo(ip),
            base_url=f"{raiz}/v1",
            programa="LM Studio" if puerto == 1234 else "compatible",
            protegido=True,
        )
    return None


def buscar(
    *,
    puertos: tuple[int, ...] = PUERTOS,
    hilos: int = HILOS,
    inspector=inspeccionar,
    direcciones: list[str] | None = None,
) -> list[ServidorIA]:
    """Barre la red local y devuelve las IA encontradas.

    `inspector` y `direcciones` se inyectan en las pruebas: la suite jamás toca
    la red de verdad."""
    if direcciones is None:
        propia = ip_local()
        if not propia:
            return []
        direcciones = subred(propia)
    if not direcciones:
        return []

    objetivos = [(ip, puerto) for ip in direcciones for puerto in puertos]
    # Dos fases: primero el puerto (barato, 300 ms), y solo a los que abren se
    # les pregunta por HTTP. Preguntar a 508 direcciones sería lentísimo.
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        abiertos = [
            objetivo
            for objetivo, abierto in zip(
                objetivos, pool.map(lambda o: _puerto_abierto(*o), objetivos)
            )
            if abierto
        ]
        encontrados = list(pool.map(lambda o: inspector(*o), abiertos))

    servidores = [s for s in encontrados if s is not None]
    # Un equipo puede tener Ollama y LM Studio a la vez; se ordena por utilidad:
    # los que ya traen modelos listos primero.
    servidores.sort(key=lambda s: (s.protegido, -len(s.modelos), s.ip))
    return servidores
