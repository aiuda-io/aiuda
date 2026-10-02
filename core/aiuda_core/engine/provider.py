"""Resolución de credenciales del proveedor de IA y construcción del cliente.

aiuda es BYO-credentials y no hay letras chicas. Tres vías, todas legítimas:

  api_key  → tu llave. `anthropic.Anthropic(api_key=...)` (x-api-key).
  cli      → el binario que YA tienes instalado (`claude`, `codex`). Lo lanzamos como
             subproceso y él se autentica con TU sesión: aiuda nunca ve tu token.
  local    → un endpoint OpenAI-compatible en tu máquina (Ollama, LM Studio, vLLM).

QUÉ SE QUITÓ Y POR QUÉ. Existió una cuarta vía, `subscription`, que tomaba el token
OAuth de `claude setup-token` y lo mandaba a api.anthropic.com anteponiendo al system
prompt la frase "You are Claude Code, Anthropic's official CLI for Claude." Sin esa
frase el backend rechazaba el token: no era un preámbulo de estilo, era una afirmación
falsa que viajaba en cada request para pasar un control de acceso. Correr en local no
lo cambiaba, porque la afirmación salía igual hacia Anthropic.

En un proyecto Apache-2.0 eso no se reparte: el riesgo de términos se le transfiere a
cada persona que lo instale y a cada fork. La magia de "un clic si ya tienes Claude
Code" no se perdió, se movió a donde sí es legítima: el modo `cli`, que lanza TU
binario con TU sesión. Lo mismo del lado de OpenAI con el device flow de Codex contra
chatgpt.com.

La credencial se resuelve en este orden:
  1. tenant.config["provider"] (lo que el usuario conectó en el panel /proveedor)
  2. settings.anthropic_api_key (variable de entorno, compat self-host)
"""

import time
from dataclasses import dataclass

import anthropic

from aiuda_core.config import settings

# Timeout explícito por llamada al proveedor, en segundos. El default del SDK son
# 10 MINUTOS por llamada (con 2 reintentos): una redacción colgada retenía la
# transacción de la corrida y el dueño veía "database is locked" al querer
# aprobar. 120 s sobran para redactar un recordatorio; si la red está mal, mejor
# fallar limpio y que la siguiente corrida horaria lo intente de nuevo.
LLM_TIMEOUT_S = 120.0

ProviderName = str  # "claude" | "codex" | "local" | "claude_cli" | "codex_cli"
ProviderMode = str  # "api_key" | "cli"

# "local" = cualquier endpoint OpenAI-compatible en tu máquina o red (Ollama,
# LM Studio, vLLM). Su secreto es un JSON {base_url, model, api_key opcional} y
# su modo siempre es api_key.
# "claude_cli"/"codex_cli" = el CLI que el dueño YA tiene instalado y con su
# sesión iniciada. Un clic y listo: sin token que pegar ni terminal que abrir.
VALID_NAMES = ("claude", "codex", "local", "claude_cli", "codex_cli")
VALID_MODES = ("api_key", "cli")


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
    """Cliente de Anthropic con la llave del dueño. Una sola vía, sin ramas."""
    return anthropic.Anthropic(api_key=cred.secret, timeout=LLM_TIMEOUT_S)


def test_credential(
    cred: ProviderCredential,
    *,
    model: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict:
    """Hace UNA llamada mínima real a Anthropic con esta credencial, por el MISMO camino
    que usa el motor. Sirve para que el dueño confirme, al conectar, que su llave de
    verdad funciona.

    Nunca relanza: devuelve siempre un dict con veredicto honesto.
      ok=True  → {ok, mode, model, latency_ms}
      ok=False → {ok, mode, code, error}  (code: auth|permission|rate_limit|status|network|unknown)
    `client` inyectable para tests."""
    model = model or settings.model_triage
    cli = client if client is not None else build_anthropic_client(cred)
    kwargs: dict = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
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
            "error": "Sin permiso (403). La cuenta no tiene acceso a este modelo.",
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
