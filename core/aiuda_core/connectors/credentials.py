"""Resolución de credenciales de conectores por tenant.

El motor, el worker y el API piden credenciales AQUÍ, nunca leen ``settings.*``
ni ``tenant.config`` directo. Orden de resolución (lo primero que exista gana):

  1. ``IntegrationCredential`` cifrada del tenant (descifra ``secret_ciphertext``
     y la mezcla con ``public_config``).
  2. ``tenant.config`` en texto plano (legado de la UI): ``['odoo']`` /
     ``['integrations'][provider]`` según el proveedor.
  3. ``settings.*`` globales (self-host single-tenant; solo fallback).

Devuelve un dict con los NOMBRES DE PARÁMETRO del conector, listo para
``Conector(**ctor_kwargs(provider, creds))``, más valores operativos que no van
al constructor (p.ej. ``belvo_link_id``). ``None`` si no hay credenciales por
ninguna vía. Así se cierra la fuga cross-tenant (settings globales compartidos)
y el texto plano en reposo, sin romper el self-host: si no hay fila cifrada, cae
al comportamiento anterior (config legado y, al final, settings globales).

El import de ``crypto`` (y por ende de ``cryptography``) es perezoso: solo se
necesita cuando hay una fila cifrada que descifrar o algo que cifrar. Las vías 2
y 3 no tocan cripto, así que el self-host sin clave sigue andando con globales.

Decisión de seguridad: si una fila existe pero NO descifra (clave retirada o
manipulación), ``get_credential`` propaga ``EncryptionError`` en vez de caer a
settings — no enmascaramos un fallo de seguridad con la credencial global.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from aiuda_core.config import settings
from aiuda_core.models import IntegrationCredential, Tenant

# Registro único: el split secreto/público por proveedor, con qué pasa al
# constructor del conector, el fallback a settings (self-host) y dónde vivía en
# texto plano (legado, para fallback de transición y backfill).
#
#   secret   campos que se cifran (van a secret_ciphertext).
#   public   campos no secretos (van a public_config, se pueden mostrar).
#   ctor     subconjunto que recibe el constructor del conector (excluye
#            operativos como belvo_link_id, que no es argumento del ctor).
#   settings {param_ctor: atributo de settings} para el fallback global.
#   legacy   rutas en tenant.config (orden de preferencia) en texto plano.
#   gate     campo cuya presencia significa "usable" (replica los gates actuales).
#   extras   {param: clave top-level de tenant.config} operativos que se mezclan
#            sin importar de qué vía salió el secreto (hoy solo belvo_link_id).
#
# La clave del proveedor es la MISMA que usa el catálogo/UI (CATALOG en
# api/integrations.py). Verificado: cada nombre de campo coincide con el del
# constructor del conector, así que Conector(**ctor_kwargs(...)) funciona.
PROVIDERS: dict[str, dict] = {
    "odoo": {
        "secret": ["api_key"],
        "public": ["url", "db", "username"],
        "ctor": ["url", "db", "username", "api_key"],
        "settings": {},
        "legacy": ["odoo", "integrations.odoo"],
        "gate": "url",
    },
    "shopify": {
        "secret": ["access_token"],
        "public": ["store_domain"],
        "ctor": ["store_domain", "access_token"],
        "settings": {
            "store_domain": "shopify_store_domain",
            "access_token": "shopify_access_token",
        },
        "legacy": ["integrations.shopify"],
        "gate": "access_token",
    },
    "woocommerce": {
        "secret": ["consumer_key", "consumer_secret"],
        "public": ["base_url"],
        "ctor": ["base_url", "consumer_key", "consumer_secret"],
        "settings": {
            "base_url": "woocommerce_base_url",
            "consumer_key": "woocommerce_consumer_key",
            "consumer_secret": "woocommerce_consumer_secret",
        },
        "legacy": ["integrations.woocommerce"],
        "gate": "consumer_key",
    },
    "belvo": {
        "secret": ["secret_id", "secret_password"],
        "public": ["base_url", "belvo_link_id"],
        "ctor": ["base_url", "secret_id", "secret_password"],
        "settings": {
            "base_url": "belvo_base_url",
            "secret_id": "belvo_secret_id",
            "secret_password": "belvo_secret_password",
        },
        "legacy": ["integrations.belvo"],
        "gate": "secret_id",
        "extras": {"belvo_link_id": "belvo_link_id"},
    },
    "stripe": {
        "secret": ["api_key"],
        "public": [],
        "ctor": ["api_key"],
        "settings": {"api_key": "stripe_api_key"},
        "legacy": ["integrations.stripe"],
        "gate": "api_key",
    },
    # Pasarelas de cobro (link de pago por WhatsApp + confirmación). Un solo secreto cada una.
    "mercadopago": {
        "secret": ["access_token"],
        "public": [],
        "ctor": ["access_token"],
        "settings": {"access_token": "mercadopago_access_token"},
        "legacy": ["integrations.mercadopago"],
        "gate": "access_token",
    },
    "clip": {
        "secret": ["api_key"],
        "public": [],
        "ctor": ["api_key"],
        "settings": {"api_key": "clip_api_key"},
        "legacy": ["integrations.clip"],
        "gate": "api_key",
    },
    "conekta": {
        "secret": ["api_key"],
        "public": [],
        "ctor": ["api_key"],
        "settings": {"api_key": "conekta_api_key"},
        "legacy": ["integrations.conekta"],
        "gate": "api_key",
    },
    "hubspot": {
        "secret": ["token"],
        "public": [],
        "ctor": ["token"],
        "settings": {"token": "hubspot_token"},
        "legacy": ["integrations.hubspot"],
        "gate": "token",
    },
    "facturama": {
        "secret": ["password"],
        "public": ["base_url", "user"],
        "ctor": ["base_url", "user", "password"],
        "settings": {
            "base_url": "facturama_base_url",
            "user": "facturama_user",
            "password": "facturama_password",
        },
        "legacy": ["integrations.facturama"],
        "gate": "user",
    },
    "facturapi": {
        "secret": ["api_key"],
        "public": [],
        "ctor": ["api_key"],
        "settings": {"api_key": "facturapi_api_key"},
        "legacy": ["integrations.facturapi"],
        "gate": "api_key",
    },
    "googlecalendar": {
        "secret": ["token"],
        "public": ["calendar_id"],
        "ctor": ["token", "calendar_id"],
        "settings": {
            "token": "google_calendar_token",
            "calendar_id": "google_calendar_id",
        },
        "legacy": ["integrations.googlecalendar"],
        "gate": "token",
    },
    "denue": {
        "secret": ["token"],
        "public": [],
        "ctor": ["token"],
        "settings": {"token": "denue_token"},
        "legacy": ["integrations.denue"],
        "gate": "token",
    },
    # Google Sheets · solo la API key es secreto; spreadsheet_id/range/tipo son
    # operativos (públicos) y NO van al ctor (el cliente solo recibe la api_key; el
    # rango y el tipo los usa el lector engine/sync.sync_google_sheets).
    "google_sheets": {
        "secret": ["api_key"],
        "public": ["spreadsheet_id", "sheet_range", "tipo"],
        "ctor": ["api_key"],
        "settings": {
            "api_key": "google_sheets_api_key",
            "spreadsheet_id": "google_sheets_spreadsheet_id",
            "sheet_range": "google_sheets_range",
            "tipo": "google_sheets_tipo",
        },
        "legacy": ["integrations.google_sheets"],
        "gate": "api_key",
    },
    # Mercado Libre · app oficial del vendedor. access_token/refresh_token/client_secret
    # se cifran; client_id/seller_id quedan públicos. El ctor recibe todo lo necesario
    # para refrescar al 401 (el conector rota el token en memoria; sync lo persiste).
    "mercadolibre": {
        "secret": ["access_token", "refresh_token", "client_secret"],
        "public": ["client_id", "seller_id"],
        "ctor": ["access_token", "refresh_token", "client_id", "client_secret", "seller_id"],
        "settings": {
            "access_token": "mercadolibre_access_token",
            "refresh_token": "mercadolibre_refresh_token",
            "client_id": "mercadolibre_client_id",
            "client_secret": "mercadolibre_client_secret",
            "seller_id": "mercadolibre_seller_id",
        },
        "legacy": ["integrations.mercadolibre"],
        "gate": "access_token",
    },
    # Generación de imágenes (plantilla de Contenido). Solo la api_key es secreto; provider
    # (fal/openai/custom), base_url (self-host) y model son operativos/públicos. El ctor los
    # recibe todos para armar el cliente agnóstico (connectors/image_gen.ImageGenClient).
    "image_gen": {
        "secret": ["api_key"],
        "public": ["provider", "base_url", "model"],
        "ctor": ["provider", "api_key", "base_url", "model"],
        "settings": {},
        "legacy": ["integrations.image_gen"],
        "gate": "api_key",
    },
    # El canal es a dónde salen los avisos internos (aviso_al_equipo); no es secreto.
    "slack": {
        "secret": ["bot_token"],
        "public": ["channel"],
        "ctor": ["bot_token"],
        "settings": {"bot_token": "slack_bot_token", "channel": "slack_channel"},
        "legacy": ["integrations.slack"],
        "gate": "bot_token",
    },
    # API OFICIAL de WhatsApp Business (Cloud API de Meta). El token se cifra; el
    # phone_number_id queda público (rutea el webhook al tenant sin descifrar). La
    # plantilla aprobada (nombre + idioma) es config del canal, no secreto.
    "whatsapp_cloud": {
        "secret": ["access_token"],
        "public": ["phone_number_id", "waba_id", "template_cobranza", "template_idioma"],
        "ctor": ["access_token", "phone_number_id"],
        "settings": {},
        "legacy": ["integrations.whatsapp_cloud"],
        "gate": "access_token",
    },
    "evolution": {
        "secret": ["api_key"],
        "public": ["base_url"],
        "ctor": ["base_url", "api_key"],
        "settings": {
            "api_key": "evolution_api_key",
            "base_url": "evolution_base_url",
        },
        "legacy": ["integrations.evolution"],
        "gate": "api_key",
    },
    # Llamadas de voz (Twilio). El auth_token se cifra; account_sid y from_number quedan
    # públicos (el account_sid rutea el StatusCallback al tenant sin descifrar). El
    # conector se construye vía TwilioVozInstance.client() (channel.resolve_voz), no por
    # ctor_kwargs: el canal necesita también el número de origen.
    "twilio_voz": {
        "secret": ["auth_token"],
        "public": ["account_sid", "from_number"],
        "ctor": ["account_sid", "auth_token"],
        "settings": {},
        "legacy": ["integrations.twilio_voz"],
        "gate": "account_sid",
    },
    # Correo del negocio por IMAP/SMTP: sirve a IMAP genérico, Gmail y Outlook (todos
    # hablan IMAP con contraseña de aplicación — la vía COMPLETA hoy). `provider` guarda
    # cuál eligió el dueño (imap/google/microsoft) para hints. `auth_method` decide la
    # autenticación: 'password' (vivo) u 'oauth' (config-ready HONESTO: los campos
    # oauth_* se guardan cifrados y el flujo está documentado en connectors/correo.py,
    # pero el intercambio XOAUTH2 no está cableado — usarlo lanza CorreoNoDisponible).
    # El conector se construye vía CorreoInstance.client() (channel.resolve_correo),
    # no por ctor_kwargs: el canal necesita también al tenant (nombre del remitente).
    "email": {
        "secret": ["password", "oauth_client_secret", "oauth_refresh_token"],
        "public": [
            "provider", "email", "imap_host", "imap_port", "smtp_host", "smtp_port",
            "auth_method", "oauth_client_id",
        ],
        "ctor": [],
        "settings": {},
        "legacy": ["integrations.email"],
        "gate": "email",
    },
    # La e.firma (FIEL) del SAT para la Descarga Masiva de CFDI. UNA credencial
    # POR RFC: el negocio puede tener hasta 3 empresas (razones sociales) y cada
    # una guarda su fila como "sat_efirma:<RFC>" (ver _spec_of), cifrada aparte y
    # borrable sola. Los tres campos son secreto: el certificado y la llave van
    # en base64 dentro del blob cifrado; se descifran SOLO en memoria por corrida
    # (connectors/sat_descarga.py), sin caché, sin temporales, sin logs. Lo único
    # público es lo que la UI enseña: RFC, titular y vigencia.
    "sat_efirma": {
        "secret": ["cer", "key", "password"],
        "public": ["rfc", "titular", "vigente_desde", "vigente_hasta"],
        "ctor": [],
        "settings": {},
        "legacy": [],
        "gate": "key",
    },
    # Proveedor de IA. NO es un conector de sync (sin ctor): es el secreto del
    # modelo que el dueño conecta en /proveedor. Vive aquí para CIFRARLO con la
    # misma maquinaria por tenant; la resolución a cliente Anthropic sigue en
    # aiuda_core.engine.provider. `legacy=['provider']` lee el texto plano viejo
    # (tenant.config['provider'] = {name, mode, secret}) como fallback de transición.
    "ia": {
        "secret": ["secret"],
        "public": ["name", "mode"],
        "ctor": [],
        "settings": {},
        "legacy": ["provider"],
        "gate": "secret",
    },
}

_SECRET_HINT = ("token", "key", "password", "secret")


def _looks_secret(field: str) -> bool:
    return any(h in field.lower() for h in _SECRET_HINT)


def _spec_of(provider: str) -> dict | None:
    """La spec del proveedor. Un proveedor puede tener VARIAS filas por tenant
    con sufijo (``sat_efirma:HCO250213281``): la parte antes de ``:`` resuelve
    la spec y el sufijo distingue la fila (una e.firma por RFC, hasta 3
    empresas del mismo negocio). La unicidad (tenant, provider) sigue intacta."""
    return PROVIDERS.get(provider) or PROVIDERS.get(provider.partition(":")[0])


def secret_fields(provider: str) -> set[str]:
    """Campos secretos de un proveedor. Sin spec, por heurística sobre los nombres
    de campo recibidos (token/key/password/secret)."""
    spec = _spec_of(provider)
    return set(spec["secret"]) if spec else set()


def all_fields(provider: str) -> list[str]:
    """Campos (públicos + secretos) que el proveedor maneja, en orden estable."""
    spec = _spec_of(provider)
    if not spec:
        return []
    return [*spec["public"], *spec["secret"]]


def ctor_kwargs(provider: str, creds: dict) -> dict:
    """Filtra ``creds`` a los argumentos del constructor del conector (deja fuera
    operativos como ``belvo_link_id``). Omite los que no estén presentes."""
    spec = _spec_of(provider)
    if not spec:
        return dict(creds)
    return {k: creds[k] for k in spec["ctor"] if creds.get(k) is not None}


def _dig(cfg: dict, path: str) -> dict:
    """Lee una ruta de ``tenant.config`` como dict. ``'odoo'`` -> cfg['odoo'];
    ``'integrations.odoo'`` -> cfg['integrations']['odoo']."""
    node: object = cfg
    for part in path.split("."):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return dict(node) if isinstance(node, dict) else {}


def _usable(spec: dict, cand: dict) -> bool:
    return bool(cand.get(spec["gate"]))


def _from_encrypted(row: IntegrationCredential) -> dict:
    public = dict(row.public_config or {})
    secret: dict = {}
    if row.secret_ciphertext:
        from aiuda_core.security import crypto  # perezoso: solo si hay fila cifrada

        raw = crypto.decrypt(row.secret_ciphertext, row.key_version)
        secret = json.loads(raw) if raw else {}
    return {**public, **secret}  # el secreto gana ante colisión de llave


def _with_extras(spec: dict, session, tenant_id: str, creds: dict) -> dict:
    """Mezcla valores operativos que viven en tenant.config top-level (p.ej.
    belvo_link_id) si no vinieron ya en la credencial."""
    extras = spec.get("extras")
    if not extras:
        return creds
    tenant = session.get(Tenant, tenant_id)
    cfg = (tenant.config or {}) if tenant is not None else {}
    out = dict(creds)
    for param, cfg_key in extras.items():
        if not out.get(param) and cfg.get(cfg_key):
            out[param] = cfg[cfg_key]
    return out


def _row(session, tenant_id: str, provider: str) -> IntegrationCredential | None:
    return session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider == provider,
            IntegrationCredential.status != "disabled",
        )
    )


def get_credential(session, tenant_id: str, provider: str) -> dict | None:
    """Credenciales efectivas del conector para este tenant (dict de args +
    operativos), o ``None`` si no hay por ninguna vía.

    Propaga ``EncryptionError`` si hay fila pero no descifra: no caemos a settings
    para no enmascarar un fallo de seguridad."""
    spec = _spec_of(provider)
    if spec is None:
        return None

    row = _row(session, tenant_id, provider)
    if row is not None:
        return _with_extras(spec, session, tenant_id, _from_encrypted(row))

    tenant = session.get(Tenant, tenant_id)
    cfg = (tenant.config or {}) if tenant is not None else {}

    for path in spec["legacy"]:
        cand = {k: v for k, v in _dig(cfg, path).items() if v}
        if _usable(spec, cand):
            return _with_extras(spec, session, tenant_id, cand)

    cand = {}
    for param, attr in spec["settings"].items():
        val = getattr(settings, attr, None)
        if val:
            cand[param] = val
    if _usable(spec, cand):
        return _with_extras(spec, session, tenant_id, cand)

    return None


def has_credential(session, tenant_id: str, provider: str) -> bool:
    """¿Existe una fila cifrada configurada para (tenant, provider)? Señal nueva
    para el catálogo (``_is_connected``), sin descifrar. No reemplaza los fallbacks
    legacy/settings, que conviven para no regresionar self-host."""
    return _row(session, tenant_id, provider) is not None


def read_stored(session, tenant_id: str, provider: str) -> dict | None:
    """Valores GUARDADOS en la fila cifrada (público + secreto descifrado), sin
    fallback a config/settings. Para enmascarar en GET y conservar el secreto
    previo en PUT. ``None`` si no hay fila."""
    row = _row(session, tenant_id, provider)
    return _from_encrypted(row) if row is not None else None


def set_credential(
    session, tenant_id: str, provider: str, values: dict
) -> IntegrationCredential:
    """Guarda credenciales cifrando los campos secretos. Upsert por (tenant,
    provider). Los no secretos van en ``public_config`` (visibles); los secretos
    se cifran juntos en ``secret_ciphertext`` y NUNCA se guardan en claro. Pone
    ``status='configured'`` (un test exitoso lo sube a 'connected')."""
    from aiuda_core.security import crypto  # perezoso

    known = secret_fields(provider)

    def is_secret(field: str) -> bool:
        return field in known if known else _looks_secret(field)

    secret = {k: v for k, v in values.items() if v and is_secret(k)}
    public = {k: v for k, v in values.items() if v and not is_secret(k)}
    ciphertext, version = crypto.encrypt(json.dumps(secret, separators=(",", ":")))

    row = session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider == provider,
        )
    )
    if row is None:
        row = IntegrationCredential(tenant_id=tenant_id, provider=provider)
        session.add(row)
    row.secret_ciphertext = ciphertext
    row.key_version = version
    row.public_config = public
    row.status = "configured"
    session.flush()
    return row


def refresh_secret(session, tenant_id: str, provider: str, values: dict) -> bool:
    """Re-cifra el secreto de una fila EXISTENTE sin tocar su ``status`` ni crear fila
    nueva. Para rotación de token (p.ej. el refresh de OpenAI/Codex): la conexión sigue
    'connected'. Mezcla los públicos con los ya guardados. Devuelve True si actualizó."""
    from aiuda_core.security import crypto  # perezoso

    row = session.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider == provider,
        )
    )
    if row is None:
        return False

    known = secret_fields(provider)

    def is_secret(field: str) -> bool:
        return field in known if known else _looks_secret(field)

    secret = {k: v for k, v in values.items() if v and is_secret(k)}
    public = {**(row.public_config or {}), **{k: v for k, v in values.items() if v and not is_secret(k)}}
    ciphertext, version = crypto.encrypt(json.dumps(secret, separators=(",", ":")))
    row.secret_ciphertext = ciphertext
    row.key_version = version
    row.public_config = public
    session.flush()
    return True
