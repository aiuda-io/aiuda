"""Computer local para CUA: un navegador Chromium (Playwright) que el agente opera.

Es el "display" del computer-use de Anthropic: recibe acciones (click/type/key/scroll)
en coordenadas de pantalla y devuelve capturas PNG. Local y sin VM — el MVP corre en la
máquina del negocio, no en un sandbox trycua. Solo lectura por defecto (la misión decide
si permite escribir); nunca descarga ni ejecuta binarios.

Requiere el extra `cua`: `uv sync --extra cua && playwright install chromium`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os

# Tamaño del "monitor" que ve el agente. El viewport de Playwright y el display que se le
# declara al modelo deben coincidir para que las coordenadas cuadren 1:1.
WIDTH, HEIGHT = 1280, 800

# Mensajes honestos de "no instalado": lo que el dueño ve cuando el servidor no tiene el
# navegador. Dicen exactamente qué falta y cómo instalarlo (ver docs/CUA.md).
MSG_EXTRA_NO_INSTALADO = (
    "El navegador del asistente no está instalado en este servidor (extra `cua`). "
    "Instálalo con: uv sync --extra cua && .venv/bin/playwright install chromium"
)
MSG_CHROMIUM_FALTA = (
    "Playwright está instalado pero falta el navegador Chromium. "
    "Corre: .venv/bin/playwright install chromium"
)


def paquete_playwright_instalado() -> bool:
    """¿El paquete `playwright` (extra `cua`) está en este entorno? Barato: no importa
    ni arranca nada, solo mira si el módulo existe."""
    return importlib.util.find_spec("playwright") is not None


# Cache solo del veredicto POSITIVO: un Chromium instalado no se desinstala solo. El
# negativo se re-verifica en cada consulta, para que instalarlo se refleje sin reiniciar.
_CHROMIUM_LISTO = False


def estado_navegador() -> tuple[bool, str]:
    """(listo, detalle) honesto del navegador del CUA en este entorno.

    Distingue los dos faltantes reales: el paquete (extra `cua` sin instalar) y el
    binario de Chromium (falta `playwright install chromium`). Es síncrono (arranca el
    driver de Playwright un instante): para endpoints/CLI, no para dentro del loop async.
    """
    global _CHROMIUM_LISTO
    if not paquete_playwright_instalado():
        return False, MSG_EXTRA_NO_INSTALADO
    if _CHROMIUM_LISTO:
        return True, "Navegador listo (Playwright + Chromium instalados)."
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
        if not os.path.exists(exe):
            return False, MSG_CHROMIUM_FALTA
    except Exception as exc:  # driver roto, permisos, etc.: la razón real, no un invento
        return False, f"Playwright no pudo iniciar: {exc}"
    _CHROMIUM_LISTO = True
    return True, "Navegador listo (Playwright + Chromium instalados)."

# Teclas estilo computer-use (xdotool) -> teclas de Playwright.
_KEYMAP = {
    "return": "Enter", "kp_enter": "Enter", "enter": "Enter",
    "tab": "Tab", "escape": "Escape", "esc": "Escape", "space": " ",
    "backspace": "Backspace", "delete": "Delete", "bksp": "Backspace",
    "page_down": "PageDown", "page_up": "PageUp", "pagedown": "PageDown", "pageup": "PageUp",
    "home": "Home", "end": "End", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight",
    "ctrl": "Control", "control": "Control", "alt": "Alt", "shift": "Shift",
    "super": "Meta", "cmd": "Meta", "meta": "Meta", "win": "Meta",
}


def _map_key(combo: str) -> str:
    """"ctrl+a" -> "Control+a"; "Page_Down" -> "PageDown". Tolerante a mayúsculas."""
    parts = [p.strip() for p in str(combo).replace(" ", "").split("+") if p.strip()]
    out = [_KEYMAP.get(p.lower(), p if len(p) == 1 else p.capitalize()) for p in parts]
    return "+".join(out)


class LocalComputer:
    """Navegador local que ejecuta acciones de computer-use. Úsalo como context manager
    asíncrono: `async with LocalComputer() as comp: ...`."""

    def __init__(
        self,
        width: int = WIDTH,
        height: int = HEIGHT,
        headless: bool = True,
        storage_state: dict | None = None,
    ):
        self.width = width
        self.height = height
        self.headless = headless
        # Sesión ya autenticada (cookies + localStorage) para arrancar YA logueado. La
        # aporta el handoff de login: el dueño entra una vez a la vista, se guarda su
        # sesión cifrada y el asistente la reusa. None = navegador limpio (login normal).
        self.storage_state = storage_state
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    async def __aenter__(self) -> "LocalComputer":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        # Un contexto propio (no new_page directo) para poder inyectar la sesión guardada
        # y, en el handoff, capturarla después de que el dueño entre.
        ctx_kwargs: dict = {"viewport": {"width": self.width, "height": self.height}}
        if self.storage_state:
            ctx_kwargs["storage_state"] = self.storage_state
        self._context = await self._browser.new_context(**ctx_kwargs)
        self.page = await self._context.new_page()
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._pw is not None:
                await self._pw.stop()

    async def capturar_storage_state(self) -> dict:
        """La sesión autenticada del contexto (cookies + localStorage), para guardarla
        cifrada y reusarla luego. Se llama con el contexto vivo (dentro del `async with`)."""
        if self._context is None:
            raise RuntimeError("LocalComputer no iniciado (usa 'async with').")
        return await self._context.storage_state()

    async def goto(self, url: str) -> None:
        # "load" y no "domcontentloaded": la primera captura que ve el agente debe ser la
        # página ya asentada (con domcontentloaded el autofocus/JS pueden seguir en vuelo).
        await self.page.goto(url, wait_until="load")

    async def screenshot(self) -> bytes:
        return await self.page.screenshot()

    async def act(self, action: str, **kw) -> None:
        """Ejecuta una acción de computer-use. Coordenadas en píxeles del viewport.

        Cubre las acciones comunes; las desconocidas (p.ej. cursor_position) son no-op:
        no rompen la misión, el modelo reintenta con otra."""
        page = self.page
        if page is None:
            raise RuntimeError("LocalComputer no iniciado (usa 'async with').")

        def coord(key="coordinate"):
            x, y = kw[key]
            return int(x), int(y)

        if action == "screenshot":
            return
        if action in ("left_click", "click"):
            await page.mouse.click(*coord())
        elif action == "double_click":
            await page.mouse.dblclick(*coord())
        elif action == "triple_click":
            # El modelo lo usa para seleccionar el texto de un campo antes de teclear
            # (visto en corrida real): sin esto, el type ANEXA en vez de reemplazar.
            await page.mouse.click(*coord(), click_count=3)
        elif action == "left_mouse_down":
            await page.mouse.move(*coord())
            await page.mouse.down()
        elif action == "left_mouse_up":
            await page.mouse.move(*coord())
            await page.mouse.up()
        elif action == "right_click":
            await page.mouse.click(*coord(), button="right")
        elif action == "middle_click":
            await page.mouse.click(*coord(), button="middle")
        elif action == "mouse_move":
            await page.mouse.move(*coord())
        elif action == "left_click_drag":
            sx, sy = coord("start_coordinate")
            ex, ey = coord()
            await page.mouse.move(sx, sy)
            await page.mouse.down()
            await page.mouse.move(ex, ey)
            await page.mouse.up()
        elif action == "type":
            await page.keyboard.type(str(kw.get("text", "")))
        elif action == "key":
            await page.keyboard.press(_map_key(kw.get("text", "")))
        elif action == "scroll":
            cx, cy = coord() if "coordinate" in kw else (self.width // 2, self.height // 2)
            direction = kw.get("scroll_direction", "down")
            amount = int(kw.get("scroll_amount", 3)) * 100
            dx = amount if direction == "right" else -amount if direction == "left" else 0
            dy = amount if direction == "down" else -amount if direction == "up" else 0
            await page.mouse.move(cx, cy)
            await page.mouse.wheel(dx, dy)
        elif action == "wait":
            await asyncio.sleep(min(float(kw.get("duration", 1)), 3))
        # cursor_position y otras: no-op deliberado.
