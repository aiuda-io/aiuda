"""Conexiones a la medida (conector genérico por API) — el fallback abierto de aiuda.

El usuario declara una fuente REST: URL, auth (header, bearer, query, basic, OAuth2 CC),
paginación y qué campo del JSON es cada dato. aiuda la prueba EN VIVO, la guarda (con el
secreto CIFRADO en tenant.config, nunca en claro) y el motor la lee en cada corrida como
una fuente más (engine/sync.sync_custom). La lectura pura vive en core/connectors/custom_api.

Open core: la conexión se puede EXPORTAR como receta (JSON declarativo SIN secretos) e
IMPORTAR una receta de la comunidad — al importar, la clave la capturas tú.
"""

import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm.attributes import flag_modified

from aiuda_server.api.deps import get_db, get_tenant
from aiuda_core.connectors import custom_api
from aiuda_core.models import Tenant

router = APIRouter()

# Qué campos tiene sentido mapear según la necesidad. Guía al builder; el motor los usa al
# ingerir (engine/sync._CUSTOM_READERS). 'name' es la única que en la práctica no puede
# faltar (un registro sin nombre no sirve).
CAP_FIELDS: dict[str, list[str]] = {
    "directorio_clientes": ["name", "phone", "email", "external_id"],
    "cuentas_por_cobrar": ["customer", "phone", "folio", "amount", "due_date", "external_id"],
    "catalogo_productos": ["name", "sku", "price", "stock", "external_id"],
    "agenda": ["title", "starts_at", "customer", "external_id"],
    "prospeccion": ["name", "phone", "email", "external_id"],
    "expedientes": ["title", "customer", "external_id"],
}
_DEFAULT_FIELDS = ["name", "external_id"]


class TestBody(BaseModel):
    base_url: str
    list_path: str = ""
    root: str = ""
    # Auth: "" = ninguna (o el legado header si auth_header viene), ver custom_api.
    auth_type: str = ""
    auth_header: str = ""  # nombre del header o del query param, según auth_type
    auth_value: str = ""  # el secreto; en editar/re-probar, vacío = usa el guardado
    token_url: str = ""  # OAuth2 client-credentials
    client_id: str = ""  # OAuth2 client-credentials
    mapping: dict[str, str] = {}
    # Paginación y comportamiento HTTP (custom_api acota todo con topes duros).
    paging: str = ""  # "" | offset | cursor
    page_param: str = "offset"
    size_param: str = "limit"
    page_size: int = 100
    cursor_param: str = "cursor"
    cursor_path: str = ""
    timeout: int = 15
    retries: int = 2
    pause_ms: int = 0
    # Escritura (inyección aiuda -> tu API): endpoint del POST de alta y el path
    # (con puntos) al id del registro creado en la respuesta. Vacíos = solo lectura.
    write_path: str = ""
    write_id_path: str = ""


class CreateBody(TestBody):
    name: str
    cap: str


# Lo que se guarda de la declaración (el secreto va aparte, cifrado).
_CONFIG_KEYS = (
    "base_url", "list_path", "root", "auth_type", "auth_header", "token_url", "client_id",
    "mapping", "paging", "page_param", "size_param", "page_size", "cursor_param",
    "cursor_path", "timeout", "retries", "pause_ms", "write_path", "write_id_path",
)

# La receta compartible: la declaración SIN identidad ni secretos. client_id queda fuera
# (identifica TU app OAuth, no es parte de una plantilla comunitaria).
_RECETA_KEYS = tuple(k for k in _CONFIG_KEYS if k != "client_id")


def _config_from(body: TestBody) -> dict:
    d = body.model_dump()
    return {k: d[k] for k in _CONFIG_KEYS}


def _encrypt_secret(auth_value: str) -> tuple[str, int]:
    if not auth_value:
        return "", 0
    from aiuda_core.security import crypto

    ct, ver = crypto.encrypt(auth_value)
    return base64.b64encode(ct).decode(), ver


def _decrypt_secret(entry: dict) -> tuple[str, str | None]:
    """El secreto guardado, descifrado. (valor, error legible)."""
    ct = entry.get("secret_ct") or ""
    if not ct:
        return "", None
    try:
        from aiuda_core.security import crypto

        return crypto.decrypt(base64.b64decode(ct), int(entry.get("secret_ver") or 1)), None
    except Exception:  # noqa: BLE001 — el porqué se devuelve legible, no como 500
        return "", "No se pudo descifrar la clave guardada. Vuelve a capturarla."


def _public(c: dict) -> dict:
    """La forma que ve el front: sin el secreto cifrado (pero diciendo si hay clave)."""
    out = {k: v for k, v in c.items() if k not in ("secret_ct", "secret_ver")}
    out["has_secret"] = bool(c.get("secret_ct"))
    return out


def _sources(tenant: Tenant) -> list[dict]:
    return list((tenant.config or {}).get("custom_sources") or [])


def _find(sources: list[dict], cid: str) -> dict:
    entry = next((c for c in sources if c.get("id") == cid), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Conexión no encontrada.")
    return entry


def _save(db, tenant: Tenant, sources: list[dict]) -> None:
    # Columna JSON: reasignar + flag_modified para que SQLAlchemy persista el cambio.
    tenant.config = {**(tenant.config or {}), "custom_sources": sources}
    flag_modified(tenant, "config")
    db.add(tenant)
    db.commit()


@router.get("/v1/custom-connectors/fields")
def campos_por_necesidad():
    """Qué campos mapear según la necesidad (para armar el builder)."""
    return {"cap_fields": CAP_FIELDS, "default": _DEFAULT_FIELDS}


def _probar(body: TestBody, secret: str) -> dict:
    rows, err = custom_api.fetch_rows(**custom_api.kwargs_from_source(body.model_dump(), secret, limit=5))
    return {"ok": err is None, "error": err, "count": len(rows), "sample": rows}


@router.post("/v1/custom-connectors/test")
def probar(body: TestBody, tenant: Tenant = Depends(get_tenant)):
    """Prueba en vivo: trae unos registros de la API del usuario y los mapea. Es la señal
    honesta de que la conexión sirve, ANTES de guardarla."""
    return _probar(body, body.auth_value)


@router.get("/v1/custom-connectors")
def listar(tenant: Tenant = Depends(get_tenant)):
    return [_public(c) for c in _sources(tenant)]


@router.post("/v1/custom-connectors")
def crear(body: CreateBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Ponle un nombre a la conexión.")
    secret_ct, secret_ver = _encrypt_secret(body.auth_value)
    sources = _sources(tenant)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": body.name.strip(),
        "cap": body.cap,
        **_config_from(body),
        "secret_ct": secret_ct,
        "secret_ver": secret_ver,
    }
    sources.append(entry)
    _save(db, tenant, sources)
    return _public(entry)


@router.put("/v1/custom-connectors/{cid}")
def editar(cid: str, body: CreateBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Edita una conexión guardada. La clave solo se reemplaza si mandas una nueva:
    vacía = se conserva la cifrada que ya estaba (nunca viaja de regreso al front)."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Ponle un nombre a la conexión.")
    sources = _sources(tenant)
    entry = _find(sources, cid)
    entry.update({"name": body.name.strip(), "cap": body.cap, **_config_from(body)})
    if body.auth_value:
        entry["secret_ct"], entry["secret_ver"] = _encrypt_secret(body.auth_value)
    _save(db, tenant, sources)
    return _public(entry)


@router.post("/v1/custom-connectors/{cid}/test")
def reprobar(
    cid: str,
    body: TestBody | None = None,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Re-prueba una conexión guardada con su clave cifrada. Sin body usa la declaración
    guardada (el botón Probar de la lista); con body usa lo que estás editando y, si no
    mandas clave, la guardada. El resultado queda registrado en la conexión."""
    sources = _sources(tenant)
    entry = _find(sources, cid)
    declaracion = body if body is not None else TestBody(**{k: entry.get(k) for k in _CONFIG_KEYS if entry.get(k) is not None})
    secret = declaracion.auth_value
    err = None
    if not secret:
        secret, err = _decrypt_secret(entry)
    if err:
        resultado = {"ok": False, "error": err, "count": 0, "sample": []}
    else:
        resultado = _probar(declaracion, secret)
    entry["last_test_at"] = datetime.now().isoformat(timespec="seconds")
    entry["last_test_ok"] = resultado["ok"]
    entry["last_test_error"] = resultado["error"] or ""
    _save(db, tenant, sources)
    return resultado


@router.delete("/v1/custom-connectors/{cid}")
def borrar(cid: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    sources = _sources(tenant)
    kept = [c for c in sources if c.get("id") != cid]
    if len(kept) == len(sources):
        raise HTTPException(status_code=404, detail="Conexión no encontrada.")
    _save(db, tenant, kept)
    return {"ok": True}


@router.get("/v1/custom-connectors/{cid}/receta")
def exportar_receta(cid: str, tenant: Tenant = Depends(get_tenant)):
    """La receta del conector: la declaración completa, SIN secretos ni identidad.
    Compartible tal cual (open core: plantillas comunitarias)."""
    entry = _find(_sources(tenant), cid)
    defaults = TestBody(base_url="").model_dump()
    receta = {"receta": 1, "app": "aiuda", "name": entry.get("name") or "", "cap": entry.get("cap") or ""}
    receta.update({k: entry.get(k, defaults.get(k)) for k in _RECETA_KEYS})
    return receta


class ImportBody(BaseModel):
    receta: dict


@router.post("/v1/custom-connectors/importar")
def importar_receta(body: ImportBody, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Crea una conexión desde una receta exportada (o escrita a mano). El secreto NUNCA
    viaja en una receta: si trae campos de clave se ignoran; la capturas tú al editar."""
    r = body.receta or {}
    name = str(r.get("name") or "").strip()
    cap = str(r.get("cap") or "").strip()
    base_url = str(r.get("base_url") or "").strip()
    if not name or not cap or not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="La receta necesita al menos name, cap y base_url (http/https).",
        )
    # Reusar la validación/coerción de TestBody, descartando llaves ajenas y CUALQUIER
    # secreto que venga colado (una receta jamás trae claves).
    campos = {k: v for k, v in r.items() if k in TestBody.model_fields and k != "auth_value"}
    try:
        declaracion = TestBody(**campos)
    except ValidationError:
        raise HTTPException(status_code=422, detail="La receta tiene valores inválidos.") from None
    sources = _sources(tenant)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "cap": cap,
        **_config_from(declaracion),
        "client_id": "",  # una receta no carga la identidad OAuth de nadie
        "secret_ct": "",
        "secret_ver": 0,
    }
    sources.append(entry)
    _save(db, tenant, sources)
    return _public(entry)
