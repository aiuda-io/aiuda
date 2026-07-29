"""CLI de aiuda: la entrada local-first.

    aiuda start    arranca todo (API + consola + scheduler) y abre el navegador
    aiuda daily    corre la corrida de cobranza AHORA, en primer plano
    aiuda doctor   revisa la instalación y dice honesto qué falta
    aiuda version  versión instalada

Sin cuentas, sin nube: el servidor escucha SOLO en 127.0.0.1 con un token de
sesión por arranque (patrón Jupyter) y los datos viven en ~/.aiuda/.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import threading
import webbrowser

DEFAULT_PORT = 4747


def archivo_sesion():
    """Dónde queda anotada la sesión viva (token y puerto), estilo Jupyter."""
    from aiuda_core.db import default_data_dir

    return default_data_dir() / "sesion.json"


def _anotar_sesion(token: str, port: int) -> None:
    """Deja el token de ESTA sesión en ~/.aiuda/sesion.json (solo tú lo lees).

    Sirve para que una segunda ventana (o `aiuda start` corrido de nuevo) se
    sume a la sesión que ya existe en vez de abrir con un token que este server
    no reconoce, que es como el dueño terminaba viendo un error en crudo."""
    import json

    ruta = archivo_sesion()
    try:
        ruta.write_text(json.dumps({"token": token, "port": port, "pid": os.getpid()}))
        ruta.chmod(0o600)
    except OSError:
        pass  # sin permiso de escritura no se rompe el arranque


def sesion_viva(port: int) -> dict | None:
    """La sesión anotada si de verdad hay un aiuda respondiendo en ese puerto.

    La nota se valida SIEMPRE contra el server: si el proceso murió de golpe
    (un apagón, un kill), el archivo queda ahí y no importa, porque sin nadie
    contestando en el puerto no se reusa nada."""
    import json
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        datos = json.loads(archivo_sesion().read_text())
    except (OSError, ValueError):
        return None
    if int(datos.get("port") or 0) != port or not datos.get("token"):
        return None
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as res:
            if res.status != 200:
                return None
    except (URLError, OSError):
        return None
    return datos


def _borrar_sesion() -> None:
    """Quita la nota al salir. Con Ctrl+C alcanza a correr; si al proceso lo
    matan de golpe, no: por eso la nota nunca se cree sola (ver sesion_viva)."""
    try:
        archivo_sesion().unlink()
    except OSError:
        pass


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("aiuda-server")
    except Exception:  # noqa: BLE001
        return "dev"


def _apagar_con_el_padre() -> None:
    """Apaga este proceso cuando muera quien lo lanzó (la app de escritorio).

    Al cerrar la ventana, la app mata al sidecar; pero un binario empaquetado
    corre en dos procesos (lanzador + Python real) y el hijo sobreviviría,
    dejando el server escuchando a espaldas del dueño. Aquí el hijo vigila su
    propio stdin: cuando el padre se va, el pipe cierra y salimos. Funciona
    igual en macOS, Linux y Windows.
    """

    def _vigilar() -> None:
        try:
            while sys.stdin.readline():
                pass
        except Exception:  # noqa: BLE001 — cualquier fallo del pipe = padre ido
            pass
        # os._exit se salta atexit y los manejadores de señal (a propósito: un
        # hilo daemon no puede parar uvicorn de otra forma). Por eso la sesión se
        # borra aquí, a mano: este es el camino de todos los días, el de cerrar
        # la ventana, y sin esto sesion.json se quedaba tirado siempre.
        _borrar_sesion()
        os._exit(0)

    threading.Thread(target=_vigilar, name="aiuda-vigilante", daemon=True).start()


def cmd_start(args: argparse.Namespace) -> int:
    import uvicorn

    if args.exit_with_parent:
        _apagar_con_el_padre()

    # Si quien nos lanzó ya fijó el token (la app de escritorio lo hace, porque
    # necesita el mismo para abrir la ventana), se RESPETA. Generar otro aquí
    # dejaría a la app con un token que el server no reconoce.
    token = "" if args.no_token else (os.environ.get("AIUDA_SESSION_TOKEN") or secrets.token_urlsafe(24))
    if token:
        os.environ["AIUDA_SESSION_TOKEN"] = token
        from aiuda_core.config import settings

        settings.session_token = token

    # ¿Ya hay un aiuda escuchando en este puerto? Entonces no se levanta otro:
    # se abre EL QUE YA ESTÁ, con su token. Dos servers peleando el mismo puerto
    # terminaban en una ventana con un error en crudo.
    viva = sesion_viva(args.port)
    if viva is not None:
        url = f"http://127.0.0.1:{args.port}/?token={viva['token']}"
        print("aiuda ya estaba abierto en esta computadora.", flush=True)
        print(f"  consola: {url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    url = f"http://127.0.0.1:{args.port}/" + (f"?token={token}" if token else "")
    if token:
        import atexit
        import signal

        _anotar_sesion(token, args.port)
        atexit.register(_borrar_sesion)

        # atexit no corre cuando al proceso lo terminan por señal, y así es como
        # se apaga casi siempre: la app cierra su sidecar, o el sistema apaga la
        # sesión. Sin esto, sesion.json se queda tirado apuntando a un puerto
        # muerto. No rompe nada (sesion_viva siempre pregunta a /health antes de
        # creerle), pero deja basura y confunde a quien la lea.
        def _apagar(_sig, _frame):
            _borrar_sesion()
            raise SystemExit(0)

        for señal in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(señal, _apagar)
            except (ValueError, OSError):  # sin hilo principal o sin esa señal
                pass
    print(f"aiuda {_version()} — todo corre en esta computadora", flush=True)
    print(f"  consola: {url}", flush=True)
    print("  datos:   ~/.aiuda/  ·  detener: Ctrl+C", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    try:
        uvicorn.run(
            "aiuda_server.api.main:app",
            host="127.0.0.1",
            port=args.port,
            log_level="warning" if args.quiet else "info",
        )
    finally:
        _borrar_sesion()
    return 0


def cmd_daily(_args: argparse.Namespace) -> int:
    from aiuda_core.db import create_all
    from aiuda_server.worker.main import run_daily_blocking

    create_all()
    print("Corrida de cobranza: sincroniza fuentes, redacta y deja todo en Aprobaciones…")
    report = run_daily_blocking()
    print(f"Listo: {report}" if report else "Listo.")
    return 0


def _check(label: str, ok: bool, detail: str) -> None:
    mark = "ok" if ok else "--"
    print(f"  [{mark}] {label}: {detail}")


def cmd_doctor(_args: argparse.Namespace) -> int:
    from aiuda_core.config import settings
    from aiuda_core.db import create_all, default_data_dir, resolved_database_url, session_scope

    print(f"aiuda doctor ({_version()})")

    # Datos y llave
    data_dir = default_data_dir()
    _check("Carpeta de datos", os.access(data_dir, os.W_OK), str(data_dir))
    db_url = resolved_database_url()
    _check("Base de datos", True, db_url if not db_url.startswith("sqlite") else db_url.replace("sqlite:///", ""))
    try:
        from aiuda_core.security import crypto, keystore

        crypto.encrypt("doctor")
        via = (
            "AIUDA_ENCRYPTION_KEYS (la administras tú)"
            if (os.environ.get("AIUDA_ENCRYPTION_KEYS") or settings.aiuda_encryption_keys)
            else keystore.describe()
        )
        _check("Llave de cifrado", True, via)
    except Exception as exc:  # noqa: BLE001
        _check("Llave de cifrado", False, str(exc))

    # IA
    create_all()
    with session_scope() as db:
        from aiuda_server.api.deps import get_workspace
        from aiuda_core.engine.provider import credential_from_config, credential_from_store

        tenant = get_workspace(db)
        cred = credential_from_store(db, tenant.id) or credential_from_config(tenant.config or {})
    if cred is not None:
        _check("Proveedor de IA", True, f"{cred.name} ({cred.mode}) conectado en la consola")
    elif settings.anthropic_api_key:
        _check("Proveedor de IA", True, "ANTHROPIC_API_KEY del entorno")
    else:
        _check("Proveedor de IA", False, "sin conectar, hazlo en la consola (/proveedor)")

    # El CLI ya instalado: la vía de un clic desde la consola.
    from aiuda_core.engine.cli_runner import detectar

    instalados = [n for n in ("claude", "codex") if detectar(n)]
    _check(
        "Claude Code / Codex instalados",
        bool(instalados),
        (", ".join(instalados) + ", conéctalos con un clic en la consola")
        if instalados
        else "ninguno en el PATH (opcional)",
    )

    # Ollama (IA local)
    try:
        from urllib.request import urlopen

        with urlopen("http://localhost:11434/api/version", timeout=2) as res:
            _check("Ollama (IA local)", True, f"respondiendo ({res.status})")
    except Exception:  # noqa: BLE001
        _check("Ollama (IA local)", False, "no responde en :11434 (opcional)")

    # Consola empaquetada
    from aiuda_server.console import console_dir

    root = console_dir()
    _check("Consola", root is not None, str(root) if root else "sin export (cd web && NEXT_EXPORT=1 npm run build)")

    # CUA (navegador que opera portales)
    try:
        from aiuda_core.cua.computer import estado_navegador

        listo, detalle = estado_navegador()
        _check("CUA (Playwright/Chromium)", listo, detalle)
    except Exception as exc:  # noqa: BLE001
        _check("CUA (Playwright/Chromium)", False, f"opcional — {exc}")

    # WhatsApp local
    wacli = shutil.which(settings.wacli_bin)
    _check("wacli (WhatsApp local)", wacli is not None, wacli or "no está en el PATH (opcional)")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(_version())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiuda", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="arranca API + consola + scheduler y abre el navegador")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_start.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    p_start.add_argument("--no-token", action="store_true", help="sin token de sesión (solo dev)")
    p_start.add_argument("--quiet", action="store_true", help="menos logs")
    p_start.add_argument(
        "--exit-with-parent",
        action="store_true",
        help="apagarse cuando muera quien lo lanzó (lo usa la app de escritorio)",
    )
    p_start.set_defaults(fn=cmd_start)

    sub.add_parser("daily", help="corre la corrida de cobranza ahora").set_defaults(fn=cmd_daily)
    sub.add_parser("doctor", help="revisa la instalación").set_defaults(fn=cmd_doctor)
    sub.add_parser("version", help="versión instalada").set_defaults(fn=cmd_version)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
