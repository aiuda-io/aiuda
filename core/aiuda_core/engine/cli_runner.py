"""Usar el Claude Code o el Codex que YA está instalado en la computadora.

Por qué existe: si el dueño ya tiene su CLI instalado y con su sesión iniciada,
pedirle que abra la Terminal, corra `claude setup-token` y pegue un token es
absurdo. Ya está logueado. aiuda solo tiene que hablarle.

Este runner ejecuta el binario local en modo no interactivo y lee su respuesta:

    claude -p "…" --output-format stream-json --include-partial-messages --verbose
    codex exec --json "…"

Los dos van por su modo de eventos y no por el de una sola respuesta al final.
Eso compra dos cosas concretas: el CLI dice en qué va mientras trabaja, así que
el reloj puede medir SILENCIO en vez de duración total (una corrida larga pero
sana ya no muere igual que una colgada), y los dos reportan cuántos tokens
gastaron, incluidos los de caché, que es de donde sale casi todo el costo.

No hay tokens que capturar, ni llaves que pegar, ni navegador que abrir: la
sesión vive en el CLI, que es de quien la instaló. aiuda nunca ve credenciales.

Si el CLI del dueño es viejo y no conoce esas banderas, se reintenta con las de
antes (`--output-format json` y `codex exec` a secas) y todo sigue funcionando,
solo que sin cifras de gasto.

Limitación honesta: estos CLIs devuelven texto, no llamadas a herramientas con
el protocolo del proveedor. Para el loop con herramientas (el chat de los
ayudantes) se le pide al modelo que conteste con un JSON diciendo qué quiere
consultar, y aiuda ejecuta la consulta y le devuelve el resultado. Es más
rudimentario que el tool calling nativo, así que si el modelo no coopera se
corta con honestidad en vez de inventar.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Cuánto se le aguanta CALLADO. Como el CLI va contando lo que hace, el silencio
# es la señal de que se colgó; tardarse no lo es.
TIMEOUT_S = 180

# Aun hablando, algo tiene que terminar. Este es el tope duro.
TIMEOUT_TOTAL_S = 900

# El chat con herramientas: cuántas vueltas antes de rendirse.
MAX_VUELTAS = 6


class CliNoDisponible(RuntimeError):
    """El binario no está instalado o no respondió."""


def _lugares_comunes(nombre: str) -> list[Path]:
    """Dónde suelen quedar estos CLIs cuando el PATH no los trae.

    La app de escritorio arranca con el PATH mínimo de macOS
    (/usr/bin:/bin:/usr/sbin:/sbin): ahí no está Homebrew, ni ~/.local/bin, ni
    los binarios de npm. Sin esto, aiuda le diría "no tienes Claude Code" a
    alguien que sí lo tiene, que es justo lo que no puede pasar."""
    home = Path.home()
    carpetas = [
        home / ".local" / "bin",  # instalador nativo de Claude Code
        home / ".claude" / "local",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        home / ".npm-global" / "bin",
        home / ".bun" / "bin",
        home / ".cargo" / "bin",
        home / ".volta" / "bin",
        Path("/opt/local/bin"),
    ]
    # Node por versiones (nvm, fnm): la más reciente primero.
    for patron in (".nvm/versions/node/*/bin", ".local/share/fnm/node-versions/*/installation/bin"):
        carpetas.extend(sorted(home.glob(patron), reverse=True))
    return [c / nombre for c in carpetas]


def detectar(nombre: str) -> str | None:
    """Ruta del CLI si está instalado. `nombre` es "claude" o "codex"."""
    del_path = shutil.which(nombre)
    if del_path:
        return del_path
    for ruta in _lugares_comunes(nombre):
        if ruta.is_file() and os.access(ruta, os.X_OK):
            return str(ruta)
    return None


def _entorno_para(binario: str) -> dict[str, str]:
    """El entorno con el que se corre el CLI del dueño.

    Encontrar el programa no basta. Varios de estos CLIs son scripts de Node que
    empiezan con `#!/usr/bin/env node`, así que al arrancarlos el sistema va a
    buscar `node` en el PATH... y una app abierta desde el Finder trae un PATH
    pelado donde node no está. El síntoma era feo de diagnosticar, porque el
    error no habla del CLI: `env: node: No such file or directory`.

    Así que al PATH se le suman la carpeta del propio binario (ahí vive su
    intérprete, en el caso de nvm y fnm) y los lugares de siempre.
    """
    carpetas = [str(Path(binario).parent)]
    carpetas += [str(p.parent) for p in _lugares_comunes("node")]
    actual = os.environ.get("PATH", "")
    if actual:
        carpetas.append(actual)
    vistas: list[str] = []
    for carpeta in carpetas:
        for parte in carpeta.split(os.pathsep):
            if parte and parte not in vistas:
                vistas.append(parte)
    return {**os.environ, "PATH": os.pathsep.join(vistas)}


def _correr(cmd: list[str], entrada: str) -> str:
    """Corre el CLI y devuelve todo lo que imprimió, vigilando que siga vivo.

    Esto era un `subprocess.run` con 180 segundos de tope total, y ahí estaba el
    problema: una corrida larga pero sana moría exactamente igual que una
    colgada. Con el modo de eventos el CLI va diciendo en qué va, así que el
    reloj mide silencio. Mientras siga hablando se le deja trabajar; si se
    calla, se corta.
    """
    try:
        proceso = subprocess.Popen(  # noqa: S603 — el comando lo arma aiuda, no el dueño
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_entorno_para(cmd[0]),
        )
    except FileNotFoundError as exc:
        raise CliNoDisponible(f"No encontré {Path(cmd[0]).name} en esta computadora.") from exc

    salida: list[str] = []
    errores: list[str] = []
    latidos: queue.Queue = queue.Queue()

    def leer(flujo, destino: list[str]) -> None:
        try:
            for linea in flujo:
                destino.append(linea)
                latidos.put(True)
        finally:
            latidos.put(None)  # este flujo ya cerró
            with contextlib.suppress(Exception):
                flujo.close()

    for flujo, destino in ((proceso.stdout, salida), (proceso.stderr, errores)):
        threading.Thread(target=leer, args=(flujo, destino), daemon=True).start()

    with contextlib.suppress(Exception):
        proceso.stdin.write(entrada)
    with contextlib.suppress(Exception):
        proceso.stdin.close()

    nombre = Path(cmd[0]).name
    limite = time.monotonic() + TIMEOUT_TOTAL_S
    abiertos = 2
    while abiertos:
        try:
            if latidos.get(timeout=TIMEOUT_S) is None:
                abiertos -= 1
        except queue.Empty:
            _matar(proceso)
            raise CliNoDisponible(
                f"{nombre} se quedó callado {TIMEOUT_S} segundos. Parece que se colgó."
            ) from None
        if time.monotonic() > limite:
            _matar(proceso)
            raise CliNoDisponible(
                f"{nombre} lleva más de {TIMEOUT_TOTAL_S // 60} minutos sin terminar."
            )

    with contextlib.suppress(subprocess.TimeoutExpired):
        proceso.wait(timeout=10)
    if proceso.returncode not in (0, None):
        raise CliNoDisponible(_motivo(nombre, "".join(salida), "".join(errores)))
    return "".join(salida)


def _matar(proceso: subprocess.Popen) -> None:
    """Que no quede un CLI huérfano comiéndose la computadora del negocio."""
    with contextlib.suppress(Exception):
        proceso.kill()
    with contextlib.suppress(Exception):
        proceso.wait(timeout=5)


def _motivo(cli: str, stdout: str, stderr: str) -> str:
    """El porqué del fallo, en palabras del dueño, no en JSON crudo.

    Cuando el CLI falla imprime su propio JSON o su propio texto. El caso más
    común de todos es que esté instalado pero sin sesión iniciada."""
    crudo = (stdout or "").strip()
    detalle = crudo
    try:
        datos = json.loads(crudo)
        if isinstance(datos, dict):
            detalle = str(datos.get("result") or datos.get("error") or "").strip()
    except ValueError:
        pass
    detalle = detalle or (stderr or "").strip()
    nombre = "Claude Code" if cli == "claude" else "Codex"
    if any(p in detalle.lower() for p in ("not logged in", "please run /login", "unauthorized", "no auth")):
        return f"{nombre} está instalado pero sin sesión iniciada. Ábrelo una vez, inicia sesión y vuelve aquí."
    return f"{nombre} no pudo responder: {detalle[:200]}" if detalle else f"{nombre} no pudo responder."


def _no_conoce_la_bandera(mensaje: str) -> bool:
    """¿El CLI se quejó de una bandera que no conoce?

    Pasa con instalaciones viejas. No es motivo para mandar al dueño a
    actualizar nada: se le vuelve a hablar como antes."""
    bajo = mensaje.lower()
    return any(
        p in bajo
        for p in (
            "unknown option",
            "unknown argument",
            "unexpected argument",
            "unrecognized",
            "invalid value",
            "did you mean",
        )
    )


def _eventos(salida: str) -> list[dict]:
    """Los objetos JSON de una salida por líneas.

    Lo que no es JSON se ignora a propósito: los dos CLIs sueltan avisos en
    medio ("Reading additional input from stdin…") que no son eventos."""
    eventos = []
    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea.startswith("{"):
            continue
        with contextlib.suppress(ValueError):
            dato = json.loads(linea)
            if isinstance(dato, dict):
                eventos.append(dato)
    return eventos


def _uso_de_claude(uso: dict) -> tuple[int, int]:
    """Los tokens de entrada que de verdad se procesaron.

    Aquí estaba ciego el medidor. `input_tokens` cuenta ÚNICAMENTE lo que no
    estaba en caché: en una llamada real de Claude Code eso da 2, mientras el
    contexto que sí se procesó fueron 6,468. Con esa cifra el tope del dueño no
    tenía cómo cortar, porque medía algo que no era el consumo.

    Lo que se lee de caché queda fuera a propósito. Son el mismo prompt de
    sistema releído en cada llamada, y se cobran a una décima parte: meterlos
    aquí multiplicaría el conteo por diez y el tope cortaría por gasto que no
    ocurrió.
    """
    return (
        int(uso.get("input_tokens") or 0) + int(uso.get("cache_creation_input_tokens") or 0),
        int(uso.get("output_tokens") or 0),
    )


def _texto_de_claude(salida: str) -> tuple[str, int, int]:
    """(texto, tokens_entrada, tokens_salida) de lo que imprimió `claude -p`.

    Entiende las dos formas: el objeto único de `--output-format json` y el
    chorro de eventos de `stream-json`, donde el último evento `result` trae el
    texto final y el uso completo."""
    eventos = _eventos(salida)
    if not eventos:
        # Ni JSON ni eventos: la salida ES el texto.
        return salida.strip(), 0, 0

    final = next((e for e in reversed(eventos) if e.get("type") == "result"), None)
    if final is None and len(eventos) == 1:
        final = eventos[0]  # el objeto único de --output-format json

    if final is not None:
        if final.get("is_error"):
            raise CliNoDisponible(
                str(final.get("result") or "Claude Code devolvió un error.")[:300]
            )
        texto = str(final.get("result") or "").strip()
        entrada, salida_tok = _uso_de_claude(final.get("usage") or {})
        if texto:
            return texto, entrada, salida_tok

    # Se cortó antes del evento final: se arma la respuesta con los pedazos que
    # sí alcanzó a mandar, en vez de tirar lo que ya dijo.
    pedazos = [
        str(delta.get("text") or "")
        for evento in eventos
        if evento.get("type") == "stream_event"
        for delta in [((evento.get("event") or {}).get("delta") or {})]
        if delta.get("type") == "text_delta"
    ]
    return "".join(pedazos).strip(), 0, 0


def _texto_de_codex(salida: str) -> tuple[str, int, int]:
    """(texto, tokens_entrada, tokens_salida) de lo que imprimió `codex exec`.

    Con `--json` los tokens por fin se pueden leer: antes se registraba la
    llamada en ceros porque la salida de texto no los traía de forma estable."""
    eventos = _eventos(salida)
    if eventos:
        mensajes = [
            str((e.get("item") or {}).get("text") or "").strip()
            for e in eventos
            if e.get("type") == "item.completed"
            and (e.get("item") or {}).get("type") == "agent_message"
        ]
        uso = next(
            (e.get("usage") or {} for e in reversed(eventos) if e.get("type") == "turn.completed"),
            {},
        )
        # El razonamiento se cobra como salida aunque no se vea en la respuesta.
        return (
            "\n".join(m for m in mensajes if m).strip(),
            int(uso.get("input_tokens") or 0),
            int(uso.get("output_tokens") or 0) + int(uso.get("reasoning_output_tokens") or 0),
        )

    # Salida de texto (CLI viejo): encabezado "codex", el mensaje, y un pie de
    # tokens. El mensaje es lo de en medio.
    lineas = [ln.rstrip() for ln in salida.splitlines()]
    corte = next(
        (i for i, ln in enumerate(lineas) if ln.strip().lower().startswith("tokens used")),
        len(lineas),
    )
    utiles = [ln for ln in lineas[:corte] if ln.strip() and ln.strip().lower() != "codex"]
    return "\n".join(utiles).strip(), 0, 0


class CliRunner:
    """ProviderRunner que delega en el CLI instalado del dueño."""

    def __init__(
        self,
        cli: str = "claude",
        *,
        usage_callback: Callable | None = None,
        correr=_correr,
    ):
        if cli not in ("claude", "codex"):
            raise ValueError(f"CLI no soportado: {cli}")
        self.cli = cli
        # Ruta absoluta: dentro de la app el PATH no trae Homebrew ni ~/.local/bin.
        self.binario = detectar(cli) or cli
        self._usage_callback = usage_callback
        self._correr = correr
        self.budget_check: Callable[[], None] | None = None

    # ------------------------------------------------------------------ #
    def model_for(self, role: str) -> str:
        # El modelo lo elige el CLI con la configuración del dueño; aiuda no la
        # pisa. Se reporta con nombre honesto para el registro de uso.
        if role in ("triage", "redaccion"):
            return f"{self.cli}-cli"
        raise ValueError(f"Rol de modelo desconocido: {role}")

    def _comando(self, prompt: str, *, moderno: bool) -> list[str]:
        if self.cli == "claude":
            if not moderno:
                return [self.binario, "-p", prompt, "--output-format", "json"]
            return [
                self.binario,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--include-partial-messages",
                "--verbose",  # stream-json lo exige
            ]
        return [self.binario, "exec", *(["--json"] if moderno else []), prompt]

    def _pedir(self, system: str, user: str, task: str, model: str) -> str:
        if self.budget_check is not None:
            self.budget_check()
        prompt = f"{system}\n\n{user}" if system else user

        try:
            salida = self._correr(self._comando(prompt, moderno=True), "")
        except CliNoDisponible as exc:
            # Un CLI viejo no conoce las banderas nuevas. En vez de decirle al
            # dueño que actualice, se le habla como antes: sin cifras de gasto,
            # pero funcionando.
            if not _no_conoce_la_bandera(str(exc)):
                raise
            salida = self._correr(self._comando(prompt, moderno=False), "")

        leer = _texto_de_claude if self.cli == "claude" else _texto_de_codex
        texto, entrada, salida_tok = leer(salida)
        if self._usage_callback is not None:
            self._usage_callback(model, task, entrada, salida_tok)
        return texto

    # ------------------------------------------------------------------ #
    def complete(
        self,
        system: str,
        user: str,
        *,
        task: str,
        model: str | None = None,
        role: str = "redaccion",
        max_tokens: int = 1024,
    ) -> str:
        return self._pedir(system, user, task, model or self.model_for(role))

    def classify(self, system: str, user: str, *, labels: list[str], task: str) -> str:
        raw = self.complete(
            system=system + f"\nResponde ÚNICAMENTE con una de estas etiquetas: {labels}",
            user=user,
            role="triage",
            task=task,
            max_tokens=16,
        )
        limpio = raw.strip().lower()
        return limpio if limpio in labels else labels[-1]

    def run_tool_loop(
        self,
        *,
        system: str,
        user_message: str,
        tools: list[dict],
        execute_tool: Callable[[str, dict], str],
        model: str | None = None,
        role: str = "redaccion",
        task: str = "agent_loop",
        max_iterations: int = MAX_VUELTAS,
    ) -> str:
        """Loop con herramientas sobre un CLI que solo devuelve texto.

        El modelo contesta con un JSON: o pide una consulta, o da la respuesta
        final. Si se sale del formato, se corta honesto."""
        model = model or self.model_for(role)
        catalogo = "\n".join(
            f"- {t.get('name')}: {t.get('description', '')}" for t in tools
        )
        instrucciones = (
            f"{system}\n\n"
            "Puedes consultar estos datos del negocio:\n"
            f"{catalogo}\n\n"
            "Responde SIEMPRE con un solo objeto JSON, sin texto alrededor:\n"
            '  para consultar: {"consulta": "nombre", "datos": {…}}\n'
            '  para contestar:  {"respuesta": "lo que le dices al dueño"}\n'
        )
        conversacion = [f"Pregunta del dueño: {user_message}"]

        for _ in range(max_iterations):
            crudo = self._pedir(instrucciones, "\n\n".join(conversacion), task, model)
            bloque = _primer_json(crudo)
            if bloque is None:
                # Sin JSON: se toma como respuesta final en texto plano. Es lo
                # honesto: el modelo dijo algo, no lo tiramos.
                return crudo.strip()
            if "respuesta" in bloque:
                return str(bloque["respuesta"]).strip()
            nombre = str(bloque.get("consulta") or "")
            if not nombre:
                return crudo.strip()
            try:
                resultado = execute_tool(nombre, dict(bloque.get("datos") or {}))
            except Exception as exc:  # el modelo puede corregir el rumbo
                resultado = f"Error: {exc}"
            conversacion.append(f"Resultado de {nombre}: {resultado}")

        return "Lo siento, no pude completar esta tarea. Un humano la revisará."


def _primer_json(texto: str) -> dict | None:
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin == -1 or fin < inicio:
        return None
    try:
        datos = json.loads(texto[inicio : fin + 1])
    except ValueError:
        return None
    return datos if isinstance(datos, dict) else None


def probar(cli: str, correr=_correr) -> dict:
    """Una llamada mínima real al CLI, para el botón de un clic.

    Veredicto honesto: ok=True → {ok, mode, model, latency_ms};
    ok=False → {ok, mode, code, error}."""
    import time

    if detectar(cli) is None:
        return {
            "ok": False,
            "mode": "cli",
            "code": "no_instalado",
            "error": f"No encontré {cli} en esta computadora.",
        }
    runner = CliRunner(cli, correr=correr)
    t0 = time.monotonic()
    try:
        texto = runner.complete(
            system="Responde en una palabra.", user="ping", task="prueba"
        )
    except CliNoDisponible as exc:
        mensaje = str(exc)
        codigo = "sin_sesion" if "sin sesión iniciada" in mensaje else "cli"
        return {"ok": False, "mode": "cli", "code": codigo, "error": mensaje}
    except Exception as exc:  # noqa: BLE001 — la prueba nunca tumba el endpoint
        return {"ok": False, "mode": "cli", "code": "unknown", "error": str(exc)[:200]}
    if not texto:
        return {
            "ok": False,
            "mode": "cli",
            "code": "sin_respuesta",
            "error": f"{cli} no devolvió nada. ¿Tienes la sesión iniciada?",
        }
    return {
        "ok": True,
        "mode": "cli",
        "model": f"{cli}-cli",
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }
