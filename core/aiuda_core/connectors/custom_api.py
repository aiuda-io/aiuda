"""Conector genérico por API REST — el fallback abierto.

Cuando aiuda no trae un conector nativo para tu sistema, tú declaras la conexión: URL, auth y
qué campo del JSON es el nombre / teléfono / monto. aiuda la lee como cualquier otra fuente. La
lógica pura (traer y mapear) vive aquí, sin efectos secundarios; el cifrado del secreto y los
endpoints viven en la capa cloud. Fiel al open-core: una "receta" declarativa que se comparte.

Lectura (fetch_rows) y, si la receta declara `write_path`, ESCRITURA (escribir_registro):
aiuda no es el sistema maestro — lo capturado aquí se puede inyectar de regreso a TU API.
Deliberadamente simple (JSON, mapeo por path con puntos). Soporta lo que una API real exige
sin volverse un framework: auth (header, bearer, query param, basic, OAuth2
client-credentials), paginación (offset o cursor), reintentos con espera (respeta Retry-After
en 429) y timeout configurable, todo con topes duros. Los WRITES van a UN intento (un timeout
ambiguo pudo haber creado el registro allá; reintentar duplicaría). Si tu API no encaja en
esto, el siguiente escalón es el CUA (aiuda opera tu portal). Solo http/https.
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

# Topes duros de seguridad: el usuario configura, aiuda acota. Ninguna conexión a la
# medida puede colgar una corrida ni martillar una API ajena.
MAX_TIMEOUT = 60
MAX_RETRIES = 5
MAX_PAGE_SIZE = 500
MAX_PAGES = 50
MAX_PAUSE_MS = 5000
MAX_ROWS = 5000

AUTH_TYPES = ("", "header", "bearer", "query", "basic", "oauth2_cc")
PAGING_TYPES = ("", "offset", "cursor")


def dig(obj, path: str):
    """Navega un JSON por un path con puntos: dig(o, 'data.items') o dig(item, 'customer.name').
    path vacío devuelve el objeto tal cual. Cualquier tramo ausente devuelve None."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _clamp(value, lo: int, hi: int, default: int) -> int:
    """Entero acotado; cualquier basura cae al default (nunca truena por config mala)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _with_params(url: str, params: dict) -> str:
    """Agrega query params respetando los que la URL ya trae."""
    if not params:
        return url
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    pairs += [(k, str(v)) for k, v in params.items()]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(pairs)))


def _http_json(
    url: str,
    headers: dict,
    timeout: int,
    retries: int,
    data: bytes | None = None,
    _sleep=time.sleep,
) -> tuple[object, str | None]:
    """GET (o POST si hay data) con reintentos: red caída y 5xx reintentan con espera
    creciente; 429 respeta Retry-After (acotado). Devuelve (json, error legible)."""
    last_err = "No se pudo conectar."
    for intento in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (http/https ya validado)
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                last_err = f"El servidor respondió {e.code} ({e.reason})."
                if intento < retries:
                    espera = _clamp((e.headers or {}).get("Retry-After"), 0, 30, 0) if e.code == 429 else 0
                    _sleep(espera or min(2**intento, 8))
                    continue
                return None, f"{last_err} Se agotaron los reintentos."
            return None, f"El servidor respondió {e.code} ({e.reason}). Revisa la URL o el auth."
        except Exception as e:  # noqa: BLE001 — cualquier fallo de red es un error legible, no una excepción
            last_err = f"No se pudo conectar: {e}"
            if intento < retries:
                _sleep(min(2**intento, 8))
                continue
            return None, last_err
        try:
            return json.loads(raw), None
        except Exception:
            return None, "La respuesta no es JSON válido."
    return None, last_err


def _oauth2_token(
    token_url: str, client_id: str, client_secret: str, timeout: int, _sleep=time.sleep
) -> tuple[str, str | None]:
    """OAuth2 client-credentials: cambia client_id + client_secret por un access_token
    (POST form-encoded, el flujo estándar de APIs de servidor a servidor)."""
    if not str(token_url or "").lower().startswith(("http://", "https://")):
        return "", "La URL del token OAuth2 debe empezar con http:// o https://."
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id or "",
            "client_secret": client_secret or "",
        }
    ).encode()
    data, err = _http_json(
        token_url,
        {"Content-Type": "application/x-www-form-urlencoded"},
        timeout,
        retries=0,
        data=body,
        _sleep=_sleep,
    )
    if err:
        return "", f"OAuth2: {err}"
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        return "", "El servidor OAuth2 no devolvió access_token. Revisa token_url y credenciales."
    return str(token), None


def _resolver_auth(
    auth_type: str,
    auth_header: str,
    auth_value: str,
    token_url: str,
    client_id: str,
    timeout: int,
    _sleep=time.sleep,
) -> tuple[dict, dict, str | None]:
    """Traduce el auth declarado a (headers, query_params, error). Sin clave = sin auth
    (APIs públicas, o una receta importada a la que aún no le capturas la clave)."""
    if not auth_value:
        return {}, {}, None
    at = (auth_type or ("header" if auth_header else "")).strip()
    if at == "":
        return {}, {}, None
    if at == "header":
        if not auth_header:
            return {}, {}, "Ponle nombre al header de auth (p.ej. X-API-Key)."
        return {auth_header: auth_value}, {}, None
    if at == "bearer":
        return {"Authorization": f"Bearer {auth_value}"}, {}, None
    if at == "query":
        if not auth_header:
            return {}, {}, "Ponle nombre al parámetro de auth (p.ej. api_key)."
        return {}, {auth_header: auth_value}, None
    if at == "basic":
        # La clave es "usuario:contraseña" (el par que Basic codifica en base64).
        tok = base64.b64encode(auth_value.encode("utf-8")).decode()
        return {"Authorization": f"Basic {tok}"}, {}, None
    if at == "oauth2_cc":
        token, err = _oauth2_token(token_url, client_id, auth_value, timeout, _sleep=_sleep)
        if err:
            return {}, {}, err
        return {"Authorization": f"Bearer {token}"}, {}, None
    return {}, {}, f"Tipo de auth desconocido: {at}."


def fetch_rows(
    base_url: str,
    list_path: str = "",
    root: str = "",
    auth_header: str = "",
    auth_value: str = "",
    mapping: dict | None = None,
    timeout: int = 15,
    limit: int = 5,
    auth_type: str = "",
    token_url: str = "",
    client_id: str = "",
    paging: str = "",
    page_param: str = "offset",
    size_param: str = "limit",
    page_size: int = 100,
    cursor_param: str = "cursor",
    cursor_path: str = "",
    retries: int = 2,
    pause_ms: int = 0,
    _sleep=time.sleep,
) -> tuple[list[dict], str | None]:
    """GET a base_url(+list_path) con el auth declarado; mapea cada registro.

    - root: path (con puntos) al ARREGLO de registros dentro del JSON (p.ej. 'data' o
      'result.items'). Vacío = el cuerpo ya es el arreglo.
    - mapping: {campo_aiuda: path_en_el_registro}. Cada fila se reduce a esos campos.
    - limit: tope de filas; 0 = todas (acotado por MAX_ROWS/MAX_PAGES).
    - paging: '' una sola petición; 'offset' manda page_param/size_param y avanza hasta
      la página corta; 'cursor' sigue cursor_path de la respuesta vía cursor_param.
    - pause_ms: espera entre páginas (para no martillar APIs con rate-limit).

    Devuelve (filas_mapeadas, error). El error es un string legible (nunca explota). Si
    una página intermedia falla, devuelve lo ya leído + el error (lectura parcial honesta).
    """
    mapping = mapping or {}
    base = (base_url or "").strip()
    if not base.lower().startswith(("http://", "https://")):
        return [], "La URL debe empezar con http:// o https://."
    url = base.rstrip("/")
    if list_path:
        url = f"{url}/{list_path.strip().lstrip('/')}"

    timeout = _clamp(timeout, 1, MAX_TIMEOUT, 15)
    retries = _clamp(retries, 0, MAX_RETRIES, 2)
    page_size = _clamp(page_size, 1, MAX_PAGE_SIZE, 100)
    pause_ms = _clamp(pause_ms, 0, MAX_PAUSE_MS, 0)
    tope = _clamp(limit, 1, MAX_ROWS, MAX_ROWS) if limit else MAX_ROWS

    headers, auth_params, err = _resolver_auth(
        auth_type, auth_header, auth_value, token_url, client_id, timeout, _sleep=_sleep
    )
    if err:
        return [], err

    rows: list[dict] = []
    recibidos = 0  # registros crudos leídos (el offset real, aun si tope corta el mapeo)
    cursor = None
    for page in range(MAX_PAGES):
        params = dict(auth_params)
        if paging == "offset":
            params[page_param or "offset"] = recibidos
            if size_param:
                params[size_param] = page_size
        elif paging == "cursor":
            if size_param:
                params[size_param] = page_size
            if page > 0:
                params[cursor_param or "cursor"] = cursor

        data, err = _http_json(_with_params(url, params), headers, timeout, retries, _sleep=_sleep)
        if err:
            if rows:
                return rows, f"Lectura parcial (falló la página {page + 1}): {err}"
            return [], err

        arr = dig(data, root)
        if not isinstance(arr, list):
            pista = " (déjalo vacío si el cuerpo ya es la lista)" if root else ""
            return rows, f"No encontré un arreglo de registros en la ruta '{root}'{pista}."

        for item in arr:
            if len(rows) >= tope:
                break
            rows.append({campo: dig(item, path) for campo, path in mapping.items()})
        recibidos += len(arr)

        if len(rows) >= tope:
            break
        if paging == "offset":
            if len(arr) < page_size:
                break  # página corta = ya no hay más
        elif paging == "cursor":
            cursor = dig(data, cursor_path) if cursor_path else None
            if not cursor:
                break
        else:
            break  # sin paginación: una sola petición
        if pause_ms:
            _sleep(pause_ms / 1000)
    return rows, None


def kwargs_from_source(src: dict, secret: str = "", limit: int = 0) -> dict:
    """Traduce una conexión guardada (entrada de tenant.config['custom_sources'] o el
    body del builder) a los kwargs de fetch_rows. El secreto llega ya descifrado por el
    caller: aquí no hay crypto. limit=0 lee todo (con los topes duros del módulo)."""
    return {
        "base_url": src.get("base_url") or "",
        "list_path": src.get("list_path") or "",
        "root": src.get("root") or "",
        "auth_type": src.get("auth_type") or "",
        "auth_header": src.get("auth_header") or "",
        "auth_value": secret,
        "token_url": src.get("token_url") or "",
        "client_id": src.get("client_id") or "",
        "mapping": src.get("mapping") or {},
        "paging": src.get("paging") or "",
        "page_param": src.get("page_param") or "offset",
        "size_param": src.get("size_param", "limit"),
        "page_size": src.get("page_size") or 100,
        "cursor_param": src.get("cursor_param") or "cursor",
        "cursor_path": src.get("cursor_path") or "",
        "timeout": src.get("timeout") or 15,
        "retries": src.get("retries", 2),
        "pause_ms": src.get("pause_ms") or 0,
        "limit": limit,
    }


def _body_desde_mapping(row: dict, mapping: dict) -> dict:
    """El mapping de lectura, invertido: {campo_aiuda: path.en.tu.api} construye el
    body anidado con TUS nombres de campo. Solo viajan los campos con valor."""
    body: dict = {}
    for campo, path in (mapping or {}).items():
        valor = row.get(campo)
        if valor is None or path in ("", None):
            continue
        cursor = body
        partes = str(path).split(".")
        for parte in partes[:-1]:
            cursor = cursor.setdefault(parte, {})
        cursor[partes[-1]] = valor
    return body


def escribir_registro(
    base_url: str,
    write_path: str,
    row: dict,
    mapping: dict | None = None,
    auth_type: str = "",
    auth_header: str = "",
    auth_value: str = "",
    token_url: str = "",
    client_id: str = "",
    timeout: int = 15,
    write_id_path: str = "",
    _sleep=time.sleep,
) -> tuple[dict, str | None]:
    """POST del registro a la API del dueño (inyección aiuda -> su sistema maestro).

    Mismo auth que la lectura. UN intento (sin reintentos: un timeout ambiguo pudo
    haber creado el registro allá y reintentar duplicaría). `write_id_path` es el
    path (con puntos) al id del registro creado dentro de la respuesta; con él la
    presencia queda ligada. Devuelve ({"ref", "respuesta"}, error_legible)."""
    base = (base_url or "").strip()
    if not base.lower().startswith(("http://", "https://")):
        return {}, "La URL debe empezar con http:// o https://."
    if not (write_path or "").strip():
        return {}, "Esta conexión no declara endpoint de escritura (write_path)."
    url = f"{base.rstrip('/')}/{write_path.strip().lstrip('/')}"
    timeout = _clamp(timeout, 1, MAX_TIMEOUT, 15)

    headers, auth_params, err = _resolver_auth(
        auth_type, auth_header, auth_value, token_url, client_id, timeout, _sleep=_sleep
    )
    if err:
        return {}, err

    body = _body_desde_mapping(row, mapping or {})
    if not body:
        return {}, "No hay campos mapeados que enviar (revisa el mapeo de la receta)."
    data, err = _http_json(
        _with_params(url, auth_params),
        {**headers, "Content-Type": "application/json"},
        timeout,
        retries=0,  # write: UN intento
        data=json.dumps(body).encode("utf-8"),
    )
    if err:
        return {}, err
    ref = dig(data, write_id_path) if write_id_path else None
    return {"ref": str(ref) if ref not in (None, "") else None, "enviado": body}, None
