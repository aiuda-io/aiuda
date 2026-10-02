"""Ejecución de misiones CUA con un navegador local (Playwright) como "computer".

MVP real y local: un Computer Use Agent de Anthropic opera un Chromium local. El modelo
ve capturas de pantalla y responde acciones (click/type/key); este runner las ejecuta en
el navegador y le devuelve la nueva captura, hasta que el agente entrega el JSON pedido.
No hay VM ni sandbox trycua: corre en la máquina del negocio.

Requiere el extra `cua` (Playwright) para el navegador, y una credencial de IA con acceso
a computer-use. Sin credencial, `run` es no-op honesto (MissionResult.success=False con la
razón) — nunca inventa datos. Ver docs/CUA.md y scripts/cua_demo.py.
"""

from __future__ import annotations

import base64
import os
import tempfile

from aiuda_core.config import settings
from aiuda_core.cua.computer import (
    HEIGHT,
    MSG_CHROMIUM_FALTA,
    MSG_EXTRA_NO_INSTALADO,
    WIDTH,
    LocalComputer,
    paquete_playwright_instalado,
)
from aiuda_core.cua.mission import Mission, MissionResult, build_mission_prompt
from aiuda_core.engine.llm import parse_json_block

# Beta y tipo de herramienta de computer-use (Anthropic).
_COMPUTER_BETA = "computer-use-2025-01-24"
_COMPUTER_TOOL_TYPE = "computer_20250124"


# Lo que el CUA le pide al modelo, y por qué solo una vía lo da hoy: ver una captura
# de pantalla (imagen) y contestar una acción de ratón o teclado con coordenadas, en
# un ir y venir de decenas de pasos. Eso es la herramienta de computer-use de
# Anthropic. Las demás vías de aiuda intercambian texto: no reciben la captura.
MSG_SIN_IA = (
    "Para operar portales hace falta una llave de Anthropic (Claude). Conéctala en "
    "Proveedor de IA. Sin ella el asistente no puede ver la pantalla del portal."
)


def _error_para_el_dueno(exc: Exception) -> str:
    """El fallo del proveedor en palabras del dueño. Sin esto el recado mostraba el
    error crudo del SDK ("Error code: 401 - {'type': 'error', ...}"), que salió tal
    cual en la verificación en vivo con una llave inválida. Lo que no se reconoce se
    deja pasar como viene: mejor el detalle técnico que una frase que lo esconda."""
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return (
            "Anthropic no aceptó tu llave (401). Revisa en Proveedor de IA que sea "
            "válida y esté vigente."
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "Tu cuenta de Anthropic no tiene permiso para esto (403)."
    if isinstance(exc, anthropic.RateLimitError):
        return (
            "Anthropic frenó la misión por límite de uso (429). Vuelve a intentarlo "
            "en unos minutos."
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return "No se pudo conectar con Anthropic (red o tiempo de espera)."
    if isinstance(exc, anthropic.APIStatusError):
        return (
            f"Anthropic rechazó la petición ({exc.status_code}). Puede que el modelo "
            f"configurado no acepte operar pantallas. Detalle: {str(exc)[:300]}"
        )
    return str(exc)


def _default_client():
    """Cliente Anthropic asíncrono desde ANTHROPIC_API_KEY (demo) o settings. None si no hay."""
    key = os.environ.get("ANTHROPIC_API_KEY") or getattr(settings, "anthropic_api_key", "")
    if not key:
        return None
    import anthropic

    return anthropic.AsyncAnthropic(api_key=key)


class ClienteDelMotor:
    """La IA del dueño (el runner de `make_runner`) con la forma que el loop espera:
    `client.beta.messages.create(...)` asíncrono.

    Por qué un adaptador y no un `AsyncAnthropic` propio: el CUA armaba su cliente
    aparte y así se saltaba el tope de gasto y el registro de uso. Aquí cada paso
    pasa por `motor.computer_use`, igual que la redacción pasa por `complete`.

    La llamada es SÍNCRONA a propósito, aunque el método sea `async`: el tope y el
    registro de uso tocan la sesión de base de datos del hilo que corre la misión,
    y SQLite no deja usar esa conexión desde otro hilo. El loop es de esta misión
    nada más (`asyncio.run` en fallback._run), así que bloquearlo no detiene a nadie."""

    def __init__(self, motor, task: str = "cua"):
        self._motor = motor
        self._task = task
        self.beta = self
        self.messages = self

    async def create(self, **kwargs):
        return self._motor.computer_use(task=self._task, **kwargs)


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


class CuaRunner:
    """Corre misiones CUA en un Chromium local vía el computer-use de Anthropic.

    `client`: cliente Anthropic async (inyectable en tests). Si None, se arma de la
    credencial disponible. `computer`: LocalComputer inyectable (tests). `model`: debe
    soportar computer-use."""

    def __init__(
        self,
        client=None,
        model: str | None = None,
        computer: LocalComputer | None = None,
        headless: bool = True,
        evidence_dir: str | None = None,
        betas: list[str] | None = None,
        storage_state: dict | None = None,
    ):
        self._client = client
        self.model = model or settings.model_redaccion
        self._computer = computer
        self.headless = headless
        # Sesión ya autenticada del portal (del handoff de login), para que el asistente
        # arranque logueado y no choque contra la pantalla de acceso. None = sin sesión.
        self.storage_state = storage_state
        self.evidence_dir = evidence_dir
        # Betas del header anthropic-beta: solo la de computer-use.
        self.betas = betas or [_COMPUTER_BETA]

    def _computer_cm(self) -> LocalComputer:
        return self._computer or LocalComputer(
            headless=self.headless, storage_state=self.storage_state
        )

    def _save_evidence(self, png: bytes, idx: int, into: str) -> str:
        path = os.path.join(into, f"paso_{idx:02d}.png")
        with open(path, "wb") as f:
            f.write(png)
        return path

    async def run(self, mission: Mission) -> MissionResult:
        # Honesto y en orden: primero la infraestructura (¿hay navegador?), luego la
        # credencial. Sin el extra `cua`, la misión no corre y se dice tal cual.
        if self._computer is None and not paquete_playwright_instalado():
            return MissionResult(success=False, error=MSG_EXTRA_NO_INSTALADO)
        client = self._client or _default_client()
        if client is None:
            return MissionResult(
                success=False,
                error=MSG_SIN_IA,
            )

        evidence_dir = self.evidence_dir or tempfile.mkdtemp(prefix="cua_")
        result = MissionResult(success=False)
        tool = {
            "type": _COMPUTER_TOOL_TYPE,
            "name": "computer",
            "display_width_px": WIDTH,
            "display_height_px": HEIGHT,
            "display_number": 1,
        }
        try:
            async with self._computer_cm() as comp:
                tool["display_width_px"] = comp.width
                tool["display_height_px"] = comp.height
                if mission.url_inicio:
                    await comp.goto(mission.url_inicio)
                shot = await comp.screenshot()
                result.evidence.append(self._save_evidence(shot, 0, evidence_dir))
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": build_mission_prompt(mission)},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": _b64(shot),
                                },
                            },
                        ],
                    }
                ]
                last_text = ""
                for paso in range(1, mission.max_pasos + 1):
                    resp = await client.beta.messages.create(
                        model=self.model,
                        max_tokens=1024,
                        tools=[tool],
                        messages=messages,
                        betas=self.betas,
                    )
                    messages.append({"role": "assistant", "content": resp.content})
                    tool_results = []
                    for block in resp.content:
                        btype = getattr(block, "type", None)
                        if btype == "text":
                            last_text = block.text
                        elif btype == "tool_use":
                            action = block.input.get("action", "")
                            params = {k: v for k, v in block.input.items() if k != "action"}
                            try:
                                await comp.act(action, **params)
                                shot = await comp.screenshot()
                                result.evidence.append(
                                    self._save_evidence(shot, paso, evidence_dir)
                                )
                                content = [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": _b64(shot),
                                        },
                                    }
                                ]
                            except Exception as exc:  # una acción falla: reporta, no aborta
                                content = [{"type": "text", "text": f"Acción falló: {exc}"}]
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": content,
                                }
                            )
                            result.steps_log.append(f"{action} {params}"[:200])
                    if not tool_results:  # el agente terminó: entrega el JSON
                        data = parse_json_block(last_text)
                        result.data = {k: v for k, v in data.items() if k != "_resumen"}
                        result.steps_log.append(str(data.get("_resumen", "")))
                        result.success = bool(result.data)
                        break
                    messages.append({"role": "user", "content": tool_results})
        except Exception as exc:
            msg = str(exc)
            # El paquete está pero el binario no: Playwright lo dice en inglés y con su
            # ruta interna; se traduce al faltante real y accionable.
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                result.error = MSG_CHROMIUM_FALTA
            else:
                result.error = _error_para_el_dueno(exc)
        return result


# Misiones plantilla para los casos mexicanos del pitch. Se invocan con las
# credenciales/contexto del tenant; el agente navega, extrae y deja evidencia.
PLANTILLAS: dict[str, Mission] = {
    "sat_cfdi_recibidos": Mission(
        objetivo="Consulta los CFDI recibidos del mes en curso y extrae folio, emisor, monto y fecha de cada uno",
        sistema="Portal del SAT (Factura Electrónica)",
        url_inicio="https://portalcfdi.facturaelectronica.sat.gob.mx/",
        datos_a_extraer={"cfdis": "lista de objetos {folio, emisor, monto, fecha}"},
        notas="El acceso es con e.firma o CIEC del negocio; espera el formulario de login.",
    ),
    "tribunal_acuerdos": Mission(
        objetivo="Busca el expediente indicado y extrae los acuerdos publicados con su fecha y síntesis",
        sistema="Portal del tribunal (boletín/listas de acuerdos)",
        url_inicio="",  # por juzgado; lo aporta la configuración de Lupita
        datos_a_extraer={"acuerdos": "lista de objetos {fecha, sintesis}"},
        notas="Para juzgados y tribunales sin API: el CUA opera el portal directo.",
    ),
    "banca_movimientos": Mission(
        objetivo="Extrae los depósitos recibidos de los últimos 7 días: fecha, monto y concepto",
        sistema="Banca empresarial en línea",
        url_inicio="",
        datos_a_extraer={"depositos": "lista de objetos {fecha, monto, concepto}"},
        notas="Alternativa cuando el banco no está en Belvo. Nunca realizar transferencias.",
    ),
}
