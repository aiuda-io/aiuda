"""Panel de la IA del negocio: conectar Claude, OpenAI, el CLI que ya tienes, u Ollama.

Cuatro vías, todas legítimas y sin letras chicas:

  - Tu API key (Claude u OpenAI), por PUT /v1/provider con mode=api_key.
  - El binario que YA tienes instalado (`claude`, `codex`), con mode=cli. Lo lanzamos como
    subproceso y él se autentica con TU sesión: aiuda nunca ve tu token. Es la vía de un
    clic para quien ya paga una suscripción.
  - Un modelo en tu computadora (Ollama, LM Studio, vLLM), con name=local.
  - Entrar con ChatGPT (name=chatgpt, mode=oauth): el flujo oficial de OpenAI para
    herramientas abiertas que corren en local. No pasa por PUT: empieza en
    POST /v1/provider/chatgpt/iniciar, que abre el navegador, y termina en
    GET /auth/callback, a donde OpenAI regresa al dueño. Ver más abajo.

El secreto del proveedor se guarda CIFRADO por tenant en IntegrationCredential
(provider='ia'), con la misma maquinaria que las integraciones — nunca en texto
plano. `name` y `mode` van en public_config (no secretos). La resolución efectiva
(fila cifrada → config legado → entorno) vive en core (aiuda_core.engine.provider).

QUÉ SE QUITÓ. Existió un modo `subscription` que tomaba el token OAuth de
`claude setup-token` y, del lado de OpenAI, un device flow contra chatgpt.com. Los dos
sostenían la afirmación de ser un cliente oficial para que el backend aceptara el token.
Eso no se reparte en un proyecto abierto. Quien quiera usar su suscripción instala el CLI
y lo elige aquí: mismo clic, y sin que aiuda toque su credencial. Entrar con ChatGPT no
es aquello de regreso: ahí aiuda se registra con su propio nombre y su propio client_id.
"""

import hmac
import html
import logging
import threading
import time
import webbrowser
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, get_workspace, require_role
from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.engine import chatgpt_auth, codex
from aiuda_core.engine.provider import (
    VALID_MODES,
    VALID_NAMES,
    resolve_credential,
    test_credential,
)
from aiuda_core.engine.runner import make_runner
from aiuda_core.models import IntegrationCredential, Tenant

router = APIRouter()
log = logging.getLogger(__name__)

MASK = "••••••"

# Clave bajo la que se cifra/lee el secreto del proveedor de IA en el almacén.
IA = "ia"


class ProviderConfigBody(BaseModel):
    name: str = "claude"
    mode: str = "api_key"
    secret: str = ""


def _legacy_provider(tenant: Tenant) -> dict | None:
    """Residuo en texto plano (tenant.config['provider']) para la transición."""
    prov = (tenant.config or {}).get("provider")
    return prov if isinstance(prov, dict) else None


def _view(db, tenant: Tenant) -> dict:
    """name, mode, has_secret — desde la fila cifrada; en transición, del config legado.

    Si la fila existe pero no se puede descifrar (clave retirada), se considera que
    el secreto está presente (no se filtra nada y la UI sigue mostrando 'conectado')."""
    try:
        stored = cred.read_stored(db, tenant.id, IA)
    except Exception:
        return {"name": "claude", "mode": "api_key", "has_secret": True}
    if stored:
        secreto = (stored.get("secret") or "").strip()
        if stored.get("name") == "chatgpt":
            # Aquí "tener secreto" es tener tokens: una conexión vencida conserva el
            # registro de la app pero ya no sirve para llamar.
            secreto = chatgpt_auth.parse_secret(secreto).get("access_token") or ""
        return {
            "name": stored.get("name") or "claude",
            "mode": stored.get("mode") or "api_key",
            "has_secret": bool(secreto),
        }
    legacy = _legacy_provider(tenant)
    if legacy:
        return {
            "name": legacy.get("name") or "claude",
            "mode": legacy.get("mode") or "api_key",
            "has_secret": bool((legacy.get("secret") or "").strip()),
        }
    return {"name": "claude", "mode": "api_key", "has_secret": False}


def _state(db, tenant: Tenant) -> dict:
    v = _view(db, tenant)
    has_secret = v["has_secret"]
    # El CLI del dueño no tiene secreto que guardar: está conectado si eso es lo
    # que eligió (su sesión vive dentro del propio CLI).
    conectado = has_secret or v["mode"] == "cli"
    # Camino de actualización: quien venía del modo suscripción se quedaría sin IA de un
    # día para otro y sin explicación (el resolver ya no acepta ese modo, a propósito).
    # No se le apaga en silencio: se le dice qué pasó y cuál es la vía equivalente.
    retirado = v["mode"] == "subscription"
    if retirado:
        conectado = False
    state = {
        "name": v["name"],
        "mode": "api_key" if retirado else v["mode"],
        "connected": conectado,
        # Honestidad: sin credencial en el panel pero con API key en el entorno,
        # la app igual funciona. La UI lo muestra como "activo por variable de entorno".
        # Con ChatGPT guardado (aunque esté vencido) NO se cae a esa llave: no se anuncia.
        "env_fallback": (
            (not conectado) and v["name"] != "chatgpt" and bool(settings.anthropic_api_key)
        ),
        # ChatGPT no tiene nada que pegar ni que enmascarar.
        "secret": "" if retirado or v["name"] == "chatgpt" else (MASK if has_secret else ""),
        "chatgpt": _estado_chatgpt(tenant, v),
    }
    if retirado:
        state["aviso_retirado"] = (
            "La conexión por suscripción se retiró: para que el proveedor aceptara ese "
            "token, aiuda tenía que declararse como su programa oficial, y eso no es algo "
            "que podamos pedirte que corras. Si ya tienes Claude Code o Codex instalados, "
            "conéctalos aquí con un clic: se autentican con tu propia sesión y aiuda nunca "
            "ve tu token. También puedes pegar tu API key o usar un modelo de esta "
            "computadora."
        )
    if v["name"] == "local" and has_secret:
        # base_url y modelo NO son secretos: la UI los muestra para editar sin
        # re-capturar. La api_key opcional del endpoint sí queda enmascarada.
        from aiuda_core.engine.openai_compat import parse_local_secret

        try:
            stored = cred.read_stored(db, tenant.id, IA) or {}
            cfg = parse_local_secret(stored.get("secret") or "")
            state["local_config"] = {"base_url": cfg["base_url"], "model": cfg["model"]}
        except Exception:  # noqa: BLE001 — sin descifrado no se filtra nada
            pass
    return state


@router.get("/v1/provider")
def get_provider(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    return _state(db, tenant)


@router.post("/v1/provider/test")
def test_provider(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Prueba REAL de la conexión: resuelve la credencial efectiva del tenant (misma que usa
    el motor) y hace una llamada mínima al proveedor. Veredicto honesto para que el dueño sepa,
    al conectar, si su llave, su programa instalado o su modelo local de verdad funciona."""
    credential = resolve_credential(session=db, tenant_id=tenant.id)
    if credential is None:
        return {
            "ok": False,
            "code": "not_configured",
            "error": "Todavía no conectas tu IA. Conéctala primero y vuelve a probar.",
        }
    if credential.name in ("codex", "chatgpt"):
        # Prueba con el bundle DEL TENANT (make_runner descifra su token), no el archivo global.
        return codex.test_codex(make_runner(credential))
    if credential.name in ("claude_cli", "codex_cli"):
        from aiuda_core.engine.cli_runner import probar

        return probar(credential.name.removesuffix("_cli"))
    if credential.name == "local":
        from aiuda_core.engine.openai_compat import test_local

        return test_local(credential.secret)
    return test_credential(credential)


@router.put("/v1/provider")
def save_provider(
    body: ProviderConfigBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    name, mode = body.name, body.mode
    if name not in VALID_NAMES:
        raise HTTPException(status_code=400, detail="Proveedor desconocido.")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail="Modo de conexión inválido.")
    if name == "chatgpt" or mode == "oauth":
        # Sus tokens solo los pone el regreso del navegador, ya validados.
        raise HTTPException(
            status_code=400,
            detail="ChatGPT se conecta entrando con tu cuenta, no pegando una llave.",
        )
    if name == "local" and mode != "api_key":
        raise HTTPException(status_code=400, detail="La IA local se conecta con su dirección.")
    if name in ("claude_cli", "codex_cli"):
        # Un clic: el dueño ya tiene su CLI instalado y con su sesión iniciada.
        # aiuda no guarda ninguna credencial suya, solo anota qué usar.
        from aiuda_core.engine.cli_runner import detectar

        binario = name.removesuffix("_cli")
        if detectar(binario) is None:
            raise HTTPException(
                status_code=400,
                detail=f"No encontré {binario} en esta computadora.",
            )
        aviso = _soltar_chatgpt(db, tenant)
        cred.set_credential(db, tenant.id, IA, {"name": name, "mode": "cli", "secret": ""})
        _scrub_legacy(db, tenant)
        db.flush()
        audit.record(
            db,
            tenant_id=tenant.id,
            action="provider.update",
            entity_type="provider",
            entity_id=IA,
            principal=actor,
            after={"name": name, "mode": "cli"},
        )
        return _guardada(name, "cli", aviso)

    secret = (body.secret or "").strip()
    # No sobreescribir el secreto guardado con el placeholder enmascarado u omisión:
    # conserva el previo (de la fila cifrada o, en transición, del config legado).
    if secret == MASK or not secret:
        try:
            prev = cred.read_stored(db, tenant.id, IA) or {}
        except Exception:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No se pudo leer la credencial actual para conservarla "
                    "(revisa la clave de cifrado). Vuelve a capturar el token."
                ),
            )
        # Solo se conserva el secreto de ESTE mismo proveedor. El de otro no le sirve, y
        # si lo guardado son los tokens de ChatGPT, heredarlos sería mandárselos como
        # si fueran una llave al proveedor que se está conectando.
        if prev:
            mismo = (prev.get("name") or "claude") == name
            secret = (prev.get("secret") or "").strip() if mismo else ""
        else:
            legacy = _legacy_provider(tenant) or {}
            mismo = (legacy.get("name") or "claude") == name
            secret = (legacy.get("secret") or "").strip() if mismo else ""
    if not secret:
        raise HTTPException(status_code=400, detail="Falta el token o la API key.")

    aviso = _soltar_chatgpt(db, tenant)
    cred.set_credential(db, tenant.id, IA, {"name": name, "mode": mode, "secret": secret})
    _scrub_legacy(db, tenant)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="provider.update",
        entity_type="provider",
        entity_id=IA,
        principal=actor,
        after={"name": name, "mode": mode},  # nunca el secreto
    )
    return _guardada(name, mode, aviso)


_SIN_CONFIRMAR = (
    "no pudimos confirmar la desconexión con OpenAI. Quita aiuda desde la configuración "
    "de ChatGPT."
)


def _soltar_chatgpt(db, tenant: Tenant) -> bool:
    """Antes de borrar o reemplazar la IA guardada: si era ChatGPT, se le avisa a OpenAI
    que esa sesión terminó y se suelta de la memoria del proceso. True si había una
    sesión y OpenAI NO confirmó (se le dice al dueño). Nunca impide el cambio."""
    try:
        bundle = chatgpt_auth.soltar(db, tenant.id)
    except Exception:  # noqa: BLE001 — sin descifrado igual se desconecta
        chatgpt_auth.olvidar(tenant.id)
        return False
    return bool(bundle.get("refresh_token")) and not chatgpt_auth.revocar(bundle)


def _guardada(name: str, mode: str, sin_confirmar: bool) -> dict:
    out = {"name": name, "mode": mode, "connected": True}
    if sin_confirmar:
        out["aviso"] = f"Tu IA quedó conectada, pero {_SIN_CONFIRMAR}"
    return out


@router.delete("/v1/provider")
def disconnect_provider(
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == IA,
        )
    )
    aviso = None
    if row is not None:
        # ChatGPT: primero se le avisa a OpenAI que la sesión terminó, y pase lo que
        # pase se borra de aquí. Si no lo confirmó, se dice. El registro de la app
        # (tenant.config['chatgpt']) se conserva para que volver a entrar no cree otra.
        if _soltar_chatgpt(db, tenant):
            aviso = f"Se borró de esta computadora, pero {_SIN_CONFIRMAR}"
        db.delete(row)
    _scrub_legacy(db, tenant)
    db.flush()
    out = {"connected": False, "env_fallback": bool(settings.anthropic_api_key)}
    if aviso:
        out["aviso"] = aviso
    return out


def _scrub_legacy(db, tenant: Tenant) -> None:
    """Borra el residuo en texto plano de tenant.config['provider'] (fin del
    callejón en claro). Reasigna el dict: las columnas JSON no trackean mutación."""
    cfg = dict(tenant.config or {})
    if cfg.pop("provider", None) is not None:
        tenant.config = cfg
        db.add(tenant)


# --------------------------------------------------------------------------- #
# Entrar con ChatGPT                                                           #
# --------------------------------------------------------------------------- #
# El dueño pica el botón, aiuda abre SU navegador en la página de OpenAI, él entra
# con su cuenta y OpenAI lo regresa a http://127.0.0.1:<puerto>/auth/callback. Ese
# regreso llega desde el navegador del sistema, que no trae la cookie de la consola:
# por eso la ruta está exenta del guardia de sesión (solo en la puerta local, ver
# main.py) y lo que la protege es el `state` del intento, que nadie más conoce, y el
# verificador de PKCE, que nunca sale de este proceso.
#
# Lo que NO es secreto y debe sobrevivir a desconectar vive en
# tenant.config["chatgpt"]: el identificador de esta instalación, el client_id que
# OpenAI le emitió a aiuda y la cuenta con la que se registró.

CALLBACK = "/auth/callback"
INTENTO_TTL_S = 600

# Un solo intento a la vez, en memoria: si el proceso se reinicia a medio login, el
# dueño vuelve a picar el botón. `error` guarda cómo terminó el último, para que la
# consola (que sondea GET /v1/provider) se lo pueda decir.
_candado_intento = threading.Lock()
_pendiente: dict = {"intento": None, "creado": 0.0, "error": None}


class ChatGPTInicioBody(BaseModel):
    # Registrar otra cuenta en vez de volver a entrar a la que ya estaba.
    otra_cuenta: bool = False


def _cfg_chatgpt(tenant: Tenant) -> dict:
    cfg = (tenant.config or {}).get("chatgpt")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _guardar_cfg_chatgpt(db, tenant: Tenant, cfg: dict) -> None:
    """Reasigna el dict: las columnas JSON no trackean mutación. Se guarda una COPIA:
    si quien llama sigue editando `cfg`, estaría mutando el valor ya guardado y el
    siguiente guardado se vería idéntico (y no se escribiría)."""
    tenant.config = {**(tenant.config or {}), "chatgpt": dict(cfg)}
    db.add(tenant)
    db.flush()


def _intento_vivo():
    intento = _pendiente["intento"]
    if intento is not None and time.monotonic() - _pendiente["creado"] > INTENTO_TTL_S:
        _pendiente["intento"] = intento = None
    return intento


def _estado_chatgpt(tenant: Tenant, vista: dict) -> dict:
    cfg = _cfg_chatgpt(tenant)
    activa = vista["name"] == "chatgpt"
    with _candado_intento:
        pendiente, error = _intento_vivo() is not None, _pendiente["error"]
    return {
        # Hay un login abierto en el navegador y todavía no regresa.
        "pendiente": pendiente,
        # Cómo terminó el último intento, si terminó mal.
        "error": error,
        # La cuenta registrada (se conserva al desconectar, para volver a entrar).
        "email": cfg.get("email"),
        "registrada": bool(cfg.get("client_id")),
        # Era la IA conectada y su sesión venció: toca volver a entrar.
        "vencida": activa and not vista["has_secret"],
        "bienvenida_vista": bool(cfg.get("bienvenida_vista")),
    }


def _abrir(url: str) -> bool:
    """Abre el navegador de ESTA computadora. False si no se pudo (o está apagado)."""
    if not settings.abrir_navegador:
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 — sin navegador, la consola enseña el enlace
        return False


def _solo_en_esta_computadora(request: Request) -> None:
    if request.scope.get("aiuda_puerta") == "red":
        raise HTTPException(
            status_code=400,
            detail="Esto se hace en la computadora donde corre aiuda: ahí se abre el navegador.",
        )


@router.post("/v1/provider/chatgpt/iniciar")
def chatgpt_iniciar(
    request: Request,
    body: ChatGPTInicioBody | None = None,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Empieza a entrar con ChatGPT: arma el intento y abre el navegador. Devuelve la
    URL por si el navegador no abrió solo. Nada queda conectado hasta el regreso."""
    _solo_en_esta_computadora(request)
    servidor = request.scope.get("server")
    if not servidor or not servidor[1]:
        raise HTTPException(status_code=400, detail="No se pudo saber en qué puerto corre aiuda.")

    cfg = _cfg_chatgpt(tenant)
    if not cfg.get("host_id"):
        # Se guarda ANTES del primer login: identifica a esta instalación de aquí en adelante.
        cfg["host_id"] = chatgpt_auth.nuevo_host_id()
        _guardar_cfg_chatgpt(db, tenant, cfg)
    client_id = None if (body and body.otra_cuenta) else cfg.get("client_id")
    # 127.0.0.1 literal (no localhost) y esta ruta exacta: es lo que OpenAI acepta.
    intento = chatgpt_auth.nuevo_intento(
        f"http://127.0.0.1:{servidor[1]}{CALLBACK}",
        host_id=cfg["host_id"],
        client_id=client_id,
        email=cfg.get("email"),
    )
    with _candado_intento:
        _pendiente.update(intento=intento, creado=time.monotonic(), error=None)
    return {"url": intento.url, "abierto": _abrir(intento.url)}


@router.post("/v1/provider/chatgpt/entendido")
def chatgpt_entendido(
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """El dueño ya leyó el aviso de que se está usando su plan: no se le repite."""
    cfg = _cfg_chatgpt(tenant)
    cfg["bienvenida_vista"] = True
    _guardar_cfg_chatgpt(db, tenant, cfg)
    return {"bienvenida_vista": True}


@router.post("/v1/provider/chatgpt/uso")
def chatgpt_uso(request: Request, _: object = Depends(require_role("admin"))):
    """Abre en el navegador la página de ChatGPT donde se ve y se limita el uso. Va por
    el server porque en la app de escritorio un enlace a otra ventana no abre nada."""
    _solo_en_esta_computadora(request)
    return {"url": chatgpt_auth.USO_URL, "abierto": _abrir(chatgpt_auth.USO_URL)}


def _pagina(ok: bool, mensaje: str, status: int = 200) -> HTMLResponse:
    """Lo que ve el dueño en la pestaña del navegador al regresar de OpenAI."""
    titulo = "Listo" if ok else "No se pudo conectar"
    cuerpo = f"""<!doctype html>
<html lang="es-MX"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aiuda</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f6f3;
color:#1c1b19;font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:28rem;padding:2rem}}h1{{font-size:1.25rem;margin:0 0 .5rem}}p{{margin:0;color:#55524c}}
</style></head><body><main><h1>{titulo}</h1><p>{html.escape(mensaje)}</p></main></body></html>"""
    return HTMLResponse(
        cuerpo,
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


_NO_ES_ESTE = "Este enlace no corresponde a un intento abierto. Vuelve a aiuda e inténtalo otra vez."


@router.get(CALLBACK, include_in_schema=False)
def chatgpt_callback(request: Request, db=Depends(get_db)):
    """El regreso de OpenAI. Sin cookie de sesión: se valida por `state` y PKCE."""
    if request.scope.get("aiuda_puerta") == "red":
        return _pagina(False, _NO_ES_ESTE, 404)
    q = request.query_params
    estados = q.getlist("state")
    with _candado_intento:
        intento = _intento_vivo()
        # Un regreso que no trae EL state de este intento no lo consume: si no,
        # cualquier página abierta en el navegador podría tumbarle el login al dueño.
        if (
            intento is None
            or len(estados) != 1
            or not hmac.compare_digest(estados[0].encode(), intento.state.encode())
            # Por la misma dirección exacta que se le dio a OpenAI, no por otro nombre.
            or request.headers.get("host") != urlsplit(intento.redirect_uri).netloc
        ):
            return _pagina(False, _NO_ES_ESTE, 400)
        _pendiente["intento"] = None  # un intento sirve una sola vez

    tenant = get_workspace(db)
    try:
        _terminar_entrada(db, tenant, intento, q)
    except chatgpt_auth.ChatGPTAuthError as exc:
        mensaje = str(exc)
        with _candado_intento:
            _pendiente["error"] = mensaje
        return _pagina(False, f"{mensaje} Vuelve a aiuda e inténtalo otra vez.")
    return _pagina(True, "Ya puedes cerrar esta pestaña y volver a aiuda.")


def _terminar_entrada(db, tenant: Tenant, intento, q) -> None:
    """Valida el regreso, canjea el código y deja la conexión guardada. Cualquier cosa
    que no cuadre lanza ChatGPTAuthError con el mensaje para el dueño."""
    Error = chatgpt_auth.ChatGPTAuthError
    if q.get("error"):
        if q.get("error") == "access_denied":
            raise Error("No diste permiso. No se conectó nada.")
        log.warning("chatgpt: el regreso trajo error=%s", q.get("error")[:60])
        raise Error("ChatGPT no completó la entrada.")
    code = q.get("code")
    if not code:
        raise Error("ChatGPT no completó la entrada.")

    cfg = _cfg_chatgpt(tenant)
    devuelto = q.get("client_id")
    if intento.client_id is None:
        # Registro nuevo: OpenAI tiene que devolver el client_id que le emitió a aiuda.
        # El de arranque no es un client_id: guardarlo sería no haberse registrado.
        if not devuelto or devuelto == chatgpt_auth.CLIENTE_REGISTRO:
            raise Error("ChatGPT no terminó de registrar a aiuda.")
        client_id = devuelto
        # Se guarda ANTES de canjear: si el canje falla, el siguiente intento vuelve a
        # entrar con este registro en vez de crear otra app en la cuenta del dueño.
        cfg = {
            "host_id": cfg["host_id"],
            "client_id": client_id,
            "bienvenida_vista": bool(cfg.get("bienvenida_vista")),
        }
        _guardar_cfg_chatgpt(db, tenant, cfg)
        db.commit()
    else:
        # Volver a entrar: el client_id puede no venir; si viene, tiene que ser el mismo.
        if devuelto and devuelto != intento.client_id:
            raise Error("ChatGPT contestó para otra aplicación. No se conectó nada.")
        client_id = intento.client_id

    tok = chatgpt_auth.canjear(intento, code, client_id)
    try:
        datos = chatgpt_auth.verificar_id_token(
            tok.get("id_token") or "", client_id=client_id, nonce=intento.nonce
        )
        if cfg.get("subject") and cfg["subject"] != datos["sub"]:
            raise Error(
                "Entraste con una cuenta distinta a la que ya estaba registrada. "
                "Para cambiar de cuenta usa Entrar con otra cuenta."
            )
        # Una identidad válida no basta: sin este permiso no se puede usar el plan.
        if chatgpt_auth.SCOPE_PLAN not in (tok.get("scope") or "").split():
            raise Error(
                "Entraste, pero no autorizaste usar tu plan de ChatGPT. Sin eso tus "
                "ayudantes no pueden redactar."
            )
        bundle = chatgpt_auth.armar_bundle(
            tok,
            previo={"client_id": client_id, "subject": datos["sub"], "email": datos.get("email")},
        )
        bundle["model"] = chatgpt_auth.elegir_modelo(bundle["access_token"])
    except Error:
        # Los tokens recién emitidos no se van a usar: se le avisa a OpenAI y se tiran.
        chatgpt_auth.revocar({"client_id": client_id, "refresh_token": tok.get("refresh_token")})
        raise

    cred.set_credential(db, tenant.id, IA, chatgpt_auth.valores(bundle))
    chatgpt_auth.recordar(tenant.id, bundle)
    _scrub_legacy(db, tenant)
    cfg.update(subject=datos["sub"], email=datos.get("email"))
    _guardar_cfg_chatgpt(db, tenant, cfg)
    audit.record(
        db,
        tenant_id=tenant.id,
        action="provider.update",
        entity_type="provider",
        entity_id=IA,
        after={"name": "chatgpt", "mode": "oauth"},  # nunca los tokens
    )
