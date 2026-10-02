"""Panel de la IA del negocio: conectar Claude, OpenAI, el CLI que ya tienes, u Ollama.

Tres vías, todas legítimas y sin letras chicas:

  - Tu API key (Claude u OpenAI), por PUT /v1/provider con mode=api_key.
  - El binario que YA tienes instalado (`claude`, `codex`), con mode=cli. Lo lanzamos como
    subproceso y él se autentica con TU sesión: aiuda nunca ve tu token. Es la vía de un
    clic para quien ya paga una suscripción.
  - Un modelo en tu computadora (Ollama, LM Studio, vLLM), con name=local.

El secreto del proveedor se guarda CIFRADO por tenant en IntegrationCredential
(provider='ia'), con la misma maquinaria que las integraciones — nunca en texto
plano. `name` y `mode` van en public_config (no secretos). La resolución efectiva
(fila cifrada → config legado → entorno) vive en core (aiuda_core.engine.provider).

QUÉ SE QUITÓ. Existió un modo `subscription` que tomaba el token OAuth de
`claude setup-token` y, del lado de OpenAI, un device flow contra chatgpt.com. Los dos
sostenían la afirmación de ser un cliente oficial para que el backend aceptara el token.
Eso no se reparte en un proyecto abierto. Quien quiera usar su suscripción instala el CLI
y lo elige aquí: mismo clic, y sin que aiuda toque su credencial.
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.engine import codex
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
        "env_fallback": (not conectado) and bool(settings.anthropic_api_key),
        "secret": "" if retirado else (MASK if has_secret else ""),
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
