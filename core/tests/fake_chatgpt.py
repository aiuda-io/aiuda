"""Servidor FALSO de "Entrar con ChatGPT" para pruebas. No es parte de la app.

Sigue lo que dice la documentación pública de OpenAI (developers.openai.com/siwc), con
las mismas rutas que el emisor real, para poder ejercitar el flujo completo sin una
cuenta: registro, canje con PKCE, ID token firmado en RS256, renovación con token que
rota, revocación, lista de modelos y la Responses API por SSE.

Que algo pase contra este servidor prueba que aiuda sigue la documentación. NO prueba
que el backend real se comporte igual: eso solo lo dice un login de verdad.

Uso en pruebas:  with FakeChatGPT() as falso: ...  (falso.base, falso.modo, falso.visto)
A mano:          python core/tests/fake_chatgpt.py --port 4801
                 curl -X POST localhost:4801/_control -d '{"responses": "limite"}'
"""

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

RECURSO = "https://api.openai.com/v1"
SCOPES = "chatgpt.tokens.use.direct email offline_access openid profile resource.invoke"


def _b64(crudo: bytes) -> str:
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


class FakeChatGPT:
    """Emisor + API en un puerto local. `modo` cambia cómo contesta; `visto` guarda lo
    que recibió para que la prueba lo revise."""

    def __init__(self, port: int = 0):
        self._llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "falsa-1"
        self.modo = {
            "authorize": "ok",  # ok | denegar | sin_plan | sin_client_id | otro_client_id
            "token": "ok",  # ok | caido
            "refresh": "ok",  # ok | caido | (cualquier código terminal, p. ej. invalid_grant)
            "revoke": "ok",  # ok | caido
            "responses": "ok",  # ok | detail_403 | limite | no_elegible | cortado | 401
            "expires_in": 3600,
            "sub": "user-falso-1",
            "email": "dueno@ejemplo.mx",
            "modelos": ["gpt-falso-grande", "gpt-falso-chico"],
            "nonce": None,  # None = el que mandó el cliente
            "aud": None,  # None = el client_id emitido
            "firma_mala": False,
        }
        self.visto: dict = {
            "authorize": [], "token": [], "revoke": [], "responses": [], "models": 0,
        }
        self._codigos: dict[str, dict] = {}
        self._access: dict[str, float] = {}  # token -> vence
        self._refresh: dict[str, str] = {}  # token vigente -> client_id
        self._gastados: set[str] = set()
        self._candado = threading.Lock()
        self._http = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self._http.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    # -- ciclo de vida -------------------------------------------------------
    def __enter__(self):
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self._http.shutdown()
        self._http.server_close()
        return False

    # -- utilidades para las pruebas ----------------------------------------
    def vencer_access_tokens(self) -> None:
        """Como si OpenAI invalidara los tokens antes de tiempo: el siguiente uso da 401."""
        with self._candado:
            self._access = {t: 0.0 for t in self._access}

    def jwt(self, datos: dict) -> str:
        cabeza = _b64(json.dumps({"alg": "RS256", "kid": self.kid, "typ": "JWT"}).encode())
        cuerpo = _b64(json.dumps(datos).encode())
        firma = self._llave.sign(f"{cabeza}.{cuerpo}".encode(), padding.PKCS1v15(), hashes.SHA256())
        if self.modo["firma_mala"]:
            firma = firma[:-1] + bytes([firma[-1] ^ 1])
        return f"{cabeza}.{cuerpo}.{_b64(firma)}"

    def _jwks(self) -> dict:
        n = self._llave.public_key().public_numbers()
        return {
            "keys": [{
                "kty": "RSA", "kid": self.kid, "alg": "RS256", "use": "sig",
                "n": _b64(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
                "e": _b64(n.e.to_bytes(3, "big")),
            }]
        }

    def _emitir(self, client_id: str, nonce: str | None) -> dict:
        access, refresh = "at_" + secrets.token_urlsafe(16), "rt_" + secrets.token_urlsafe(16)
        self._access[access] = time.time() + self.modo["expires_in"]
        self._refresh[refresh] = client_id
        ahora = int(time.time())
        out = {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": self.modo["expires_in"],
            "scope": SCOPES if self.modo["authorize"] != "sin_plan" else "email openid profile",
            "earliest_refresh_at": ahora,
        }
        if nonce is not None:
            out["id_token"] = self.jwt({
                "iss": self.base,
                "aud": self.modo["aud"] or client_id,
                "sub": self.modo["sub"],
                "email": self.modo["email"],
                "nonce": self.modo["nonce"] or nonce,
                "iat": ahora,
                "exp": ahora + 3600,
            })
        return out

    # -- HTTP ----------------------------------------------------------------
    def _handler(self):
        falso = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencio en la salida de pytest
                pass

            def _json(self, status: int, cuerpo: dict | None = None):
                datos = json.dumps(cuerpo).encode() if cuerpo is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def _cuerpo(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _bearer_valido(self) -> bool:
                token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                return falso._access.get(token, 0) > time.time()

            def do_GET(self):
                url = urlsplit(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == "/.well-known/jwks.json":
                    return self._json(200, falso._jwks())
                if url.path == "/_visto":
                    return self._json(200, falso.visto)
                if url.path == "/v1/models":
                    falso.visto["models"] += 1
                    if not self._bearer_valido():
                        return self._json(401, {"error": {"code": "invalid_token"}})
                    return self._json(200, {
                        "models": [
                            {"slug": "interno-oculto", "display_name": "x", "visibility": "hide"},
                            *(
                                {"slug": s, "display_name": s, "visibility": "list"}
                                for s in falso.modo["modelos"]
                            ),
                        ]
                    })
                if url.path == "/api/accounts/authorize":
                    return self._authorize(q)
                self._json(404, {"detail": "no existe"})

            def _authorize(self, q: dict):
                falso.visto["authorize"].append(q)
                registro = q.get("client_id") == "dynamic_agent_client"
                malo = (
                    q.get("response_type") != "code"
                    or q.get("code_challenge_method") != "S256"
                    or not q.get("code_challenge")
                    or not q.get("state")
                    or not q.get("nonce")
                    or q.get("resource") != RECURSO
                    or not (q.get("ext_agent_host_id") or "").startswith("urn:uuid:")
                    or not (q.get("redirect_uri") or "").startswith("http://127.0.0.1:")
                    or not (q.get("redirect_uri") or "").endswith("/auth/callback")
                    or "chatgpt.tokens.use.direct" not in (q.get("scope") or "")
                    # El nombre va solo en el registro; al volver a entrar se omite.
                    or registro != bool(q.get("agent_name_hint"))
                )
                if malo:
                    return self._json(400, {"error": "invalid_request"})
                modo = falso.modo["authorize"]
                if modo == "denegar":
                    vuelta = {"error": "access_denied", "state": q["state"]}
                else:
                    client_id = "oaiapp_falso_" + secrets.token_hex(4) if registro else q["client_id"]
                    code = secrets.token_urlsafe(16)
                    falso._codigos[code] = {**q, "client_id": client_id}
                    vuelta = {"code": code, "state": q["state"], "scope": SCOPES}
                    if modo == "otro_client_id":
                        vuelta["client_id"] = "oaiapp_de_otro"
                    elif modo != "sin_client_id" and registro:
                        vuelta["client_id"] = client_id
                self.send_response(302)
                self.send_header("Location", f"{q['redirect_uri']}?{urlencode(vuelta)}")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                ruta = urlsplit(self.path).path
                crudo = self._cuerpo()
                if ruta == "/_control":
                    falso.modo.update(json.loads(crudo or b"{}"))
                    return self._json(200, falso.modo)
                if ruta == "/_vencer":
                    falso.vencer_access_tokens()
                    return self._json(200, {})
                if ruta == "/v1/responses":
                    return self._responses(crudo)
                form = {k: v[0] for k, v in parse_qs(crudo.decode()).items()}
                if ruta == "/api/accounts/oauth/token":
                    return self._token(form)
                if ruta == "/api/accounts/oauth/revoke":
                    falso.visto["revoke"].append(form)
                    if falso.modo["revoke"] == "caido":
                        return self._json(503, {"error": "server_error"})
                    with falso._candado:
                        falso._refresh.pop(form.get("token", ""), None)
                    return self._json(200)
                self._json(404, {"detail": "no existe"})

            def _token(self, form: dict):
                falso.visto["token"].append(form)
                if form.get("resource") != RECURSO or "client_secret" in form:
                    return self._json(400, {"error": "invalid_request"})
                with falso._candado:
                    if form.get("grant_type") == "authorization_code":
                        if falso.modo["token"] == "caido":
                            return self._json(503, {"error": "server_error"})
                        pend = falso._codigos.pop(form.get("code", ""), None)  # un solo uso
                        reto = _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                        if (
                            pend is None
                            or reto != pend["code_challenge"]
                            or form.get("redirect_uri") != pend["redirect_uri"]
                            or form.get("client_id") != pend["client_id"]
                        ):
                            return self._json(400, {"error": "invalid_grant"})
                        return self._json(200, falso._emitir(pend["client_id"], pend["nonce"]))
                    if form.get("grant_type") == "refresh_token":
                        modo = falso.modo["refresh"]
                        if modo == "caido":
                            return self._json(503, {"error": "server_error"})
                        if modo != "ok":
                            return self._json(400, {"error": {"code": modo, "message": "x"}})
                        token = form.get("refresh_token", "")
                        if "scope" in form:
                            return self._json(400, {"error": "invalid_request"})
                        if token in falso._gastados:
                            return self._json(400, {"error": {"code": "refresh_token_reused"}})
                        if falso._refresh.get(token) != form.get("client_id"):
                            return self._json(400, {"error": "invalid_grant"})
                        del falso._refresh[token]
                        falso._gastados.add(token)
                        return self._json(200, falso._emitir(form["client_id"], None))
                self._json(400, {"error": "unsupported_grant_type"})

            def _responses(self, crudo: bytes):
                body = json.loads(crudo or b"{}")
                falso.visto["responses"].append({
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                modo = falso.modo["responses"]
                if modo == "401" or not self._bearer_valido():
                    return self._json(401, {"error": {"code": "invalid_token", "message": "x"}})
                if modo == "detail_403":
                    return self._json(403, {"detail": "Serving region not permitted"})
                if modo == "no_elegible":
                    return self._json(403, {"error": {
                        "code": "subscription_sharing_user_not_eligible", "message": "x",
                    }})
                prohibidos = {"max_output_tokens", "temperature", "top_p", "metadata", "user",
                              "truncation", "previous_response_id"} & set(body)
                if (
                    body.get("store") is not False
                    or body.get("stream") is not True
                    or not isinstance(body.get("input"), list)
                    or prohibidos
                    or body.get("model") not in falso.modo["modelos"]
                ):
                    return self._json(400, {"error": {
                        "code": "subscription_sharing_unsupported_capability",
                        "param": next(iter(prohibidos), "body"),
                    }})
                eventos: list[dict] = [{"type": "response.output_text.delta", "delta": "Hola "}]
                if modo == "limite":
                    eventos.append({"type": "response.failed", "response": {"error": {
                        "code": "subscription_sharing_usage_limit_exceeded", "message": "x",
                    }}})
                elif modo != "cortado":
                    eventos += [
                        {"type": "response.output_text.delta", "delta": "desde el plan"},
                        {"type": "response.completed", "response": {
                            "usage": {"input_tokens": 11, "output_tokens": 4},
                        }},
                    ]
                datos = "".join(f"data: {json.dumps(e)}\n\n" for e in eventos).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Servidor falso de Entrar con ChatGPT (pruebas).")
    ap.add_argument("--port", type=int, default=4801)
    args = ap.parse_args()
    with FakeChatGPT(args.port) as f:
        print(f"falso en {f.base}", flush=True)
        threading.Event().wait()
