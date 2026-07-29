"""Panel de proveedor de IA: conectar Claude u OpenAI, simétricos (API key o suscripción).

OpenAI se conecta de tres formas:
  - Suscripción por device code ("Iniciar sesión con ChatGPT"): /v1/provider/openai/device/
    start + /device/poll. El dueño aprueba un código en su navegador; nada se pega ni se corre
    en el servidor. Es la vía recomendada para suscripción.
  - API key (sk-...): por PUT /v1/provider (name=codex, mode=api_key), igual que la API key de
    Claude. La vía soportada y facturada por OpenAI; el motor habla la Responses API estándar.
  - Pegar auth.json: /v1/provider/openai/connect, fallback de power-user/self-host.

El secreto del proveedor se guarda CIFRADO por tenant en IntegrationCredential
(provider='ia'), con la misma maquinaria que las integraciones — nunca en texto
plano. `name` y `mode` van en public_config (no secretos). La resolución efectiva
(fila cifrada → config legado → entorno) vive en core (aiuda_core.engine.provider).

Nota de honestidad: el modo "subscription" usa el token OAuth de `claude setup-token`,
que queda fuera de los términos de suscripción de Anthropic. Es opt-in; la consola lo
advierte.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.engine import codex
from aiuda_core.engine.codex import CodexRunner
from aiuda_core.engine.provider import (
    VALID_MODES,
    VALID_NAMES,
    resolve_credential,
    test_credential,
)
from aiuda_core.engine.runner import make_runner
from aiuda_core.models import IntegrationCredential, Tenant

router = APIRouter()

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
        return {
            "name": stored.get("name") or "claude",
            "mode": stored.get("mode") or "api_key",
            "has_secret": bool((stored.get("secret") or "").strip()),
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
    state = {
        "name": v["name"],
        "mode": v["mode"],
        "connected": conectado,
        # Honestidad: sin credencial en el panel pero con API key en el entorno,
        # la app igual funciona. La UI lo muestra como "activo por variable de entorno".
        "env_fallback": (not conectado) and bool(settings.anthropic_api_key),
        "secret": MASK if has_secret else "",
    }
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
    al conectar, si su token/API key/suscripción de verdad funciona."""
    credential = resolve_credential(session=db, tenant_id=tenant.id)
    if credential is None:
        return {
            "ok": False,
            "code": "not_configured",
            "error": "No hay proveedor conectado. Conecta tu API key o suscripción primero.",
        }
    if credential.name == "codex":
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
    if name == "codex" and mode == "subscription":
        # OpenAI por SUSCRIPCIÓN no se conecta pegando un secreto: se hace por OAuth (device
        # code, "Iniciar sesión con ChatGPT"), en /v1/provider/openai/device/*. La vía API key
        # (sk-...) sí es un secreto y pasa por aquí, igual que la API key de Claude.
        raise HTTPException(
            status_code=400,
            detail="Conecta la suscripción de OpenAI con 'Iniciar sesión con ChatGPT', no pegando un secreto.",
        )
    if name == "local" and mode != "api_key":
        raise HTTPException(status_code=400, detail="La IA local no usa suscripción.")
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
        return {"name": name, "mode": "cli", "connected": True}

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
        secret = (prev.get("secret") or "").strip()
        if not secret:
            legacy = _legacy_provider(tenant)
            secret = (legacy.get("secret") or "").strip() if legacy else ""
    if not secret:
        raise HTTPException(status_code=400, detail="Falta el token o la API key.")

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
    return {"name": name, "mode": mode, "connected": True}


class OpenAIConnectBody(BaseModel):
    """El dueño corre `codex login` en SU máquina (OAuth en su propio navegador) y pega aquí
    el contenido de ~/.codex/auth.json — o los tokens sueltos. En self-host de una sola
    máquina puede omitirse todo: se lee el archivo local."""

    auth_json: str = ""
    access_token: str = ""
    refresh_token: str = ""
    account_id: str = ""


def _bundle_desde_body(body: OpenAIConnectBody) -> dict | None:
    """Extrae el bundle {access_token, refresh_token, account_id} de lo que pegó el dueño."""
    if body.auth_json.strip():
        return codex.tokens_from_json(body.auth_json)
    if body.access_token.strip():
        return {
            "access_token": body.access_token.strip(),
            "refresh_token": body.refresh_token.strip(),
            "account_id": body.account_id.strip(),
        }
    return None


def _save_codex_bundle(db, tenant: Tenant, bundle: dict, actor) -> None:
    """Persiste el bundle de suscripción de OpenAI CIFRADO por tenant (name=codex,
    mode=subscription). Único punto de guardado, reusado por el pegado de auth.json y por el
    device code — el runner autentica con este bundle, no con un archivo global."""
    secret = json.dumps(
        {
            "access_token": bundle["access_token"],
            "refresh_token": bundle.get("refresh_token", ""),
            "account_id": bundle.get("account_id", ""),
        },
        separators=(",", ":"),
    )
    cred.set_credential(db, tenant.id, IA, {"name": "codex", "mode": "subscription", "secret": secret})
    _scrub_legacy(db, tenant)
    db.flush()
    audit.record(
        db,
        tenant_id=tenant.id,
        action="provider.update",
        entity_type="provider",
        entity_id=IA,
        principal=actor,
        after={"name": "codex", "mode": "subscription"},
    )


@router.post("/v1/provider/openai/connect")
def connect_openai(
    body: OpenAIConnectBody | None = None,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Conecta OpenAI (Sign in with ChatGPT) guardando el bundle de token CIFRADO POR TENANT.

    Varios workspaces: el dueño corre `codex login` en SU máquina y pega el auth.json (o los
    tokens). Self-host de una máquina: si no pega nada, se lee el ~/.codex/auth.json local.
    NUNCA se ejecuta `codex login` en el servidor (mutaría un archivo global compartido entre
    tenants — la fuga que este cambio cierra). Verifica con una llamada REAL usando ESTE
    bundle antes de guardar; persiste el bundle completo cifrado (name=codex, mode=subscription)."""
    body = body or OpenAIConnectBody()
    bundle = _bundle_desde_body(body)
    if bundle is None and (body.auth_json.strip() or body.access_token.strip()):
        raise HTTPException(status_code=400, detail="Lo pegado no trae un access_token válido de OpenAI.")
    if bundle is None:
        # Self-host: la sesión local de codex de esta máquina.
        bundle = codex.read_tokens()
    if bundle is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No hay sesión de OpenAI. En tu máquina corre `codex login`, autoriza en el "
                "navegador, y pega aquí el contenido de ~/.codex/auth.json."
            ),
        )

    # Verifica con el bundle DE ESTE TENANT (no el archivo global): no guardamos lo que no responde.
    verdict = codex.test_codex(CodexRunner(tokens=bundle))
    if not verdict.get("ok"):
        raise HTTPException(status_code=502, detail=verdict.get("error", "OpenAI no respondió."))

    _save_codex_bundle(db, tenant, bundle, actor)
    return {"name": "codex", "mode": "subscription", "connected": True, "test": verdict}


class OpenAIDevicePollBody(BaseModel):
    """Lo que la consola reenvía en cada sondeo: el código de dispositivo y el user_code que
    recibió al arrancar (OpenAI exige ambos en el poll)."""

    device_code: str = ""
    user_code: str = ""


@router.post("/v1/provider/openai/device/start")
def openai_device_start(
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Arranca "Iniciar sesión con ChatGPT" (device code). Devuelve el código de un solo uso,
    la URL que el dueño abre, el intervalo de sondeo y la expiración (~15 min). La consola
    sondea /device/poll con esos datos hasta que el dueño autorice en su navegador. No se pega
    ningún secreto ni se corre `codex login` en el servidor."""
    try:
        return codex.device_start()
    except codex.CodexError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/v1/provider/openai/device/poll")
def openai_device_poll(
    body: OpenAIDevicePollBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Sondea el device code una vez (la consola llama esto en bucle según el intervalo).
    Responde {status:pending} hasta que el dueño autorice; al autorizar, canjea la sesión, la
    PRUEBA con una llamada REAL (mismo camino del motor) y la guarda CIFRADA por tenant
    (name=codex, mode=subscription), igual que la vía de pegar auth.json. Devuelve 200 en los
    tres casos (pending/error/success) para que la consola no trate el sondeo como fallo."""
    device_code = body.device_code.strip()
    user_code = body.user_code.strip()
    if not device_code or not user_code:
        raise HTTPException(status_code=400, detail="Falta el código de dispositivo. Reinicia el inicio de sesión.")

    result = codex.device_poll(device_code, user_code)
    status = result.get("status")
    if status == "pending":
        return {"status": "pending"}
    if status != "success":
        return {"status": "error", "detail": result.get("error", "No se pudo autorizar con OpenAI.")}

    bundle = result.get("bundle") or {}
    if not (bundle.get("access_token") or "").strip():
        return {"status": "error", "detail": "OpenAI autorizó pero no devolvió una sesión utilizable."}

    # Verifica con el bundle DE ESTE TENANT antes de guardar: no persistimos lo que no responde.
    verdict = codex.test_codex(CodexRunner(tokens=bundle))
    if not verdict.get("ok"):
        return {"status": "error", "detail": verdict.get("error", "La sesión de OpenAI no respondió.")}

    _save_codex_bundle(db, tenant, bundle, actor)
    return {"status": "success", "name": "codex", "mode": "subscription", "connected": True, "test": verdict}


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
    if row is not None:
        db.delete(row)
    _scrub_legacy(db, tenant)
    db.flush()
    return {"connected": False, "env_fallback": bool(settings.anthropic_api_key)}


def _scrub_legacy(db, tenant: Tenant) -> None:
    """Borra el residuo en texto plano de tenant.config['provider'] (fin del
    callejón en claro). Reasigna el dict: las columnas JSON no trackean mutación."""
    cfg = dict(tenant.config or {})
    if cfg.pop("provider", None) is not None:
        tenant.config = cfg
        db.add(tenant)
