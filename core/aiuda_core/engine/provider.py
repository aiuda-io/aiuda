"""Resolución de credenciales del proveedor de IA y construcción del cliente.

aiuda es BYO-credentials: el motor habla con Anthropic con una de dos vías.

  api_key       → la vía con licencia. `anthropic.Anthropic(api_key=...)` (x-api-key).
  subscription  → token OAuth de `claude setup-token` (plan Pro/Max). Se manda como
                  Authorization: Bearer + header beta, imitando a Claude Code.

NOTA HONESTA: la vía `subscription` usa la suscripción personal del dueño EN SU
máquina (aiuda es local-first), parecido a como la usa Claude Code. Aun así no es
una vía oficial de Anthropic; la UI lo dice sin alarmismo. Las vías sin letras
chicas son `api_key` y el proveedor `local` (Ollama).

La credencial se resuelve en este orden:
  1. tenant.config["provider"] (lo que el usuario conectó en el panel /proveedor)
  2. settings.anthropic_api_key (variable de entorno, compat self-host)
"""

import json
import time
from dataclasses import dataclass

import anthropic

from aiuda_core.config import settings

# Header beta que habilita el modo OAuth contra api.anthropic.com (igual que Claude Code).
OAUTH_BETA = "oauth-2025-04-20"

# Timeout explícito por llamada al proveedor, en segundos. El default del SDK son
# 10 MINUTOS por llamada (con 2 reintentos): una redacción colgada retenía la
# transacción de la corrida y el dueño veía "database is locked" al querer
# aprobar. 120 s sobran para redactar un recordatorio; si la red está mal, mejor
# fallar limpio y que la siguiente corrida horaria lo intente de nuevo.
LLM_TIMEOUT_S = 120.0

# Anthropic rechaza el token OAuth si el primer bloque `system` no declara la identidad de
# Claude Code. Se antepone solo en modo suscripción.
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

ProviderName = str  # "claude" | "codex" | "local" | "claude_cli" | "codex_cli"
ProviderMode = str  # "api_key" | "subscription" | "cli"

# "local" = cualquier endpoint OpenAI-compatible en tu máquina o red (Ollama,
# LM Studio, vLLM). Su secreto es un JSON {base_url, model, api_key opcional} y
# su modo siempre es api_key (no hay suscripción que rentar).
# "claude_cli"/"codex_cli" = el CLI que el dueño YA tiene instalado y con su
# sesión iniciada. Un clic y listo: sin token que pegar ni terminal que abrir.
VALID_NAMES = ("claude", "codex", "local", "claude_cli", "codex_cli")
VALID_MODES = ("api_key", "subscription", "cli")


@dataclass(frozen=True)
class ProviderCredential:
    name: ProviderName
    mode: ProviderMode
    secret: str


def credential_from_config(config: dict | None) -> ProviderCredential | None:
    """Lee la credencial que el usuario conectó en el panel (tenant.config['provider'])."""
    prov = (config or {}).get("provider")
    if not isinstance(prov, dict):
        return None
    secret = (prov.get("secret") or "").strip()
    name = prov.get("name") or "claude"
    mode = prov.get("mode") or "api_key"
    # El CLI del dueño no guarda secreto: su sesión vive dentro del CLI.
    if not secret and mode != "cli":
        return None
    if name not in VALID_NAMES or mode not in VALID_MODES:
        return None
    return ProviderCredential(name=name, mode=mode, secret=secret)


def codex_tokens(cred: ProviderCredential | None) -> dict | None:
    """Extrae el bundle de token de Codex (ChatGPT) del secreto CIFRADO POR TENANT.

    Para ``codex`` el secreto guarda el JSON {access_token, refresh_token, account_id}
    (por tenant, así el runner NO comparte el archivo global ~/.codex/auth.json). Devuelve
    el bundle o None si el secreto es legado (guardaba solo el account_id, texto sin JSON)
    o incompleto — en ese caso el runner cae al archivo local (self-host)."""
    if cred is None or cred.name != "codex":
        return None
    raw = (cred.secret or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None  # secreto legado (solo account_id): sin bundle, self-host usa el archivo
    if not isinstance(data, dict) or not (data.get("access_token") or "").strip():
        return None
    return {
        "access_token": (data.get("access_token") or "").strip(),
        "refresh_token": (data.get("refresh_token") or "").strip(),
        "account_id": (data.get("account_id") or "").strip(),
    }


def default_credential() -> ProviderCredential | None:
    """Fallback a la API key del entorno (self-host actual). None si no hay ninguna."""
    if settings.anthropic_api_key:
        return ProviderCredential(name="claude", mode="api_key", secret=settings.anthropic_api_key)
    return None


def credential_from_store(session, tenant_id: str) -> ProviderCredential | None:
    """Lee la credencial de IA del almacén CIFRADO por tenant (IntegrationCredential
    'ia'). El resolver de credenciales ya cubre el fallback al texto plano legado
    (tenant.config['provider']). None si no hay un secreto usable."""
    from aiuda_core.connectors.credentials import get_credential

    data = get_credential(session, tenant_id, "ia")
    if not data:
        return None
    secret = (data.get("secret") or "").strip()
    name = data.get("name") or "claude"
    mode = data.get("mode") or "api_key"
    if not secret and mode != "cli":
        return None
    if name not in VALID_NAMES or mode not in VALID_MODES:
        return None
    return ProviderCredential(name=name, mode=mode, secret=secret)


def resolve_credential(
    config: dict | None = None,
    *,
    session=None,
    tenant_id: str | None = None,
) -> ProviderCredential | None:
    """Credencial efectiva del proveedor de IA.

    Con ``session`` + ``tenant_id``: prefiere la fila CIFRADA del tenant; si no hay,
    cae al texto plano legado de ``tenant.config['provider']`` (vía el resolver de
    credenciales) y al final al entorno. Sin ellos (compat/tests): solo el config
    en claro y el entorno. El secreto NUNCA se lee desde ``config`` cuando hay una
    fila cifrada disponible."""
    if session is not None and tenant_id is not None:
        return credential_from_store(session, tenant_id) or default_credential()
    return credential_from_config(config or {}) or default_credential()


def build_anthropic_client(cred: ProviderCredential) -> anthropic.Anthropic:
    """Construye el cliente Anthropic según el modo de la credencial.

    En `subscription` se manda Authorization: Bearer (auth_token) + header beta; el SDK
    no filtra x-api-key cuando se usa auth_token (verificado). En `api_key`, la vía normal.
    """
    if cred.mode == "subscription":
        # El token de suscripción (claude setup-token) trae límites de ráfaga muy
        # bajos. Con los reintentos default del SDK (2 → 3 intentos rápidos por
        # llamada) un 429 se RE-dispara al instante y nunca cede. Con max_retries=0
        # mandamos un solo intento: si el plan tiene cupo, pasa; si no, falla limpio
        # en vez de gastar el límite martillándolo. (api_key conserva los reintentos.)
        return anthropic.Anthropic(
            auth_token=cred.secret,
            default_headers={"anthropic-beta": OAUTH_BETA},
            max_retries=0,
            timeout=LLM_TIMEOUT_S,
        )
    return anthropic.Anthropic(api_key=cred.secret, timeout=LLM_TIMEOUT_S)


def oauth_system_prefix(cred: ProviderCredential | None) -> str | None:
    """Preámbulo de identidad requerido por el modo suscripción; None en cualquier otro caso."""
    if cred is not None and cred.mode == "subscription":
        return CLAUDE_CODE_IDENTITY
    return None


def test_credential(
    cred: ProviderCredential,
    *,
    model: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict:
    """Hace UNA llamada mínima real a Anthropic con esta credencial, por el MISMO camino
    que usa el motor (mismo cliente, mismo prefijo de identidad en suscripción). Sirve para
    que el dueño confirme, al conectar, que su token/API key de verdad funciona.

    Nunca relanza: devuelve siempre un dict con veredicto honesto.
      ok=True  → {ok, mode, model, latency_ms}
      ok=False → {ok, mode, code, error}  (code: auth|permission|rate_limit|status|network|unknown)
    `client` inyectable para tests."""
    model = model or settings.model_triage
    cli = client if client is not None else build_anthropic_client(cred)
    system = oauth_system_prefix(cred)  # requerido: sin él, Anthropic rechaza el token OAuth
    kwargs: dict = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    if system:
        kwargs["system"] = system
    t0 = time.monotonic()
    try:
        cli.messages.create(**kwargs)
        return {
            "ok": True,
            "mode": cred.mode,
            "model": model,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except anthropic.AuthenticationError:
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "auth",
            "error": "El token no autorizó (401). Revisa que sea válido y esté vigente.",
        }
    except anthropic.PermissionDeniedError:
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "permission",
            "error": (
                "Sin permiso (403). La suscripción no autorizó esta vía, o la cuenta no "
                "tiene acceso al modelo."
                if cred.mode == "subscription"
                else "Sin permiso (403). La cuenta no tiene acceso a este modelo."
            ),
        }
    except anthropic.RateLimitError:
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "rate_limit",
            "error": "Límite de ráfaga (429). El plan no tiene cupo ahora; reintenta en unos segundos.",
        }
    except anthropic.APIConnectionError:
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "network",
            "error": "No se pudo conectar con Anthropic (red o tiempo de espera).",
        }
    except anthropic.APIStatusError as e:
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "status",
            "error": f"Anthropic respondió {e.status_code}. Reintenta en un momento.",
        }
    except Exception as e:  # noqa: BLE001 — el test nunca debe tumbar el endpoint
        return {
            "ok": False,
            "mode": cred.mode,
            "code": "unknown",
            "error": (str(e)[:200] or "Error desconocido al probar la conexión."),
        }
