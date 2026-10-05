"""Entrar con ChatGPT: el dueño usa SU plan de ChatGPT desde aiuda, por la vía oficial.

Es el flujo "Sign in with ChatGPT" que OpenAI publica para herramientas abiertas que
corren en la computadora del usuario (developers.openai.com/siwc). No es la vía que se
retiró: aquella mandaba el token haciéndose pasar por el CLI de Codex contra
chatgpt.com/backend-api. Esta es distinta en lo que importa:

  - aiuda se registra con SU nombre (`agent_name_hint=aiuda`) y OpenAI le emite un
    `client_id` propio durante el login. No hay secreto ni identidad prestada.
  - La inferencia va a la Responses API pública (api.openai.com/v1/responses) con el
    access token como Bearer, sin ningún encabezado de otro cliente.
  - El dueño ve la app en su configuración de ChatGPT y ahí la limita o la quita.

Aquí vive solo el protocolo (PKCE, canje, validación del ID token, renovación y
revocación). Las rutas HTTP están en aiuda_server.api.provider; el runner es el mismo
CodexRunner de la llave, con el token en lugar de la llave.

El token de acceso dura una hora y el de renovación ROTA: cada renovación devuelve uno
nuevo y el anterior deja de servir. Perder el nuevo obliga al dueño a volver a entrar,
así que renovar va bajo un candado de proceso y el resultado se guarda en memoria y en
la fila cifrada con su propia transacción, que no depende de que a la corrida que lo
pidió le vaya bien (ver `_persistir`).

NO VERIFICADO CON UNA CUENTA REAL. Todo esto se probó contra un servidor falso que sigue
la documentación; el comportamiento real del backend solo se conoce por lo que dicen los
documentos de OpenAI.

Dirección de imports (sin ciclos): provider.py y codex.py → chatgpt_auth.py → config.
"""

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import httpx

from aiuda_core.config import settings

logger = logging.getLogger(__name__)

# El nombre con el que aiuda se presenta. Es el suyo: no se cambia por el de nadie.
NOMBRE_APP = "aiuda"
# Punto de entrada del primer registro. NO es un client_id que se guarde ni se canjee.
CLIENTE_REGISTRO = "dynamic_agent_client"
# El recurso es parte del contrato (va en el token como `aud`), no la URL a la que se
# le pega: por eso es constante aunque `openai_base` apunte a otro lado en pruebas.
RECURSO = "https://api.openai.com/v1"
SCOPE_PLAN = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {SCOPE_PLAN}"
# Donde el dueño ve y limita lo que aiuda gasta de su plan.
USO_URL = "https://chatgpt.com/settings/usage"

# Se renueva cuando al token le quedan menos de cinco minutos.
MARGEN_S = 300
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Códigos con los que el servidor dice que el token de renovación ya no sirve y hay que
# volver a entrar. Cualquier otro fallo (red, 5xx) conserva la conexión.
_TERMINALES = frozenset({
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
})

VENCIDA = "Tu conexión con ChatGPT venció. Vuelve a entrar con ChatGPT en Tu IA."


class ChatGPTAuthError(Exception):
    """Fallo del flujo de ChatGPT. El mensaje es para el dueño; `code` para la consola."""

    def __init__(self, mensaje: str, code: str = "status"):
        super().__init__(mensaje)
        self.code = code


class SesionVencida(ChatGPTAuthError):
    """El token de renovación ya no sirve: toca volver a entrar."""

    def __init__(self, mensaje: str = VENCIDA):
        super().__init__(mensaje, "auth")


# --------------------------------------------------------------------------- #
# Inicio: PKCE y la URL que se abre en el navegador                            #
# --------------------------------------------------------------------------- #
def _b64(crudo: bytes) -> str:
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


def _unb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def nuevo_host_id() -> str:
    """Identificador opaco de ESTA instalación. Se genera una vez y se conserva."""
    return f"urn:uuid:{uuid.uuid4()}"


@dataclass(frozen=True)
class Intento:
    """Un intento de entrar: lo que hay que recordar hasta que regrese el navegador."""

    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    # None = primer registro (el client_id llega en el regreso).
    client_id: str | None
    url: str


def nuevo_intento(
    redirect_uri: str, *, host_id: str, client_id: str | None = None, email: str | None = None
) -> Intento:
    """Arma un intento con state, nonce y verificador frescos.

    Sin `client_id` es un registro nuevo: aiuda se presenta con su nombre. Con él es
    volver a entrar a la cuenta ya registrada, y el nombre ya no se manda. El ID token
    anterior NO se manda como pista (`id_token_hint`): no hace falta y así ningún
    token viaja en la barra de direcciones del navegador."""
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    params = {
        "client_id": client_id or CLIENTE_REGISTRO,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RECURSO,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
    }
    if client_id is None:
        params["agent_name_hint"] = NOMBRE_APP
    elif email:
        params["login_hint"] = email
    url = f"{settings.chatgpt_issuer}/api/accounts/authorize?{urlencode(params)}"
    return Intento(state, nonce, verifier, redirect_uri, client_id, url)


# --------------------------------------------------------------------------- #
# Canje, renovación y revocación                                               #
# --------------------------------------------------------------------------- #
def _codigo(cuerpo) -> str:
    """El código de error venga como venga: {"error": "x"}, {"error": {"code": "x"}}
    o {"code": "x"}."""
    if not isinstance(cuerpo, dict):
        return ""
    err = cuerpo.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("type") or "")
    return str(err or cuerpo.get("code") or "")


def _json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return None


def _pedir_token(datos: dict) -> tuple[int, dict]:
    """POST al endpoint de tokens. Devuelve (status, cuerpo); la red caída lanza."""
    try:
        resp = httpx.post(
            f"{settings.chatgpt_issuer}/api/accounts/oauth/token", data=datos, timeout=_TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise ChatGPTAuthError(
            "No se pudo hablar con ChatGPT (red o tiempo de espera).", "network"
        ) from exc
    cuerpo = _json(resp)
    return resp.status_code, cuerpo if isinstance(cuerpo, dict) else {}


def canjear(intento: Intento, code: str, client_id: str) -> dict:
    """Cambia el código del regreso por los tokens. Sin secreto: es un cliente público,
    lo que prueba que somos quien empezó el intento es el verificador de PKCE."""
    status, cuerpo = _pedir_token({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": intento.verifier,
        "redirect_uri": intento.redirect_uri,
        "resource": RECURSO,
    })
    if status != 200 or not cuerpo.get("access_token"):
        logger.warning("chatgpt: el canje respondió %s (%s)", status, _codigo(cuerpo))
        raise ChatGPTAuthError("ChatGPT no completó la entrada. Inténtalo otra vez.")
    return cuerpo


def _epoch(valor) -> int:
    """`earliest_refresh_at` no tiene formato documentado: se acepta número (segundos o
    milisegundos) o fecha ISO. Lo que no se entienda cuenta como 'sin restricción'."""
    if isinstance(valor, (int, float)) and valor > 0:
        return int(valor / 1000 if valor > 1e12 else valor)
    if isinstance(valor, str) and valor.strip():
        try:
            return _epoch(float(valor))
        except ValueError:
            pass
        try:
            return int(datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return 0


def armar_bundle(tok: dict, *, previo: dict) -> dict:
    """La credencial completa a partir de una respuesta de tokens. `previo` trae lo que
    esa respuesta no repite (client_id, cuenta, modelo, y en una renovación el ID token
    y los permisos). Todo se reemplaza junto: nunca medio token nuevo y medio viejo."""
    scope = tok.get("scope")
    return {
        **previo,
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or previo.get("refresh_token") or "",
        "id_token": tok.get("id_token") or previo.get("id_token") or "",
        "expires_at": int(time.time()) + int(tok.get("expires_in") or 3600),
        "earliest_refresh_at": _epoch(tok.get("earliest_refresh_at")),
        "scopes": scope.split() if isinstance(scope, str) else previo.get("scopes") or [],
        "guardado": time.time(),
    }


def renovar(bundle: dict) -> dict:
    """Pide un token nuevo con el de renovación. Devuelve el bundle de reemplazo.

    `SesionVencida` si el servidor dice que ese token ya no sirve; `ChatGPTAuthError`
    si el fallo es pasajero (la conexión se conserva)."""
    if not bundle.get("refresh_token"):
        raise SesionVencida()
    status, cuerpo = _pedir_token({
        "grant_type": "refresh_token",
        "client_id": bundle["client_id"],
        "refresh_token": bundle["refresh_token"],
        "resource": RECURSO,
    })
    if status == 200 and cuerpo.get("access_token"):
        return armar_bundle(cuerpo, previo=bundle)
    codigo = _codigo(cuerpo)
    logger.warning("chatgpt: la renovación respondió %s (%s)", status, codigo)
    if codigo in _TERMINALES:
        raise SesionVencida()
    raise ChatGPTAuthError(
        "No se pudo renovar tu conexión con ChatGPT. Se intenta de nuevo más tarde.", "network"
    )


def revocar(bundle: dict) -> bool:
    """Le avisa a OpenAI que esta sesión terminó. True solo si lo confirmó (200)."""
    if not bundle.get("refresh_token") or not bundle.get("client_id"):
        return False
    try:
        resp = httpx.post(
            f"{settings.chatgpt_issuer}/api/accounts/oauth/revoke",
            data={
                "token": bundle["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": bundle["client_id"],
            },
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError:
        return False
    return resp.status_code == 200


# --------------------------------------------------------------------------- #
# ID token: firma RS256 contra las llaves publicadas, sin dependencia nueva    #
# --------------------------------------------------------------------------- #
def verificar_id_token(id_token: str, *, client_id: str, nonce: str) -> dict:
    """Valida el ID token y devuelve sus datos. Revisa firma, emisor, destinatario
    (el client_id emitido), vigencia y el nonce de ESTE intento."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    malo = ChatGPTAuthError("ChatGPT devolvió una identidad que no se pudo comprobar.")
    try:
        cabeza_b64, datos_b64, firma_b64 = id_token.split(".")
        cabeza = json.loads(_unb64(cabeza_b64))
        datos = json.loads(_unb64(datos_b64))
        firma = _unb64(firma_b64)
    except (ValueError, AttributeError) as exc:
        raise malo from exc
    if cabeza.get("alg") != "RS256" or not cabeza.get("kid"):
        raise malo
    try:
        resp = httpx.get(f"{settings.chatgpt_issuer}/.well-known/jwks.json", timeout=_TIMEOUT)
        llaves = (resp.json() or {}).get("keys") or []
    except (httpx.HTTPError, ValueError) as exc:
        raise ChatGPTAuthError(
            "No se pudo hablar con ChatGPT (red o tiempo de espera).", "network"
        ) from exc
    jwk = next(
        (k for k in llaves if k.get("kid") == cabeza["kid"] and k.get("kty") == "RSA"), None
    )
    if jwk is None:
        raise malo
    try:
        publica = RSAPublicNumbers(
            int.from_bytes(_unb64(jwk["e"]), "big"), int.from_bytes(_unb64(jwk["n"]), "big")
        ).public_key()
        publica.verify(
            firma, f"{cabeza_b64}.{datos_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
    except (InvalidSignature, KeyError, ValueError) as exc:
        raise malo from exc

    aud = datos.get("aud")
    para_mi = client_id in aud if isinstance(aud, list) else aud == client_id
    exp = datos.get("exp")
    if (
        datos.get("iss") != settings.chatgpt_issuer
        or not para_mi
        or not isinstance(exp, (int, float))
        or exp < time.time()
        or not secrets.compare_digest(str(datos.get("nonce") or ""), nonce)
        or not datos.get("sub")
    ):
        raise malo
    return datos


# --------------------------------------------------------------------------- #
# Modelos y errores de la Responses API en esta vía                            #
# --------------------------------------------------------------------------- #
def mensaje_error(status: int, codigo: str = "") -> tuple[str, str]:
    """(code corto, mensaje para el dueño) de un rechazo de OpenAI en esta vía. OpenAI
    no cambia a otra forma de cobro por su cuenta, y aiuda tampoco: se dice y se para."""
    if codigo == "subscription_sharing_usage_limit_exceeded" or status == 429:
        return "limite", (
            "Llegaste al límite de uso de tu plan de ChatGPT o al que le pusiste a aiuda. "
            "Revísalo en Administrar uso."
        )
    if codigo == "subscription_sharing_user_not_eligible":
        return "no_elegible", (
            "Tu cuenta de ChatGPT no puede usar su plan en otras aplicaciones. "
            "Revisa tu plan en ChatGPT o conecta tu IA de otra forma."
        )
    if codigo == "subscription_sharing_unsupported_capability":
        return "no_soportado", (
            "ChatGPT rechazó esta petición porque usa algo que tu plan no admite fuera "
            "de ChatGPT."
        )
    if codigo in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable") or status == 503:
        return "no_disponible", (
            "ChatGPT no pudo revisar tu plan en este momento. Se intenta de nuevo más tarde."
        )
    if codigo == "subscription_sharing_invalid_user" or status == 401:
        return "auth", "ChatGPT no aceptó tu sesión. Vuelve a entrar con ChatGPT en Tu IA."
    if status == 403:
        return "permiso", (
            "ChatGPT no permitió usar tu plan desde aquí. Puede ser una restricción de "
            "tu cuenta o de tu región."
        )
    if status == 200:
        return "status", "ChatGPT no terminó la respuesta. Inténtalo otra vez."
    return "status", f"ChatGPT respondió {status}. Inténtalo en un momento."


def elegir_modelo(access_token: str) -> str:
    """El modelo que usará esta cuenta. Se le pregunta a OpenAI qué tiene disponible
    (cada cuenta ve los suyos) y se prefiere el de la configuración si aparece; si no,
    el primero de su lista, que viene en el orden que OpenAI recomienda."""
    try:
        resp = httpx.get(
            f"{settings.openai_base}/models",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ChatGPTAuthError(
            "No se pudo hablar con ChatGPT (red o tiempo de espera).", "network"
        ) from exc
    cuerpo = _json(resp)
    if resp.status_code != 200:
        code, mensaje = mensaje_error(resp.status_code, _codigo(cuerpo))
        raise ChatGPTAuthError(mensaje, code)
    modelos = (cuerpo or {}).get("models") if isinstance(cuerpo, dict) else None
    slugs = [
        m["slug"]
        for m in modelos or []
        if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"
    ]
    if not slugs:
        raise ChatGPTAuthError("Tu cuenta de ChatGPT no tiene ningún modelo disponible para aiuda.")
    return settings.model_codex if settings.model_codex in slugs else slugs[0]


# --------------------------------------------------------------------------- #
# La credencial guardada y su token vigente                                    #
# --------------------------------------------------------------------------- #
IA = "ia"

# Un candado para TODO el proceso: dos corridas no pueden renovar a la vez, porque la
# segunda mandaría un token de renovación que la primera ya gastó.
_candado = threading.Lock()
# El bundle más nuevo por workspace. La fila cifrada es la verdad entre reinicios; esto
# es la verdad dentro del proceso, para cuando otra sesión de base todavía ve la fila
# vieja o la transacción que guardaba el token nuevo se revirtió.
_ultimo: dict[str, dict] = {}


def parse_secret(secret: str) -> dict:
    """El bundle guardado (un JSON dentro del secreto cifrado). {} si no se entiende."""
    try:
        bundle = json.loads(secret or "")
    except ValueError:
        return {}
    return bundle if isinstance(bundle, dict) else {}


def valores(bundle: dict) -> dict:
    """Lo que se guarda en la fila 'ia': el bundle va entero dentro del secreto cifrado."""
    return {"name": "chatgpt", "mode": "oauth", "secret": json.dumps(bundle, separators=(",", ":"))}


def recordar(tenant_id: str, bundle: dict) -> None:
    """Al conectar: este bundle es el más nuevo que conoce el proceso."""
    _ultimo[tenant_id] = bundle


def olvidar(tenant_id: str) -> None:
    """Al desconectar: que nada en memoria reviva una credencial ya borrada."""
    with _candado:
        _ultimo.pop(tenant_id, None)


def soltar(session, tenant_id: str) -> dict:
    """Al desconectar o cambiar de IA: devuelve el bundle vigente (para revocarlo) y lo
    quita de la memoria. Toma el candado, así que espera a una renovación en curso y lo
    que devuelve ya es el token que esa renovación dejó. {} si la IA no era ChatGPT."""
    with _candado:
        try:
            return bundle_actual(session, tenant_id)
        finally:
            _ultimo.pop(tenant_id, None)


def _ya_escribe(session) -> bool:
    """¿La sesión de quien llama ya tiene abierta una transacción de escritura?"""
    try:
        return bool(session.connection().connection.dbapi_connection.in_transaction)
    except Exception:  # noqa: BLE001 — ante la duda, se trata como que no
        return False


def _guardar(session, tenant_id: str, bundle: dict) -> bool:
    """Escribe el bundle en la fila 'ia' SOLO si esa fila sigue siendo esta misma
    conexión de ChatGPT. Si mientras se renovaba el dueño guardó otra IA (o entró con
    otra cuenta), lo suyo manda: no se le escribe encima y el bundle se suelta."""
    from aiuda_core.connectors import credentials

    guardado = credentials.read_stored(session, tenant_id, IA) or {}
    if (
        guardado.get("name") != "chatgpt"
        or parse_secret(guardado.get("secret") or "").get("client_id") != bundle.get("client_id")
    ):
        _ultimo.pop(tenant_id, None)
        return False
    return credentials.refresh_secret(session, tenant_id, IA, valores(bundle))


def _escribir_aparte(bind, tenant_id: str) -> None:
    """Escribe el bundle de memoria en su fila con una transacción propia, confirmada
    en el acto. Si no logra entrar (otro está escribiendo), queda en memoria."""
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    bundle = _ultimo.get(tenant_id)
    if bundle is None:
        return
    try:
        with Session(bind=bind) as aparte:
            _guardar(aparte, tenant_id, bundle)
            aparte.commit()
    except OperationalError:
        logger.warning("chatgpt: no se pudo guardar el token renovado; queda en memoria")


def _persistir(session, tenant_id: str, bundle: dict) -> None:
    """Deja el bundle como el más nuevo en memoria y lo escribe cifrado en su fila.

    La escritura NO puede depender de que a la corrida le vaya bien: si se revirtiera
    junto con ella (por ejemplo, porque el plan llegó a su límite justo después de
    renovar), el token recién rotado se perdería y el viejo ya no sirve. Por eso va en
    una transacción aparte. La excepción es cuando quien llama ya está escribiendo:
    SQLite admite un solo escritor, así que ahí se escribe con su misma sesión y, si
    esa transacción se revierte, se repone aparte en cuanto suelta la base."""
    from sqlalchemy import event

    _ultimo[tenant_id] = bundle
    if not _ya_escribe(session):
        _escribir_aparte(session.get_bind(), tenant_id)
        return
    if not _guardar(session, tenant_id, bundle):
        return
    event.listen(
        session,
        "after_rollback",
        lambda s: _escribir_aparte(s.get_bind(), tenant_id),
        once=True,
    )


def bundle_actual(session, tenant_id: str) -> dict:
    """El bundle vigente: el de la fila, o el de memoria si es más nuevo (y entonces se
    vuelve a escribir en la fila). {} si la conexión ya no es de ChatGPT."""
    from aiuda_core.connectors import credentials

    guardado = credentials.read_stored(session, tenant_id, IA) or {}
    if guardado.get("name") != "chatgpt":
        return {}
    bundle = parse_secret(guardado.get("secret") or "")
    memoria = _ultimo.get(tenant_id)
    if (
        memoria
        and memoria.get("client_id") == bundle.get("client_id")
        and memoria.get("guardado", 0) > bundle.get("guardado", 0)
    ):
        _persistir(session, tenant_id, memoria)
        return memoria
    return bundle


def token_vigente(session, tenant_id: str, *, rechazado: str | None = None) -> str:
    """El access token para la siguiente llamada, renovándolo si hace falta.

    Sin `rechazado`: renueva si está por vencer. Con `rechazado` (el token al que OpenAI
    acaba de contestar 401): renueva aunque el reloj diga que seguía vigente, salvo que
    otro hilo ya lo haya hecho, en cuyo caso se usa el de ese hilo.

    Si la renovación es rechazada de forma definitiva se borran los tokens, se conserva
    el registro de la app (client_id y cuenta) y se pide volver a entrar."""
    with _candado:
        bundle = bundle_actual(session, tenant_id)
        if not bundle.get("access_token"):
            raise SesionVencida()
        ahora = time.time()
        if rechazado is not None:
            toca = bundle["access_token"] == rechazado
        else:
            toca = (
                bundle.get("expires_at", 0) - ahora < MARGEN_S
                and ahora >= bundle.get("earliest_refresh_at", 0)
            )
        if not toca:
            return bundle["access_token"]
        try:
            nuevo = renovar(bundle)
        except SesionVencida:
            vacio = {
                **bundle,
                "access_token": "",
                "refresh_token": "",
                "id_token": "",
                "guardado": time.time(),
            }
            _persistir(session, tenant_id, vacio)
            raise
        except ChatGPTAuthError:
            # Fallo pasajero. Si el token todavía sirve, se usa; la conexión no se toca.
            if rechazado is None and bundle.get("expires_at", 0) > ahora:
                return bundle["access_token"]
            raise
        _persistir(session, tenant_id, nuevo)
        return nuevo["access_token"]
