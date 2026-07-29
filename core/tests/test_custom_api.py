"""Conector genérico por API: traer + mapear (sin red, urlopen mockeado)."""

import io
import json
import urllib.error
from contextlib import contextmanager

from aiuda_core.connectors import custom_api


def _fake_urlopen(payload, status=200):
    """Devuelve un contextmanager tipo urlopen que entrega `payload` como JSON."""

    @contextmanager
    def opener(req, timeout=15):
        yield io.BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


class _Servidor:
    """urlopen falso con guion: registra cada request y responde en orden.

    Cada respuesta del guion es un payload JSON o una excepción (se lanza). Permite
    probar paginación, reintentos y el flujo OAuth2 sin red."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.requests = []  # (url, headers, data)

    @contextmanager
    def __call__(self, req, timeout=15):
        self.requests.append((req.full_url, dict(req.headers), req.data))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        yield io.BytesIO(json.dumps(r).encode("utf-8"))


def _http_error(code, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("https://x.com", code, "err", headers, io.BytesIO(b""))


def test_dig_navega_con_puntos():
    obj = {"a": {"b": {"c": 7}}}
    assert custom_api.dig(obj, "a.b.c") == 7
    assert custom_api.dig(obj, "a.b") == {"c": 7}
    assert custom_api.dig(obj, "") == obj
    assert custom_api.dig(obj, "a.x.y") is None


def test_fetch_mapea_cada_registro(monkeypatch):
    payload = {"data": [{"nombre": "ACME", "tel": {"movil": "5512345678"}}, {"nombre": "Beta", "tel": {"movil": "5599"}}]}
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", _fake_urlopen(payload))
    rows, err = custom_api.fetch_rows(
        base_url="https://mi.api.com",
        list_path="clientes",
        root="data",
        mapping={"name": "nombre", "phone": "tel.movil"},
    )
    assert err is None
    assert rows == [
        {"name": "ACME", "phone": "5512345678"},
        {"name": "Beta", "phone": "5599"},
    ]


def test_root_vacio_cuerpo_es_arreglo(monkeypatch):
    payload = [{"n": "uno"}, {"n": "dos"}]
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", _fake_urlopen(payload))
    rows, err = custom_api.fetch_rows(base_url="https://x.com", mapping={"name": "n"})
    assert err is None and rows == [{"name": "uno"}, {"name": "dos"}]


def test_root_que_no_es_lista_da_error_legible(monkeypatch):
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", _fake_urlopen({"data": {"no": "lista"}}))
    rows, err = custom_api.fetch_rows(base_url="https://x.com", root="data", mapping={"name": "n"})
    assert rows == [] and "arreglo" in err


def test_url_no_http_se_rechaza():
    rows, err = custom_api.fetch_rows(base_url="ftp://x.com", mapping={})
    assert rows == [] and "http" in err.lower()


def _headers_bajos(req_headers: dict) -> dict:
    """urllib capitaliza los headers; comparamos en minúsculas."""
    return {k.lower(): v for k, v in req_headers.items()}


# ---------------------------------------------------------------------------
# Tipos de auth
# ---------------------------------------------------------------------------


def test_auth_bearer_manda_authorization(monkeypatch):
    srv = _Servidor([[{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", auth_type="bearer", auth_value="tok-123", mapping={"name": "n"}
    )
    assert err is None and rows == [{"name": "uno"}]
    assert _headers_bajos(srv.requests[0][1])["authorization"] == "Bearer tok-123"


def test_auth_query_param_va_en_la_url(monkeypatch):
    srv = _Servidor([[{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    _, err = custom_api.fetch_rows(
        base_url="https://x.com/api?v=2",
        auth_type="query",
        auth_header="api_key",
        auth_value="k-9",
        mapping={"name": "n"},
    )
    assert err is None
    url = srv.requests[0][0]
    assert "api_key=k-9" in url and "v=2" in url  # respeta los params que ya traía
    assert "authorization" not in _headers_bajos(srv.requests[0][1])


def test_auth_basic_codifica_usuario_contrasena(monkeypatch):
    import base64 as b64

    srv = _Servidor([[{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    _, err = custom_api.fetch_rows(
        base_url="https://x.com", auth_type="basic", auth_value="ana:secreta", mapping={"name": "n"}
    )
    assert err is None
    esperado = "Basic " + b64.b64encode(b"ana:secreta").decode()
    assert _headers_bajos(srv.requests[0][1])["authorization"] == esperado


def test_auth_oauth2_cc_cambia_credenciales_por_token(monkeypatch):
    srv = _Servidor([{"access_token": "tok-oauth", "expires_in": 3600}, [{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com/api",
        auth_type="oauth2_cc",
        auth_value="client-secret",
        token_url="https://x.com/oauth/token",
        client_id="mi-app",
        mapping={"name": "n"},
    )
    assert err is None and rows == [{"name": "uno"}]
    # 1a petición: POST al token endpoint con grant_type y credenciales.
    url, _, data = srv.requests[0]
    assert url == "https://x.com/oauth/token"
    body = data.decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=mi-app" in body and "client-secret" in body
    # 2a: el GET de datos con el token que devolvió.
    assert _headers_bajos(srv.requests[1][1])["authorization"] == "Bearer tok-oauth"


def test_auth_oauth2_sin_token_da_error_legible(monkeypatch):
    srv = _Servidor([{"error": "invalid_client"}])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com",
        auth_type="oauth2_cc",
        auth_value="s",
        token_url="https://x.com/token",
        mapping={},
    )
    assert rows == [] and "access_token" in err


def test_auth_header_sin_nombre_da_error_legible():
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", auth_type="header", auth_value="clave", mapping={}
    )
    assert rows == [] and "header" in err.lower()


def test_sin_clave_no_manda_auth(monkeypatch):
    """Una receta importada sin clave aún: se intenta sin auth (API pública u honesto 401)."""
    srv = _Servidor([[{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    _, err = custom_api.fetch_rows(
        base_url="https://x.com", auth_type="bearer", auth_value="", mapping={"name": "n"}
    )
    assert err is None
    assert "authorization" not in _headers_bajos(srv.requests[0][1])


# ---------------------------------------------------------------------------
# Paginación, reintentos, rate-limit
# ---------------------------------------------------------------------------


def test_paginacion_offset_junta_paginas(monkeypatch):
    pagina1 = [{"n": f"c{i}"} for i in range(3)]
    pagina2 = [{"n": "c3"}]  # página corta: aquí se detiene
    srv = _Servidor([pagina1, pagina2])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com",
        mapping={"name": "n"},
        paging="offset",
        page_size=3,
        limit=0,
    )
    assert err is None and len(rows) == 4
    assert "offset=0" in srv.requests[0][0] and "limit=3" in srv.requests[0][0]
    assert "offset=3" in srv.requests[1][0]


def test_paginacion_cursor_sigue_el_cursor(monkeypatch):
    srv = _Servidor(
        [
            {"items": [{"n": "a"}], "next": "abc"},
            {"items": [{"n": "b"}], "next": None},
        ]
    )
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com",
        root="items",
        mapping={"name": "n"},
        paging="cursor",
        cursor_path="next",
        cursor_param="after",
        size_param="",
        limit=0,
    )
    assert err is None and [r["name"] for r in rows] == ["a", "b"]
    assert "after" not in srv.requests[0][0]
    assert "after=abc" in srv.requests[1][0]


def test_limit_corta_aunque_haya_mas_paginas(monkeypatch):
    srv = _Servidor([[{"n": f"c{i}"} for i in range(5)]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", mapping={"name": "n"}, paging="offset", page_size=5, limit=2
    )
    assert err is None and len(rows) == 2
    assert len(srv.requests) == 1  # con el tope alcanzado ya no pide más


def test_reintenta_en_500_y_recupera(monkeypatch):
    esperas = []
    srv = _Servidor([_http_error(500), [{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", mapping={"name": "n"}, retries=2, _sleep=esperas.append
    )
    assert err is None and rows == [{"name": "uno"}]
    assert len(esperas) == 1  # una espera entre el fallo y el reintento


def test_429_respeta_retry_after(monkeypatch):
    esperas = []
    srv = _Servidor([_http_error(429, retry_after=7), [{"n": "uno"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", mapping={"name": "n"}, retries=1, _sleep=esperas.append
    )
    assert err is None and rows == [{"name": "uno"}]
    assert esperas == [7]  # esperó lo que el servidor pidió


def test_reintentos_agotados_devuelve_error(monkeypatch):
    srv = _Servidor([_http_error(503), _http_error(503)])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com", mapping={}, retries=1, _sleep=lambda s: None
    )
    assert rows == [] and "503" in err and "reintentos" in err


def test_401_no_se_reintenta(monkeypatch):
    srv = _Servidor([_http_error(401)])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(base_url="https://x.com", mapping={}, retries=3)
    assert rows == [] and "401" in err
    assert len(srv.requests) == 1  # un auth malo no se arregla reintentando


def test_lectura_parcial_reporta_pagina_que_fallo(monkeypatch):
    srv = _Servidor([[{"n": f"c{i}"} for i in range(3)], _http_error(500)])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    rows, err = custom_api.fetch_rows(
        base_url="https://x.com",
        mapping={"name": "n"},
        paging="offset",
        page_size=3,
        limit=0,
        retries=0,
    )
    assert len(rows) == 3  # lo que sí llegó se conserva
    assert "parcial" in err and "página 2" in err


def test_pausa_entre_paginas(monkeypatch):
    esperas = []
    srv = _Servidor([[{"n": "a"}, {"n": "b"}], [{"n": "c"}]])
    monkeypatch.setattr(custom_api.urllib.request, "urlopen", srv)
    _, err = custom_api.fetch_rows(
        base_url="https://x.com",
        mapping={"name": "n"},
        paging="offset",
        page_size=2,
        pause_ms=250,
        limit=0,
        _sleep=esperas.append,
    )
    assert err is None and esperas == [0.25]


def test_config_basura_cae_a_defaults():
    assert custom_api._clamp("no-numero", 1, 60, 15) == 15
    assert custom_api._clamp(9999, 1, 60, 15) == 60
    assert custom_api._clamp(-3, 0, 5, 2) == 0


def test_kwargs_from_source_traduce_entrada_guardada():
    src = {
        "base_url": "https://mi.api.com",
        "list_path": "clientes",
        "auth_type": "query",
        "auth_header": "api_key",
        "paging": "offset",
        "page_size": 50,
        "timeout": 30,
        "retries": 0,
    }
    kw = custom_api.kwargs_from_source(src, secret="s3cr3t", limit=0)
    assert kw["auth_value"] == "s3cr3t" and kw["auth_type"] == "query"
    assert kw["page_size"] == 50 and kw["timeout"] == 30 and kw["retries"] == 0
    assert kw["limit"] == 0 and kw["mapping"] == {}
