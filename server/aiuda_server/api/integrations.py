"""Grafo de integraciones del tenant para la vista de red (mapa mental).

Devuelve, por sistema, si está conectado y en qué dirección fluyen los datos
con aiuda. La detección de "conectado" combina tres señales reales:
  1. credenciales en tenant.config (Odoo, Belvo)
  2. tokens globales en settings (Shopify, Stripe, etc. — self-host single-tenant)
  3. datos que ya entraron: source + presence de facturas y clientes

Así el grafo refleja la verdad del negocio, no un catálogo estático.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aiuda_server import audit
from aiuda_server.api.deps import get_db, get_tenant, require_role
from aiuda_core.config import settings
from aiuda_core.connectors import credentials as cred
from aiuda_core.connectors.channel import UNOFFICIAL_WHATSAPP_WARNING
from aiuda_core.models import (
    Ayudante,
    CfdiBoveda,
    Conversation,
    Customer,
    IntegrationCredential,
    Invoice,
    Tenant,
)

router = APIRouter()

# Campos que se ocultan al devolver la config (credenciales). La definición vive en
# core (connectors/credentials.py) y se importa: tenerla duplicada aquí fue parte del
# bug que dejaba secretos en texto plano.
SECRET_HINT = cred.SECRET_HINT

# Dirección de flujo (define cómo se dibuja la arista):
#   read     sistema -> aiuda   (aiuda jala datos)
#   writeback aiuda -> sistema   (aiuda inyecta lo confirmado)
#   channel  sistema <-> aiuda  (WhatsApp: entra y sale)
#   confirm  sistema -> aiuda   (banco/Stripe confirman un pago)

# group: canal | datos | fiscal | operacion
# live NO se declara aquí: se DERIVA más abajo de la única fuente de verdad
#      (_LECTURA_CABLEADA + _NON_READ_LIVE). Antes había literales "live" en este
#      catálogo que el bucle pisaba al importar y quedaban contradiciendo al código
#      (facturama/facturapi/googlecalendar/hubspot/denue decían False siendo True).
# does = qué hace aiuda con esta integración (honesto, en una línea).
CATALOG = [
    {"key": "whatsapp", "name": "WhatsApp (tu número)", "group": "canal", "logo": "/brand/int/whatsapp.png", "color": "#25D366", "flows": ["channel"], "rol": "Tu número, en tu computadora", "does": "Tus clientes te escriben y tú respondes y apruebas desde la consola. Se conecta con QR como WhatsApp Web, con tu propio número; para enviar a volumen está WhatsApp Business (oficial).", "warning": UNOFFICIAL_WHATSAPP_WARNING},
    {"key": "whatsapp_cloud", "name": "WhatsApp Business (oficial)", "group": "canal", "logo": "/brand/int/whatsapp.png", "color": "#075E54", "flows": ["channel"], "rol": "La API oficial de Meta, para volumen", "does": "Envía y recibe por la Cloud API oficial de Meta: texto libre dentro de la ventana de 24 horas y plantillas aprobadas fuera de ella. Necesita un servidor con URL pública para recibir webhooks (no aplica corriendo solo local). Implementado contra el contrato documentado; PENDIENTE de verificar en vivo."},
    {"key": "email", "name": "Correo", "group": "canal", "logo": None, "color": "#2f6fed", "flows": ["channel"], "rol": "Correo del negocio: IMAP, Google o Microsoft", "does": "Lee tu buzón (IMAP): los correos de tus clientes entran como hilos a la bandeja, tu ayudante PROPONE la respuesta y tú apruebas antes de que salga (SMTP, enhebrado al hilo). Gmail y Outlook entran hoy con contraseña de aplicación; OAuth queda documentado, por cablear."},
    {"key": "slack", "name": "Slack", "group": "canal", "logo": "/brand/int/slack.webp", "color": "#611f69", "flows": ["channel"], "rol": "Avisos al equipo dentro de tu workspace", "does": "Publica en tu canal de Slack los avisos que aiuda ya genera: el resumen diario de cartera y el aviso cuando la IA se pausa por tope. Implementado contra el contrato documentado (chat.postMessage); PENDIENTE de verificar en vivo — captura bot token y canal y usa 'Probar conexión'."},
    {"key": "twilio_voz", "name": "Llamadas de voz (Twilio)", "group": "canal", "logo": None, "color": "#F22F46", "flows": ["channel"], "rol": "Llama a tus clientes con el recordatorio", "does": "Llama a tus clientes y les DICE el recordatorio aprobado con voz (es-MX); Twilio te avisa si contestó o no y cada resultado queda en la ficha. Requiere tu cuenta de Twilio y un número comprado; Twilio cobra por minuto de llamada. Implementado contra el contrato documentado de la API REST; PENDIENTE de verificar en vivo — captura tus credenciales y usa 'Probar conexión'."},

    {"key": "excel", "name": "Excel / CSV", "group": "datos", "logo": None, "color": "#1f9d6d", "flows": ["read"], "rol": "Subes cualquier hoja y la IA entiende qué es", "does": "Subes cualquier Excel (clientes, productos, facturas, citas, prospectos) y la IA detecta qué es y lo carga al lugar correcto (re-subir no duplica)."},
    {"key": "odoo", "name": "Odoo", "group": "datos", "logo": "/brand/int/odoo.svg", "color": "#714B67", "flows": ["read", "writeback"], "rol": "Lee tu cartera y regresa lo cobrado", "does": "Lee tu cartera de Odoo (facturas, clientes, catálogo, compras) y regresa lo cobrado: asienta el pago contra la factura y actualiza el cliente."},
    {"key": "shopify", "name": "Shopify", "group": "datos", "logo": "/brand/int/shopify.svg", "color": "#95BF47", "flows": ["read", "writeback"], "rol": "Pedidos por cobrar y nota de pago de vuelta", "does": "Trae tus pedidos por cobrar y registra de vuelta la nota de pago."},
    {"key": "woocommerce", "name": "WooCommerce", "group": "datos", "logo": "/brand/int/woocommerce.svg", "color": "#7F54B3", "flows": ["read"], "rol": "Pedidos pendientes de tu tienda", "does": "Trae los pedidos pendientes de tu tienda a tu cartera."},
    {"key": "google_sheets", "name": "Google Sheets", "group": "datos", "logo": None, "color": "#0F9D58", "flows": ["read"], "rol": "Una hoja compartida como fuente", "does": "Lee una hoja de Google Sheets compartida ('cualquiera con el enlace · lector'): declaras el rango y qué trae (facturas, clientes o productos) y aiuda mapea las columnas por su nombre y las carga. Solo lectura por API key; OAuth para hojas privadas queda por cablear. PENDIENTE de verificar en vivo — captura tu API key y usa 'Probar conexión'."},
    {"key": "mercadolibre", "name": "Mercado Libre", "group": "datos", "logo": None, "color": "#FFE600", "flows": ["read"], "rol": "Tus ventas de Mercado Libre a tu cartera", "does": "Trae tus ventas con pago pendiente a la cartera, tu catálogo (publicaciones con precio y existencia) y los compradores recientes al directorio. API oficial (api.mercadolibre.com) con refresco de token OAuth. PENDIENTE de verificar en vivo — captura las credenciales de tu app y usa 'Probar conexión'."},

    {"key": "belvo", "name": "Belvo", "group": "fiscal", "logo": "/brand/int/belvo.svg", "color": "#0663F9", "flows": ["confirm"], "rol": "Confirma pagos viendo tu banco", "does": "Detecta en tu banco los depósitos que confirman tus facturas."},
    {"key": "stripe", "name": "Stripe", "group": "fiscal", "logo": "/brand/int/stripe.png", "color": "#635BFF", "flows": ["confirm"], "rol": "Confirma cobros con tarjeta", "does": "Detecta tus cobros con tarjeta para confirmar pagos."},
    {"key": "mercadopago", "name": "Mercado Pago", "group": "fiscal", "logo": None, "color": "#00B1EA", "flows": ["confirm", "action"], "rol": "Cobra por link de WhatsApp y confirma", "does": "Genera un link de pago (Checkout Pro) que tu ayudante manda con el recordatorio; el cliente paga con un clic. Y detecta los pagos aprobados para confirmar tus facturas. Implementado contra el contrato documentado; PENDIENTE de verificar en vivo — captura tu access token y usa 'Probar conexión'."},
    {"key": "clip", "name": "Clip", "group": "fiscal", "logo": None, "color": "#FF5A2D", "flows": ["confirm", "action"], "rol": "Link de pago para changarros y PyMEs", "does": "Crea un link de pago que tu ayudante envía por WhatsApp con el recordatorio, y detecta los pagos ya cobrados para confirmar facturas. La vía más difundida en el changarro mexicano. Implementado contra el contrato documentado; PENDIENTE de verificar en vivo — captura tu API key y usa 'Probar conexión'."},
    {"key": "conekta", "name": "Conekta", "group": "fiscal", "logo": None, "color": "#01203E", "flows": ["confirm", "action"], "rol": "Cobra en OXXO, SPEI o tarjeta", "does": "Crea un link de pago que acepta tarjeta, OXXO Pay (efectivo) y SPEI (transferencia) — clave para quien no usa tarjeta. Tu ayudante lo manda por WhatsApp y confirma cuando el pago entra. Implementado contra el contrato documentado; PENDIENTE de verificar en vivo — captura tu private key y usa 'Probar conexión'."},
    {"key": "sat", "name": "SAT · Bóveda fiscal", "group": "fiscal", "logo": None, "color": "#6B1F3A", "flows": ["read"], "rol": "Tus CFDI y cartera fiscal, hasta 3 RFCs", "does": "Importa XML o ZIP y descarga CFDI con e.firma cifrada. Clasifica PPD, PUE, pagos, egresos e intercompañía. La descarga automática está cableada; falta verificarla contra el SAT vivo."},
    {"key": "facturama", "name": "Facturama", "group": "fiscal", "logo": "/brand/int/facturama.jpg", "color": "#C4453A", "flows": ["read"], "rol": "Lee tus CFDI como respaldo fiscal", "does": "Lee tus CFDI del SAT como respaldo fiscal (el conector aún no timbra)."},
    {"key": "facturapi", "name": "Facturapi", "group": "fiscal", "logo": "/brand/int/facturapi.png", "color": "#3B82C4", "flows": ["read"], "rol": "Lee tus CFDI como respaldo fiscal", "does": "Lee tus CFDI del SAT como respaldo fiscal (el conector aún no timbra)."},

    {"key": "googlecalendar", "name": "Google Calendar", "group": "operacion", "logo": "/brand/int/googlecalendar.svg", "color": "#4285F4", "flows": ["read"], "rol": "Citas y recordatorios de agenda", "does": "Lee tu disponibilidad para agendar citas."},
    {"key": "hubspot", "name": "HubSpot", "group": "operacion", "logo": "/brand/int/hubspot.svg", "color": "#FF7A59", "flows": ["read"], "rol": "Contactos y actividad del CRM", "does": "Lee contactos y oportunidades de tu CRM."},
    {"key": "denue", "name": "DENUE · INEGI", "group": "operacion", "logo": None, "color": "#16415a", "flows": ["read"], "rol": "Directorio público para prospectar", "does": "Busca empresas en el directorio público para prospectar."},
    {"key": "image_gen", "name": "Generación de imágenes", "group": "operacion", "logo": None, "color": "#7c3aed", "flows": ["action"], "rol": "El motor visual de la plantilla de Contenido", "does": "Genera las imágenes de tus publicaciones desde el prompt del ayudante. Pluggable: fal.ai con modelos open-weights (Flux, el más barato por imagen), OpenAI (gpt-image-1) o tu propio endpoint self-host compatible. Implementado contra el contrato documentado; PENDIENTE de verificar en vivo — captura tu API key y usa 'Probar conexión'."},
]


CATALOG_KEYS = {item["key"] for item in CATALOG}


# --- Capa de capacidades ----------------------------------------------------
# Una CAPACIDAD es una función de negocio, independiente de la fuente que la
# cumple. El aiudante depende de capacidades, no de sistemas: la relación
# aiudante <-> fuente se DERIVA cruzando lo que el agente necesita con lo que
# cada fuente provee. Así una sola fuente sirve a varios aiudantes y, cuando
# Odoo gane una capacidad nueva (p.ej. catálogo), se conecta solo a quien la
# necesita sin tocar el cableado de cada agente. Ese cruce es lo que evita el
# desorden de mantener N agentes x M sistemas a mano.
CAPABILITIES: dict[str, dict] = {
    "cuentas_por_cobrar": {"label": "Cuentas por cobrar", "desc": "Tu cartera: facturas y pedidos con saldo pendiente."},
    "mensajeria": {"label": "Mensajería con clientes", "desc": "El canal por donde hablas con tus clientes."},
    "confirmacion_pago": {"label": "Confirmación de pago", "desc": "Verificar contra el banco o la pasarela que un pago entró."},
    "link_de_pago": {"label": "Cobro con link de pago", "desc": "Genera un link para que el cliente pague por WhatsApp (tarjeta, OXXO, SPEI)."},
    "cfdi": {"label": "CFDI y respaldo fiscal", "desc": "Tus comprobantes fiscales del SAT."},
    "directorio_clientes": {"label": "Directorio de clientes", "desc": "El maestro de clientes y contactos."},
    "catalogo_productos": {"label": "Catálogo de productos", "desc": "Lo que vendes: productos, precios, existencias."},
    "agenda": {"label": "Agenda y citas", "desc": "Disponibilidad y citas del calendario."},
    "prospeccion": {"label": "Prospección", "desc": "Directorios para encontrar nuevos clientes."},
    "expedientes": {"label": "Expedientes", "desc": "Casos, acuerdos y documentos de respaldo (lo opera el CUA sobre el portal del tribunal)."},
    "avisos_equipo": {"label": "Avisos al equipo", "desc": "Notificaciones internas para tu gente."},
    "compras": {"label": "Compras y proveedores", "desc": "Órdenes de compra y abasto."},
    "generacion_contenido": {"label": "Generación de contenido", "desc": "Imágenes para tus publicaciones y campañas, desde el prompt del ayudante."},
}

# Qué capacidad(es) provee cada fuente. Solo la lista; si una capacidad YA corre
# sola hoy (live) NO se declara a mano aquí: se DERIVA de una sola fuente de verdad
# (abajo). Antes había dos tablas —SOURCE_CAPS con `live` a mano y _LECTURA_CABLEADA—
# que se contradecían: el mismo par (fuente, capacidad) salía "por conectar" en el
# mapa y "seleccionable" en los aiudantes. Ahora todo sale de _LECTURA_CABLEADA.
_SOURCE_PROVIDES: dict[str, list[str]] = {
    "whatsapp": ["mensajeria"],
    "whatsapp_cloud": ["mensajeria"],  # canal oficial (Cloud API de Meta)
    "email": ["mensajeria"],  # canal de correo: lectura IMAP en sync + envío SMTP (vivo)
    # El importador universal entiende cualquier hoja: cartera, directorio, catálogo,
    # agenda y prospectos. Todas vivas (la ingesta es real).
    "excel": ["cuentas_por_cobrar", "directorio_clientes", "catalogo_productos", "agenda", "prospeccion"],
    "odoo": ["cuentas_por_cobrar", "directorio_clientes", "catalogo_productos", "compras"],
    "shopify": ["cuentas_por_cobrar", "catalogo_productos", "directorio_clientes"],
    "woocommerce": ["cuentas_por_cobrar", "catalogo_productos"],
    "belvo": ["confirmacion_pago"],
    "stripe": ["confirmacion_pago"],
    # Pasarelas de cobro: confirman el pago Y generan el link que el ayudante manda.
    "mercadopago": ["confirmacion_pago", "link_de_pago"],
    "clip": ["confirmacion_pago", "link_de_pago"],
    "conekta": ["confirmacion_pago", "link_de_pago"],
    "sat": ["cfdi", "cuentas_por_cobrar"],
    "facturama": ["cfdi"],
    "facturapi": ["cfdi"],
    "googlecalendar": ["agenda"],
    "hubspot": ["directorio_clientes", "prospeccion"],
    "denue": ["prospeccion"],
    "slack": ["avisos_equipo"],
    # Google Sheets: una hoja mapeada por tipo (facturas/clientes/productos) cae a
    # cartera, directorio o catálogo. El motor ingiere el tipo declarado; declara las
    # tres porque el camino de lectura de cada una ya está cableado.
    "google_sheets": ["cuentas_por_cobrar", "directorio_clientes", "catalogo_productos"],
    # Mercado Libre: ventas por cobrar, catálogo (publicaciones) y compradores.
    "mercadolibre": ["cuentas_por_cobrar", "catalogo_productos", "directorio_clientes"],
    # Llamadas de voz (Twilio): un canal más para alcanzar al cliente (voz por teléfono).
    "twilio_voz": ["mensajeria"],
    # Generación de imágenes: el motor visual de la plantilla de Contenido (fal/OpenAI/self-host).
    "image_gen": ["generacion_contenido"],
}

# --- Una sola fuente de verdad para "qué corre solo hoy" --------------------
# Lectura realmente CABLEADA: el motor jala de aquí vía `sync_fuentes` (cada entrada
# tiene su lector real en sync.py: sync_directorio/sync_catalogo/sync_pedidos/sync_odoo/
# sync_compras/sync_prospeccion/sync_agenda/sync_cfdi). Sumar una capacidad = sumar su
# lector y registrarlo aquí; nada más lo declara.
_LECTURA_CABLEADA: dict[str, set[str]] = {
    "shopify": {"cuentas_por_cobrar", "catalogo_productos", "directorio_clientes"},
    "woocommerce": {"cuentas_por_cobrar", "catalogo_productos"},
    # Google Sheets: lectura cableada vía sync_google_sheets (reusa los lectores custom).
    "google_sheets": {"cuentas_por_cobrar", "directorio_clientes", "catalogo_productos"},
    # Mercado Libre: lectura cableada en sync_pedidos/sync_catalogo/sync_directorio.
    "mercadolibre": {"cuentas_por_cobrar", "catalogo_productos", "directorio_clientes"},
    "odoo": {"cuentas_por_cobrar", "catalogo_productos", "directorio_clientes", "compras"},
    "sat": {"cfdi", "cuentas_por_cobrar"},
    "hubspot": {"directorio_clientes", "prospeccion"},
    "denue": {"prospeccion"},
    "googlecalendar": {"agenda"},
    "facturama": {"cfdi"},
    "facturapi": {"cfdi"},
}

# Flujos vivos que NO son lectura de sync: los canales (WhatsApp y correo: entra/sale),
# la confirmación de pagos (banco/pasarela) y los avisos internos que SALEN a Slack.
# Aparte porque _lee_en_vivo solo habla de LECTURA.
_NON_READ_LIVE: set[tuple[str, str]] = {
    ("whatsapp", "mensajeria"),
    # Canal oficial: envío/inbound cableados al worker y al webhook. El semáforo
    # 'verified' (Probar conexión) es el que dice si YA se verificó contra Meta.
    ("whatsapp_cloud", "mensajeria"),
    # Correo: lectura IMAP en la corrida (engine/correo.sync_correo) + envío SMTP en
    # el worker; probado con fakes y servidor SMTP local — 'Probar conexión' verifica
    # contra el buzón real del negocio.
    ("email", "mensajeria"),
    ("belvo", "confirmacion_pago"),
    ("stripe", "confirmacion_pago"),
    # Pasarelas de cobro: la confirmación está cableada a detectar_pagos y el link a
    # POST /v1/cobro/link. El semáforo 'verified' (Probar conexión) confirma la credencial.
    ("mercadopago", "confirmacion_pago"),
    ("mercadopago", "link_de_pago"),
    ("clip", "confirmacion_pago"),
    ("clip", "link_de_pago"),
    ("conekta", "confirmacion_pago"),
    ("conekta", "link_de_pago"),
    # Avisos internos cableados: el resumen diario y el aviso de tope de IA salen por
    # aviso_al_equipo (worker) si el tenant conectó Slack. El semáforo 'verified'
    # (Probar conexión = auth.test) dice si ya se verificó contra Slack.
    ("slack", "avisos_equipo"),
    # Llamadas de voz: el envío (colocar la llamada) está cableado al worker y el
    # resultado (contestó/no contestó) al webhook de StatusCallback. El semáforo
    # 'verified' (Probar conexión) dice si ya se verificó contra la cuenta de Twilio.
    ("twilio_voz", "mensajeria"),
    # Generación de imágenes: la generación está cableada (connectors/image_gen), es una
    # ACCIÓN (no lectura). El semáforo 'verified' (Probar conexión) confirma la credencial.
    ("image_gen", "generacion_contenido"),
}


def _lee_en_vivo(src: str, cap: str) -> bool:
    """¿La LECTURA de esta capacidad ya corre sola hoy para esta fuente?"""
    if src == "excel":
        return True  # el importador universal entiende cualquier hoja
    return cap in _LECTURA_CABLEADA.get(src, set())


def _cap_is_live(src: str, cap: str) -> bool:
    """Única definición de 'este par (fuente, capacidad) ya corre solo hoy': lectura
    cableada o un flujo vivo que no es lectura (canal / confirmación de pago)."""
    return _lee_en_vivo(src, cap) or (src, cap) in _NON_READ_LIVE


# SOURCE_CAPS mantiene la forma histórica (lista de (capacidad, live)) que consumen el
# mapa, el detalle y la validación de selección — pero el `live` ya no se declara a mano:
# se DERIVA, así no puede volver a contradecir a _LECTURA_CABLEADA.
SOURCE_CAPS: dict[str, list[tuple[str, bool]]] = {
    src: [(cap, _cap_is_live(src, cap)) for cap in caps]
    for src, caps in _SOURCE_PROVIDES.items()
}

# El `live` a nivel conector (badge del catálogo y del detalle) se deriva igual: un
# conector está vivo si alguna de sus capacidades corre hoy. Evita que el detalle diga
# "Por conectar" mientras el mapa lo pinta activo.
for _item in CATALOG:
    _item["live"] = any(live for _, live in SOURCE_CAPS.get(_item["key"], []))

# Qué capacidades necesita cada aiudante por su rol. Esto es LO ÚNICO que se
# edita al sumar un agente; los sistemas a los que llega se derivan solos.
AGENT_CAPS: dict[str, list[str]] = {
    "mariana": ["cuentas_por_cobrar", "mensajeria", "confirmacion_pago"],
    "carlos": ["catalogo_productos", "directorio_clientes", "cuentas_por_cobrar", "mensajeria"],
    "lupita": ["cfdi", "expedientes", "mensajeria"],
    "valeria": ["agenda", "mensajeria"],
    "diego": ["confirmacion_pago", "cfdi", "cuentas_por_cobrar"],
    "roberto": ["catalogo_productos", "compras", "directorio_clientes"],
    "memo": ["avisos_equipo"],
    "sofia": ["prospeccion", "directorio_clientes", "mensajeria"],
}

# (name, role). El nombre VISIBLE es el ROL: los nombres de persona
# (Mariana/Carlos/Lupita…) se retiraron de la superficie del producto. El slug
# interno se conserva (el front lo usa como key y para la apariencia curada).
AGENT_META: dict[str, tuple[str, str]] = {
    "mariana": ("Cobranza", "Cobranza"),
    "carlos": ("Ventas", "Ventas"),
    "lupita": ("Legal y fiscal", "Legal y fiscal"),
    "valeria": ("Recepción", "Recepción"),
    "diego": ("Conciliación", "Conciliación"),
    "roberto": ("Compras", "Compras"),
    "memo": ("Contenido", "Contenido"),
    "sofia": ("Prospección", "Prospección"),
}

# Índice inverso: qué fuentes proveen cada capacidad, y si la capacidad ya
# está viva en algún lado (al menos una fuente la corre hoy).
_CAP_PROVIDERS: dict[str, list[str]] = {}
_CAP_LIVE: dict[str, bool] = {cap: False for cap in CAPABILITIES}
for _src, _caps in SOURCE_CAPS.items():
    for _cap, _live in _caps:
        _CAP_PROVIDERS.setdefault(_cap, []).append(_src)
        if _live:
            _CAP_LIVE[_cap] = True


def _provides(system: str) -> list[dict]:
    """Capacidades que provee una fuente, con su estado real (live por capacidad)."""
    return [
        {"cap": cap, "label": CAPABILITIES[cap]["label"], "live": live}
        for cap, live in SOURCE_CAPS.get(system, [])
        if cap in CAPABILITIES
    ]


_CATALOG_BY_KEY = {item["key"]: item for item in CATALOG}


def fuentes_de_capacidad(cap: str) -> list[dict]:
    """Las fuentes que PUEDEN alimentar una capacidad (de dónde puede leer una
    aiudita), con su logo y si su lectura ya corre hoy. Las posibles salen de
    SOURCE_CAPS (la misma fuente de verdad que el mapa, para no desincronizar); el
    `live` mide lectura cableada real (ver `_LECTURA_CABLEADA`), no participación.
    Las vivas van primero."""
    out: list[dict] = []
    for src in _CAP_PROVIDERS.get(cap, []):
        item = _CATALOG_BY_KEY.get(src)
        if item is None:
            continue
        out.append(
            {
                "key": src,
                "name": item["name"],
                "logo": item["logo"],
                "color": item["color"],
                "live": _lee_en_vivo(src, cap),
            }
        )
    out.sort(key=lambda f: (not f["live"], f["name"]))
    # Fallback CUA: para capacidades sin conector API, el dueño puede elegir que un
    # Computer Use Agent opere el portal (SAT, banca, tribunal). Va al final, marcado
    # experimental: hoy no ejecuta en local (falta el backend), pero es una elección real
    # que el motor enruta al lector CUA. Ver aiuda_core.cua.fallback.
    from aiuda_core.cua.fallback import CUA_FUENTE, capacidad_tiene_cua

    if capacidad_tiene_cua(cap):
        out.append(
            {
                "key": CUA_FUENTE,
                "name": "CUA (experimental)",
                "logo": "",
                "color": "#5B6B7A",
                "live": False,
                "experimental": True,
            }
        )
    return out


def fuente_default(cap: str) -> str | None:
    """La fuente que el motor usa hoy para esa capacidad: la primera viva. Si
    ninguna lee en vivo, la primera posible (queda 'por conectar' hasta cablearla)."""
    fuentes = fuentes_de_capacidad(cap)
    return fuentes[0]["key"] if fuentes else None


def fuente_valida(cap: str, key: str) -> bool:
    return any(f["key"] == key for f in fuentes_de_capacidad(cap))


def fuentes_preferidas(db, tenant: Tenant) -> dict[str, str]:
    """capacidad -> fuente elegida EXPLÍCITAMENTE por algún ayudante del tenant.

    Es lo que hace real "de dónde lee": el motor de sync la respeta por capacidad.
    Solo cuenta como elección lo que DIFIERE del default (la primera fuente viva): al
    crear una aiudita su `_fuente` se autollena al default, y eso NO debe suprimir a las
    demás (si no, elegir Excel por defecto apagaría el Odoo recién conectado). Si dos
    ayudantes eligen distinto para la misma capacidad, gana el más antiguo (mismo criterio
    que resolve.py)."""
    from aiuda_core.aiuditas import aiudita_por_id

    prefs: dict[str, str] = {}
    rows = db.scalars(
        select(Ayudante).where(Ayudante.tenant_id == tenant.id).order_by(Ayudante.created_at)
    ).all()
    for a in rows:
        for aid, cfg in (a.aiuditas or {}).items():
            spec = aiudita_por_id(aid)
            if spec is None or not spec.capacidad or spec.capacidad in prefs:
                continue
            fuente = cfg.get("_fuente") if isinstance(cfg, dict) else None
            if isinstance(fuente, str) and fuente and fuente != fuente_default(spec.capacidad):
                prefs[spec.capacidad] = fuente
    return prefs


def _agent_systems(slug: str) -> list[str]:
    """Sistemas a los que llega un agente = fuentes que proveen alguna de las
    capacidades que necesita. Derivado, no hardcodeado."""
    seen: list[str] = []
    for cap in AGENT_CAPS.get(slug, []):
        for src in _CAP_PROVIDERS.get(cap, []):
            if src in CATALOG_KEYS and src not in seen:
                seen.append(src)
    return seen


# Se deriva AGENT_SYSTEMS desde la capa de capacidades para no romper a quien
# lo consume (mapas, endpoints). Ya no se mantiene a mano.
AGENT_SYSTEMS: dict[str, list[str]] = {slug: _agent_systems(slug) for slug in AGENT_CAPS}


def _capabilities_overview(connected: set[str]) -> list[dict]:
    """Catálogo de capacidades con su estado: si ya está viva en algún lado y
    si el tenant tiene una fuente conectada que la cumpla."""
    out = []
    for cap, meta in CAPABILITIES.items():
        providers = [s for s in _CAP_PROVIDERS.get(cap, []) if s in CATALOG_KEYS]
        out.append(
            {
                "key": cap,
                "label": meta["label"],
                "desc": meta["desc"],
                "live": _CAP_LIVE.get(cap, False),
                "providers": providers,
                "connected": any(s in connected for s in providers),
            }
        )
    return out


def _agent_caps_detail(slug: str, connected: set[str]) -> tuple[list[str], list[str]]:
    """Devuelve (needs, gaps) de un agente. Un gap es una capacidad que el
    agente necesita y que ninguna fuente conectada le cumple todavía: eso es
    lo que dispara "conecta algo" o "solicita aiuda" en el mapa."""
    needs = AGENT_CAPS.get(slug, [])
    gaps = [
        cap
        for cap in needs
        if not any(s in connected for s in _CAP_PROVIDERS.get(cap, []) if s in CATALOG_KEYS)
    ]
    return needs, gaps


def _active_systems(db, tenant: Tenant) -> set[str]:
    """Sistemas que ya tienen datos reales fluyendo (source + presence)."""
    active: set[str] = set()

    invoices = db.scalars(select(Invoice).where(Invoice.tenant_id == tenant.id)).all()
    for inv in invoices:
        if inv.source:
            active.add(inv.source)
        for k in (inv.presence or {}):
            active.add(k)

    customers = db.scalars(select(Customer).where(Customer.tenant_id == tenant.id)).all()
    for c in customers:
        for k in (c.presence or {}):
            active.add(k)

    # WhatsApp cuenta como conectado si HAY conversaciones (llegaron mensajes de
    # verdad) o si el dueño configuró el canal. NO por `evolution_instance`: ese
    # identificador se genera al crear el workspace, así que una instalación
    # recién hecha decía "1 fuente conectada" sin que nadie hubiera conectado
    # nada. Una fuente está conectada cuando puede leer o escribir algo, punto.
    has_convos = db.scalar(
        select(Conversation.id).where(Conversation.tenant_id == tenant.id).limit(1)
    )
    canal_wa = ((tenant.config or {}).get("integrations") or {}).get("whatsapp")
    if has_convos or canal_wa:
        active.add("whatsapp")

    # csv cuenta como excel
    if "csv" in active:
        active.add("excel")
    if db.scalar(
        select(CfdiBoveda.id).where(CfdiBoveda.tenant_id == tenant.id).limit(1)
    ):
        active.add("sat")
    return active


def _saved_int(tenant: Tenant, key: str) -> dict | None:
    """Config legada que el dueño guardó en texto plano (solo fallback de
    transición; lo nuevo vive cifrado en IntegrationCredential)."""
    return ((tenant.config or {}).get("integrations") or {}).get(key)


def _is_configured(db, tenant: Tenant, key: str) -> bool:
    """¿El dueño ya capturó credenciales? Fila cifrada o config legada en claro."""
    if key == "sat":
        return bool(
            (tenant.config or {}).get("sat_empresas")
            or db.scalar(
                select(IntegrationCredential.id).where(
                    IntegrationCredential.tenant_id == tenant.id,
                    IntegrationCredential.provider.like("sat_efirma:%"),
                ).limit(1)
            )
        )
    return cred.has_credential(db, tenant.id, key) or _saved_int(tenant, key) is not None


def _is_connected(db, system: str, tenant: Tenant, active: set[str]) -> bool:
    cfg = tenant.config or {}
    if system in active:
        return True
    # Señal nueva: credencial cifrada por tenant. Los fallbacks de abajo se
    # conservan para no regresionar self-host (settings.* globales) ni el legado.
    if cred.has_credential(db, tenant.id, system):
        return True
    if _saved_int(tenant, system):
        return True
    if system == "sat":
        return _is_configured(db, tenant, "sat")
    if system == "odoo":
        return bool((cfg.get("odoo") or {}).get("url"))
    if system == "belvo":
        return bool(cfg.get("belvo_link_id") or settings.belvo_secret_id)
    if system == "stripe":
        return bool(settings.stripe_api_key)
    if system == "shopify":
        return bool(settings.shopify_access_token)
    if system == "woocommerce":
        return bool(settings.woocommerce_base_url)
    if system == "facturapi":
        return bool(settings.facturapi_api_key)
    if system == "facturama":
        return bool(settings.facturama_user)
    if system == "hubspot":
        return bool(settings.hubspot_token)
    if system == "slack":
        return bool(settings.slack_bot_token)
    if system == "googlecalendar":
        return bool(settings.google_calendar_token)
    if system == "denue":
        return bool(settings.denue_token)
    return False


def _verified_map(db, tenant_id: str) -> dict[str, dict]:
    """Último veredicto de la prueba de conexión por fuente (lo escribe /test).
    keyed por provider → {status, last_test_at, last_error}. Alimenta el semáforo."""
    rows = db.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.status != "disabled",
        )
    ).all()
    out = {
        r.provider: {
            "status": r.status,
            "last_test_at": r.last_test_at.isoformat() if r.last_test_at else None,
            "last_error": r.last_error,
        }
        for r in rows
    }
    sat_rows = [r for r in rows if r.provider.startswith("sat_efirma:")]
    if sat_rows:
        probadas = [r for r in sat_rows if r.last_test_at is not None]
        if probadas:
            ultima = max(probadas, key=lambda r: r.last_test_at)
            out["sat"] = {
                "status": ultima.status,
                "last_test_at": ultima.last_test_at.isoformat(),
                "last_error": ultima.last_error,
            }
    return out


@router.get("/v1/integrations")
def integrations_graph(tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Grafo de integraciones: aiuda al centro, sistemas alrededor, con su
    estado de conexión y dirección de flujo. Lo consume la vista de red."""
    active = _active_systems(db, tenant)
    connected_keys = {
        item["key"] for item in CATALOG if _is_connected(db, item["key"], tenant, active)
    }

    # Cuántas facturas trae cada fuente, para mostrar volumen en el nodo.
    counts: dict[str, int] = {}
    for inv in db.scalars(select(Invoice).where(Invoice.tenant_id == tenant.id)).all():
        if inv.source:
            counts[inv.source] = counts.get(inv.source, 0) + 1
        for k in (inv.presence or {}):
            counts[k] = counts.get(k, 0) + 1
    counts["sat"] = len(
        db.scalars(
            select(CfdiBoveda.id).where(CfdiBoveda.tenant_id == tenant.id)
        ).all()
    )

    # TODO el equipo en el mapa (activos o no): cada agente trae si está
    # activado, sus capacidades, los sistemas a los que llega (derivados) y los
    # huecos (capacidades sin fuente conectada). Mostrar sólo los activos hacía
    # que el mapa contradijera al resto de la consola (sidebar, /asistentes).
    active_agents = set((tenant.config or {}).get("active_agents") or ["mariana"])
    agents = []
    for slug in AGENT_META:
        name, role = AGENT_META[slug]
        uses = [k for k in AGENT_SYSTEMS.get(slug, []) if k in CATALOG_KEYS]
        needs, gaps = _agent_caps_detail(slug, connected_keys)
        agents.append(
            {
                "slug": slug,
                "name": name,
                "role": role,
                "avatar": f"/asistentes/{slug}.png",
                "active": slug in active_agents,
                "systems": uses,
                "needs": needs,
                "gaps": gaps,
            }
        )

    status_map = _verified_map(db, tenant.id)
    systems = []
    for item in CATALOG:
        connected = item["key"] in connected_keys
        configured = _is_configured(db, tenant, item["key"])
        st = status_map.get(item["key"])
        # Semáforo: ok = la última prueba pasó; error = falló (con motivo); untested =
        # configurado pero sin probar aún; None = ni configurado.
        if not configured:
            verified = None
        elif st and st.get("status") == "connected":
            verified = "ok"
        elif st and st.get("status") == "error":
            verified = "error"
        else:
            verified = "untested"
        n = counts.get(item["key"], 0)
        # "Lo usa tu equipo": sólo agentes ACTIVOS (los que de verdad lo usan hoy).
        used_by = [a["slug"] for a in agents if a["active"] and item["key"] in a["systems"]]
        systems.append(
            {
                **item,
                "connected": connected,
                "configured": configured,
                "verified": verified,
                "last_test_at": (st or {}).get("last_test_at"),
                "last_error": (st or {}).get("last_error"),
                "records": n,
                "detail": f"{n} registros" if n else None,
                "agents": used_by,
                "provides": _provides(item["key"]),
            }
        )

    connected_count = sum(1 for s in systems if s["connected"])
    return {
        "business_name": tenant.name,
        "systems": systems,
        "agents": agents,
        "capabilities": _capabilities_overview(connected_keys),
        "connected_count": connected_count,
        "available_count": len(systems) - connected_count,
    }


@router.get("/v1/agents/{slug}/systems")
def agent_systems(slug: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Sistemas a los que llega un asistente: a cuáles ya está conectado y a
    cuáles se podría conectar. Funciona para cualquier agente (activo o no)."""
    if slug not in AGENT_META:
        raise HTTPException(status_code=404, detail="Agente desconocido.")
    active = _active_systems(db, tenant)
    connected_keys = {
        item["key"] for item in CATALOG if _is_connected(db, item["key"], tenant, active)
    }
    by_key = {item["key"]: item for item in CATALOG}
    name, role = AGENT_META[slug]
    needs, gaps = _agent_caps_detail(slug, connected_keys)
    systems = []
    for key in AGENT_SYSTEMS.get(slug, []):
        item = by_key.get(key)
        if not item:
            continue
        # Sólo las capacidades de esta fuente que este agente realmente usa.
        relevant = [p for p in _provides(key) if p["cap"] in needs]
        systems.append(
            {
                **item,
                "connected": key in connected_keys,
                "provides": relevant,
            }
        )

    # Capacidades del agente con qué fuente (conectada) las cumple.
    capabilities = []
    for cap in needs:
        providers = [s for s in _CAP_PROVIDERS.get(cap, []) if s in CATALOG_KEYS]
        capabilities.append(
            {
                "key": cap,
                "label": CAPABILITIES[cap]["label"],
                "desc": CAPABILITIES[cap]["desc"],
                "live": _CAP_LIVE.get(cap, False),
                "providers": providers,
                "connected": any(s in connected_keys for s in providers),
            }
        )

    return {
        "slug": slug,
        "name": name,
        "role": role,
        "avatar": f"/asistentes/{slug}.png",
        "systems": systems,
        "capabilities": capabilities,
        "needs": needs,
        "gaps": gaps,
        "connected_count": sum(1 for s in systems if s["connected"]),
    }


def _source_capabilities(tenant: Tenant, key: str) -> list[dict]:
    """Qué capacidades provee una fuente, con qué aiudante activo usa cada una y
    si el dueño la dejó prendida (para jalarla cuando se cablee la sync real).
    Las apagadas viven en config['integrations_caps'][key], aparte de las
    credenciales para no confundir el estado de 'conectado'."""
    active = set((tenant.config or {}).get("active_agents") or ["mariana"])
    disabled = set(((tenant.config or {}).get("integrations_caps") or {}).get(key) or [])
    out = []
    for cap, live in SOURCE_CAPS.get(key, []):
        if cap not in CAPABILITIES:
            continue
        agents = [
            {"slug": slug, "name": AGENT_META[slug][0], "avatar": f"/asistentes/{slug}.png"}
            for slug, caps in AGENT_CAPS.items()
            if cap in caps and slug in active and slug in AGENT_META
        ]
        out.append(
            {
                "cap": cap,
                "label": CAPABILITIES[cap]["label"],
                "desc": CAPABILITIES[cap]["desc"],
                "live": live,
                # Lo no-vivo no se puede prender aún; lo vivo, prendido salvo que se apague.
                "enabled": live and cap not in disabled,
                "toggleable": live,
                "agents": agents,
            }
        )
    return out


@router.get("/v1/integrations/{key}")
def integration_detail(key: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """Detalle de una fuente para su pantalla de configuración: qué hace, su
    estado y qué capacidades le da a tu equipo (con toggles)."""
    item = next((i for i in CATALOG if i["key"] == key), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Integración desconocida.")
    active = _active_systems(db, tenant)
    return {
        **item,
        "connected": _is_connected(db, key, tenant, active),
        "configured": _is_configured(db, tenant, key),
        "capabilities": _source_capabilities(tenant, key),
    }


class CapabilitiesBody(BaseModel):
    disabled: list[str]


@router.put("/v1/integrations/{key}/capabilities")
def set_capabilities(
    key: str,
    body: CapabilitiesBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Guarda qué capacidades de esta fuente quieres jalar (las apagadas)."""
    if key not in CATALOG_KEYS:
        raise HTTPException(status_code=404, detail="Integración desconocida.")
    valid = {c for c, live in SOURCE_CAPS.get(key, []) if live}
    disabled = [c for c in body.disabled if c in valid]
    cfg = dict(tenant.config or {})
    caps = dict(cfg.get("integrations_caps") or {})
    caps[key] = disabled
    cfg["integrations_caps"] = caps
    tenant.config = cfg
    db.add(tenant)
    db.flush()
    return {"key": key, "disabled": disabled}


# Qué fuente es dueña de cada tipo de objeto y a qué modelo de Odoo mapea (para el
# deep-link "Crear en la fuente"). aiuda no es el maestro: un objeto que vive en tu fuente
# se crea ALLÁ (como se edita allá), no como huérfano local.
_OBJETO_CAP_MODELO = {
    "clientes": ("directorio_clientes", "res.partner"),
    "productos": ("catalogo_productos", "product.template"),
    "facturas": ("cuentas_por_cobrar", "account.move"),
    # Agenda: hoy la proveen Excel y Google Calendar (sin deep-link de alta); el
    # modelo de Odoo queda declarado por si algún día provee la capacidad.
    "citas": ("agenda", "calendar.event"),
}


@router.get("/v1/objects/{tipo}/source")
def object_source(tipo: str, tenant: Tenant = Depends(get_tenant), db=Depends(get_db)):
    """De dónde nace un objeto nuevo. aiuda espeja tus fuentes; crear un registro que vive en
    tu fuente se hace ALLÁ (deep-link), no como huérfano en aiuda. Devuelve la fuente dueña
    conectada + la liga para crear uno nuevo en ella (hoy Odoo), o native=True si ninguna
    fuente externa lo posee (entonces aiuda es la fuente y el alta es aquí)."""
    entry = _OBJETO_CAP_MODELO.get(tipo)
    if entry is None:
        raise HTTPException(status_code=404, detail="Tipo de objeto desconocido.")
    cap, model = entry
    active = _active_systems(db, tenant)
    source = next(
        (f["key"] for f in fuentes_de_capacidad(cap) if _is_connected(db, f["key"], tenant, active)),
        None,
    )
    label = _CATALOG_BY_KEY[source]["name"] if source in _CATALOG_BY_KEY else None
    new_url = None
    if source == "odoo":
        creds = None
        try:
            creds = cred.get_credential(db, tenant.id, "odoo")
        except Exception:
            creds = None
        base = (creds or {}).get("url", "").rstrip("/") if creds else ""
        if base:
            new_url = f"{base}/odoo/{model}/new"
    return {
        "tipo": tipo,
        "source": source,
        "source_label": label,
        "new_url": new_url,  # solo Odoo hoy; otras fuentes se importan/suben
        "native": source is None,
    }


class IntegrationRequestBody(BaseModel):
    system: str
    reason: str | None = None


@router.post("/v1/integration-requests", status_code=201)
def request_integration(
    body: IntegrationRequestBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
):
    """Registra que un negocio quiere una integración que aún no existe. El
    equipo de aiuda las prioriza por demanda."""
    system = body.system.strip()
    if not system:
        raise HTTPException(status_code=422, detail="Dinos qué sistema te falta.")
    cfg = dict(tenant.config or {})
    reqs = list(cfg.get("integration_requests") or [])
    reqs.append({"system": system, "reason": (body.reason or "").strip()})
    cfg["integration_requests"] = reqs
    tenant.config = cfg
    db.add(tenant)
    db.flush()
    return {"ok": True, "system": system}


class IntegrationConfigBody(BaseModel):
    values: dict[str, str]


def _mask(values: dict) -> dict:
    """Devuelve la config con las credenciales ocultas (para mostrar sin filtrar)."""
    out = {}
    for k, v in values.items():
        if any(h in k.lower() for h in SECRET_HINT) and v:
            out[k] = "••••••"
        else:
            out[k] = v
    return out


@router.get("/v1/integrations/{key}/config")
def get_integration_config(
    key: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    if key not in CATALOG_KEYS:
        raise HTTPException(status_code=404, detail="Integración desconocida.")
    # Proveedores con secreto: lee de la fila cifrada. Los públicos en claro; los
    # secretos como '••••••' (su valor NUNCA sale). Si aún no hay fila, cae al
    # legado en texto plano (enmascarado).
    if key in cred.PROVIDERS:
        row = db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant.id,
                IntegrationCredential.provider == key,
                IntegrationCredential.status != "disabled",
            )
        )
        if row is not None:
            values = dict(row.public_config or {})
            try:
                stored = cred.read_stored(db, tenant.id, key) or {}
                present = {f for f in cred.secret_fields(key) if stored.get(f)}
            except Exception:
                # No se pudo descifrar (clave retirada): no filtramos, asumimos
                # presentes los secretos porque la fila existe.
                present = set(cred.secret_fields(key))
            for f in present:
                values[f] = "••••••"
            return {"key": key, "configured": True, "values": values}
    saved = _saved_int(tenant, key)
    return {"key": key, "configured": saved is not None, "values": _mask(saved or {})}


@router.put("/v1/integrations/{key}/config")
def save_integration_config(
    key: str,
    body: IntegrationConfigBody,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    actor=Depends(require_role("admin")),
):
    """Guarda la config de una integración. Para proveedores con secreto, cifra por
    tenant en IntegrationCredential (los secretos NUNCA en claro) y limpia el
    residuo legado. Los sin secreto (whatsapp/excel) siguen en tenant.config."""
    if key not in CATALOG_KEYS:
        raise HTTPException(status_code=404, detail="Integración desconocida.")

    if key in cred.PROVIDERS:
        # Conserva el secreto previo cuando llega el placeholder o no se reescribe.
        # Si NO se puede descifrar lo guardado (clave perdida/rotada) y el dueño no
        # reescribe un secreto, abortamos: re-cifrar sin él lo borraría para siempre.
        try:
            prev = cred.read_stored(db, tenant.id, key) or {}
            prev_readable = True
        except Exception:
            prev = {}
            prev_readable = False
        secrets = cred.secret_fields(key)
        final: dict = {}
        lost_secret = False
        for field in cred.all_fields(key):
            incoming = body.values.get(field)
            keep_prev = incoming is None or (field in secrets and incoming == "••••••")
            if keep_prev:
                if prev.get(field):
                    final[field] = prev[field]  # conserva lo previo (placeholder/omitido)
                elif field in secrets and not prev_readable:
                    lost_secret = True  # había/pudo haber un secreto ilegible: no lo pisamos
            elif incoming != "":
                final[field] = incoming
            # "" => el dueño lo borró: se omite
        if lost_secret:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No se pudieron leer las credenciales actuales para conservarlas "
                    "(revisa la clave de cifrado). Vuelve a capturar TODAS las "
                    "credenciales de esta integración para reemplazarlas."
                ),
            )
        cred.set_credential(db, tenant.id, key, final)
        # Fin del callejón en claro: borra el residuo legado de tenant.config.
        cfg = dict(tenant.config or {})
        integrations = dict(cfg.get("integrations") or {})
        if integrations.pop(key, None) is not None:
            cfg["integrations"] = integrations
            tenant.config = cfg
            db.add(tenant)
        db.flush()
        audit.record(
            db,
            tenant_id=tenant.id,
            action="integration.update",
            entity_type="integration",
            entity_id=key,
            principal=actor,  # nunca el secreto, solo qué proveedor se tocó
        )
        return {"key": key, "configured": True, "connected": True}

    # Proveedores sin secreto en el registro: flujo legado en tenant.config, EN CLARO.
    #
    # Falla cerrada: si llega algo con pinta de secreto por esta vía, se rechaza en vez
    # de guardarlo sin cifrar. El bug que esto cierra era silencioso y sistémico: basta
    # con que una llave del CATALOG no exista en cred.PROVIDERS para caer aquí, y el
    # front inventa un campo "token" secreto para toda llave que no declare los suyos
    # (fieldsFor en web/lib/integration-fields.ts). Así, `whatsapp`, `excel` y `sat`
    # pedían un secreto y lo dejaban en texto plano en reposo mientras el resto iba
    # cifrado con Fernet. La respuesta correcta a "esta fuente sí tiene secreto" es
    # darle su entrada en PROVIDERS, no ensanchar esta rama.
    ofensivos = sorted(
        k for k, v in body.values.items() if v and any(h in k.lower() for h in SECRET_HINT)
    )
    if ofensivos:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{key}' no tiene registro de cifrado, así que no puede guardar "
                f"credenciales ({', '.join(ofensivos)}). Guardarlas aquí las dejaría en "
                "texto plano. Es un error de configuración de aiuda, no tuyo: repórtalo."
            ),
        )

    cfg = dict(tenant.config or {})
    integrations = dict(cfg.get("integrations") or {})
    # Reemplazo completo: cualquier secreto en claro que hubiera quedado de una versión
    # anterior en ESTA llave se va con la sobreescritura. Los de otras llaves los limpia
    # `purgar_secretos_en_claro`, que corre al arrancar.
    clean = {k: v for k, v in body.values.items() if v and v != "••••••"}
    integrations[key] = clean
    cfg["integrations"] = integrations
    tenant.config = cfg
    db.add(tenant)
    db.flush()
    return {"key": key, "configured": True, "connected": True}


@router.delete("/v1/integrations/{key}/config")
def disconnect_integration(
    key: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    # Borra la fila cifrada (si existe) y limpia el residuo legado en claro.
    if key in cred.PROVIDERS:
        row = db.scalar(
            select(IntegrationCredential).where(
                IntegrationCredential.tenant_id == tenant.id,
                IntegrationCredential.provider == key,
            )
        )
        if row is not None:
            db.delete(row)
    cfg = dict(tenant.config or {})
    integrations = dict(cfg.get("integrations") or {})
    integrations.pop(key, None)
    cfg["integrations"] = integrations
    tenant.config = cfg
    db.add(tenant)
    db.flush()
    return {"key": key, "configured": False, "connected": False}


def _test_odoo(creds: dict) -> dict:
    """Prueba real contra Odoo con las credenciales del negocio."""
    missing = [f for f in ("url", "db", "username", "api_key") if not creds.get(f)]
    if missing:
        labels = {"url": "URL", "db": "base de datos", "username": "usuario", "api_key": "API key"}
        return {"ok": False, "message": f"Faltan datos: {', '.join(labels[m] for m in missing)}."}
    from aiuda_core.connectors.odoo import OdooConnector

    try:
        conn = OdooConnector(creds["url"], creds["db"], creds["username"], creds["api_key"])
        info = conn.test_connection()
        # Etiquetas honestas: "Contactos" son todos los res.partner (señal de
        # vida); lo que el sync de verdad lee son los clientes (customer_rank>0)
        # y las facturas con saldo. Antes decía "Clientes: 25" cuando se leen 3.
        return {
            "ok": True,
            "message": f"Conectado a Odoo {info['version']}.",
            "details": {
                "Contactos en Odoo": info["partners"],
                "Clientes que se leen": info["clientes"],
                "Facturas por cobrar": info["invoices"],
            },
        }
    except Exception as exc:  # red, credenciales, db inexistente, etc.
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_email(creds: dict) -> dict:
    """Prueba real de la cuenta de correo: login IMAP y, si hay SMTP configurado,
    conexión + AUTH SMTP (sin enviar nada). Sirve para IMAP genérico, Gmail y
    Outlook con contraseña de aplicación — la vía completa hoy. Con auth OAuth
    guardada responde honesto: aún no está cableada."""
    labels = {"imap_host": "servidor IMAP", "email": "correo", "password": "contraseña"}
    missing = [labels[f] for f in ("imap_host", "email", "password") if not creds.get(f)]
    if missing:
        return {"ok": False, "message": f"Faltan datos: {', '.join(missing)}."}
    from aiuda_core.connectors.correo import CorreoClient, CorreoNoDisponible

    host = creds["imap_host"]
    client = CorreoClient(
        email=creds["email"],
        password=creds["password"],
        imap_host=host,
        imap_port=creds.get("imap_port") or 993,
        smtp_host=creds.get("smtp_host", ""),
        smtp_port=creds.get("smtp_port") or 587,
        auth_method=creds.get("auth_method") or "password",
        timeout=15,
    )
    try:
        detalles = client.verificar()
    except CorreoNoDisponible as exc:  # OAuth guardado pero no cableado: honesto
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # red, credenciales, IMAP/SMTP apagado, etc.
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}
    details = {"Buzones": detalles.get("buzones", 0)}
    details["Envío (SMTP)"] = (
        "listo" if detalles.get("smtp") == "listo"
        else "sin configurar: captura el servidor SMTP para poder responder"
    )
    return {
        "ok": True,
        "message": f"Conectado a {host} como {creds['email']}.",
        "details": details,
    }


def _test_denue(creds: dict) -> dict:
    """Prueba real contra la API pública del INEGI: una búsqueda mínima ('todos',
    centro de CDMX, 500 m) con el token del negocio. Un token inválido llega como
    RemoteProtocolError (INEGI responde 'HTTP/1.1 000'); se reporta legible."""
    if not creds.get("token"):
        return {
            "ok": False,
            "message": "Falta el token (gratuito en inegi.org.mx/app/api/denue).",
        }
    from aiuda_core.connectors.denue import DenueClient

    try:
        negocios = DenueClient(token=creds["token"]).buscar("todos", 19.4326, -99.1332, 500)
        return {
            "ok": True,
            "message": "Conectado al DENUE del INEGI.",
            "details": {"Negocios en la muestra": len(negocios)},
        }
    except Exception as exc:  # token inválido, red, respuesta rara
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_whatsapp_cloud(creds: dict) -> dict:
    """Prueba real contra la Graph API de Meta (lee los datos del número, no envía).
    La lógica vive en el conector (aiuda_core.connectors.waba.test_connection)."""
    from aiuda_core.connectors.waba import test_connection

    return test_connection(creds)


def _test_slack(creds: dict) -> dict:
    """Prueba real contra Slack: auth.test con el bot token (no publica nada).
    Exige también el canal de avisos: sin él, los avisos no tienen a dónde salir."""
    labels = {"bot_token": "bot token (xoxb-…)", "channel": "canal de avisos (p.ej. #cobranza)"}
    missing = [labels[f] for f in ("bot_token", "channel") if not creds.get(f)]
    if missing:
        return {"ok": False, "message": f"Faltan datos: {', '.join(missing)}."}
    from aiuda_core.connectors.slack import SlackClient

    try:
        info = SlackClient(bot_token=creds["bot_token"]).test_connection()
        return {
            "ok": True,
            "message": f"Conectado al workspace {info.get('team') or 'de Slack'}.",
            "details": {
                "Bot": info.get("user") or "",
                "Canal de avisos": creds["channel"],
            },
        }
    except Exception as exc:  # token inválido, red, app desinstalada
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_mercadolibre(creds: dict) -> dict:
    """Prueba real contra la API oficial de Mercado Libre: /users/me (nickname) y el
    conteo de publicaciones del vendedor. Verifica el access token o, si caducó, el
    refresco con client_id/client_secret/refresh_token."""
    if not creds.get("access_token") and not creds.get("refresh_token"):
        return {
            "ok": False,
            "message": "Falta el access token (o el refresh token con client_id y client_secret).",
        }
    from aiuda_core.connectors.mercadolibre import MercadoLibreClient

    try:
        info = MercadoLibreClient(**cred.ctor_kwargs("mercadolibre", creds)).test_connection()
        return {
            "ok": True,
            "message": f"Conectado como {info.get('nickname') or 'vendedor'}.",
            "details": {"Publicaciones": info.get("items", 0), "ID de vendedor": info.get("seller_id")},
        }
    except Exception as exc:  # token vencido sin refresh, credenciales malas, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_google_sheets(creds: dict) -> dict:
    """Prueba real contra la Sheets API v4: lee la metadata de la hoja (título y
    pestañas) con la API key y, si hay rango, cuenta sus filas. Un 403 típico =
    la hoja no está compartida como 'cualquiera con el enlace · lector'."""
    missing = [
        {"api_key": "API key de Google", "spreadsheet_id": "ID de la hoja"}[f]
        for f in ("api_key", "spreadsheet_id")
        if not creds.get(f)
    ]
    if missing:
        return {"ok": False, "message": f"Faltan datos: {', '.join(missing)}."}
    from aiuda_core.connectors.google_sheets import GoogleSheetsClient

    try:
        info = GoogleSheetsClient(api_key=creds["api_key"]).test_connection(
            creds["spreadsheet_id"], creds.get("sheet_range") or ""
        )
        details = {"Pestañas": info["sheets"]}
        if creds.get("sheet_range"):
            details["Filas en el rango"] = info["rows"]
        return {
            "ok": True,
            "message": f"Conectado a la hoja '{info['title'] or 'sin título'}'.",
            "details": details,
        }
    except Exception as exc:  # API key inválida, hoja no compartida, ID malo, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_twilio_voz(creds: dict) -> dict:
    """Prueba real contra la API de Twilio: lee la cuenta y sus números comprados con
    las credenciales del negocio (no llama a ningún cliente). La lógica vive en el
    conector (aiuda_core.connectors.twilio_voz.test_connection)."""
    from aiuda_core.connectors.twilio_voz import test_connection

    return test_connection(creds)


def _test_image_gen(creds: dict) -> dict:
    """Prueba real del proveedor de imagen: openai/custom listan modelos (sin costo);
    fal genera una imagen mínima (fracción de centavo). Lógica en el conector."""
    from aiuda_core.connectors.image_gen import test_connection

    return test_connection(creds)


def _test_mercadopago(creds: dict) -> dict:
    """Prueba real contra Mercado Pago (/users/me): valida el access token y cuenta pagos
    recientes. No cobra ni mueve dinero."""
    if not creds.get("access_token"):
        return {"ok": False, "message": "Falta el access token de Mercado Pago."}
    from aiuda_core.connectors.mercadopago import MercadoPagoClient

    try:
        info = MercadoPagoClient(**cred.ctor_kwargs("mercadopago", creds)).test_connection()
        return {
            "ok": True,
            "message": f"Conectado como {info.get('cuenta') or 'tu cuenta'}.",
            "details": {"Pagos recientes": info.get("pagos_recientes", 0)},
        }
    except Exception as exc:  # token inválido, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_clip(creds: dict) -> dict:
    """Prueba real contra Clip: valida la API key pidiendo una página mínima de pagos."""
    if not creds.get("api_key"):
        return {"ok": False, "message": "Falta la API key de Clip."}
    from aiuda_core.connectors.clip import ClipClient

    try:
        info = ClipClient(**cred.ctor_kwargs("clip", creds)).test_connection()
        return {"ok": True, "message": "Conectado a Clip.", "details": {"Pagos visibles": info.get("pagos_visibles", 0)}}
    except Exception as exc:  # API key inválida, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_conekta(creds: dict) -> dict:
    """Prueba real contra Conekta: valida la private key pidiendo una orden (limit=1)."""
    if not creds.get("api_key"):
        return {"ok": False, "message": "Falta la private key de Conekta."}
    from aiuda_core.connectors.conekta import ConektaClient

    try:
        info = ConektaClient(**cred.ctor_kwargs("conekta", creds)).test_connection()
        return {"ok": True, "message": "Conectado a Conekta.", "details": {"Órdenes visibles": info.get("ordenes_visibles", 0)}}
    except Exception as exc:  # private key inválida, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_shopify(creds: dict) -> dict:
    """Prueba real contra Shopify (shop.json): valida el access token y reporta
    catálogo y pedidos sin pagar, sin descargar los pedidos."""
    if not creds.get("access_token") or not creds.get("store_domain"):
        return {"ok": False, "message": "Faltan el dominio de la tienda y el access token."}
    from aiuda_core.connectors.shopify import ShopifyClient

    try:
        info = ShopifyClient(**cred.ctor_kwargs("shopify", creds)).test_connection()
        return {
            "ok": True,
            "message": f"Conectado a {info.get('shop') or 'tu tienda'}.",
            "details": {
                "Productos": info.get("productos", 0),
                "Pedidos sin pagar": info.get("pedidos_sin_pagar", 0),
            },
        }
    except Exception as exc:  # token inválido, dominio malo, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_woocommerce(creds: dict) -> dict:
    """Prueba real contra WooCommerce (wc/v3): valida las llaves (Basic) y reporta
    catálogo y pedidos pendientes por el encabezado X-WP-Total, sin traer todo."""
    if not (creds.get("consumer_key") and creds.get("consumer_secret") and creds.get("base_url")):
        return {"ok": False, "message": "Faltan la URL de la tienda y las llaves (consumer key y secret)."}
    from aiuda_core.connectors.woocommerce import WooCommerceClient

    try:
        info = WooCommerceClient(**cred.ctor_kwargs("woocommerce", creds)).test_connection()
        return {
            "ok": True,
            "message": "Conectado a tu tienda WooCommerce.",
            "details": {
                "Productos": info.get("productos", 0),
                "Pedidos pendientes": info.get("pedidos_pendientes", 0),
            },
        }
    except Exception as exc:  # llaves inválidas, URL mala, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_hubspot(creds: dict) -> dict:
    """Prueba real contra HubSpot (search, limit=1): valida el token de la app
    privada y devuelve los totales de contactos y oportunidades."""
    if not creds.get("token"):
        return {"ok": False, "message": "Falta el token de la app privada de HubSpot."}
    from aiuda_core.connectors.hubspot import HubSpotClient

    try:
        info = HubSpotClient(**cred.ctor_kwargs("hubspot", creds)).test_connection()
        return {
            "ok": True,
            "message": "Conectado a tu cuenta de HubSpot.",
            "details": {
                "Contactos": info.get("contactos", 0),
                "Oportunidades": info.get("oportunidades", 0),
            },
        }
    except Exception as exc:  # token inválido, permisos faltantes, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_googlecalendar(creds: dict) -> dict:
    """Prueba real contra Google Calendar (calendarList): valida el token y confirma
    que el calendario configurado esté visible (si no, la agenda quedaría vacía)."""
    if not creds.get("token"):
        return {"ok": False, "message": "Falta el token de acceso de Google Calendar."}
    from aiuda_core.connectors.gcal import GoogleCalendarClient

    try:
        info = GoogleCalendarClient(**cred.ctor_kwargs("googlecalendar", creds)).test_connection()
        if not info.get("configurado_visible"):
            return {
                "ok": False,
                "message": (
                    f"El token sirve, pero el calendario '{info.get('calendario_configurado')}' "
                    "no está entre los visibles. Revisa el ID o los permisos."
                ),
                "details": {"Calendarios visibles": info.get("calendarios", 0)},
            }
        return {
            "ok": True,
            "message": "Conectado a tu Google Calendar.",
            "details": {
                "Calendarios visibles": info.get("calendarios", 0),
                "Calendario configurado": info.get("calendario_configurado"),
            },
        }
    except Exception as exc:  # token inválido/expirado, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_facturama(creds: dict) -> dict:
    """Prueba real contra Facturama: valida usuario y contraseña (Basic) pidiendo la
    primera página de CFDI emitidos (muestra, sin descargar XML)."""
    if not (creds.get("user") and creds.get("password")):
        return {"ok": False, "message": "Faltan el usuario y la contraseña de Facturama."}
    from aiuda_core.connectors.facturama import FacturamaClient

    try:
        info = FacturamaClient(**cred.ctor_kwargs("facturama", creds)).test_connection()
        return {
            "ok": True,
            "message": "Conectado a Facturama.",
            "details": {"CFDI en la muestra": info.get("cfdi_muestra", 0)},
        }
    except Exception as exc:  # credenciales malas, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_facturapi(creds: dict) -> dict:
    """Prueba real contra Facturapi: valida la API key pidiendo una factura (limit=1)
    y lee el total de la paginación."""
    if not creds.get("api_key"):
        return {"ok": False, "message": "Falta la API key de Facturapi."}
    from aiuda_core.connectors.facturapi import FacturapiClient

    try:
        info = FacturapiClient(**cred.ctor_kwargs("facturapi", creds)).test_connection()
        return {
            "ok": True,
            "message": "Conectado a Facturapi.",
            "details": {"Facturas": info.get("facturas", 0)},
        }
    except Exception as exc:  # API key inválida, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_belvo(creds: dict) -> dict:
    """Prueba real contra Belvo: valida las llaves (Basic) listando los links y, si
    hay link configurado, cuenta sus cuentas bancarias (lo que alimenta la
    conciliación)."""
    if not (creds.get("secret_id") and creds.get("secret_password")):
        return {"ok": False, "message": "Faltan las llaves de Belvo (secret id y password)."}
    from aiuda_core.connectors.belvo import BelvoClient

    try:
        info = BelvoClient(**cred.ctor_kwargs("belvo", creds)).test_connection(creds.get("belvo_link_id") or "")
        details = {"Conexiones bancarias": info.get("links", 0)}
        if info.get("cuentas") is not None:
            details["Cuentas del link"] = info["cuentas"]
        return {"ok": True, "message": "Conectado a Belvo.", "details": details}
    except Exception as exc:  # llaves inválidas, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


def _test_stripe(creds: dict) -> dict:
    """Prueba real contra Stripe (/v1/balance): valida la API key y confirma lectura
    de cargos. Devuelve el saldo disponible y cuántos cargos recientes hay."""
    if not creds.get("api_key"):
        return {"ok": False, "message": "Falta la API key (secreta) de Stripe."}
    from aiuda_core.connectors.stripe_pagos import StripeClient

    try:
        info = StripeClient(**cred.ctor_kwargs("stripe", creds)).test_connection()
        saldo = f"{info.get('disponible', 0):.2f} {info.get('moneda', '')}".strip()
        return {
            "ok": True,
            "message": "Conectado a Stripe.",
            "details": {"Saldo disponible": saldo, "Cargos recientes": info.get("cargos_recientes", 0)},
        }
    except Exception as exc:  # API key inválida, red
        return {"ok": False, "message": f"No se pudo conectar: {exc}"}


# Pruebas reales por fuente. Las que no están aquí responden honesto: por habilitar.
_TESTERS = {
    "odoo": _test_odoo,
    "email": _test_email,
    "denue": _test_denue,
    "whatsapp_cloud": _test_whatsapp_cloud,
    "slack": _test_slack,
    "google_sheets": _test_google_sheets,
    "mercadolibre": _test_mercadolibre,
    "twilio_voz": _test_twilio_voz,
    "shopify": _test_shopify,
    "woocommerce": _test_woocommerce,
    "hubspot": _test_hubspot,
    "googlecalendar": _test_googlecalendar,
    "facturama": _test_facturama,
    "facturapi": _test_facturapi,
    "belvo": _test_belvo,
    "stripe": _test_stripe,
    "image_gen": _test_image_gen,
    "mercadopago": _test_mercadopago,
    "clip": _test_clip,
    "conekta": _test_conekta,
}


@router.post("/v1/integrations/{key}/test")
def test_integration(
    key: str,
    tenant: Tenant = Depends(get_tenant),
    db=Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Probar conexión: pega de verdad al sistema con las credenciales del tenant
    (de la tabla cifrada, con fallback legado/settings) y reporta ok/falla. El
    resultado se guarda en la fila ('connected'/'error'), así 'Conectado' se vuelve
    verificable. Cada fuente en ``_TESTERS`` hace una llamada real y ligera a su API;
    las que aún no tienen prueba (p.ej. Excel, que es carga de archivo) responden
    honesto: 'por habilitarse'."""
    if key not in CATALOG_KEYS:
        raise HTTPException(status_code=404, detail="Integración desconocida.")
    tester = _TESTERS.get(key)
    if tester is None:
        return {
            "ok": None,
            "message": "La prueba de conexión para esta fuente está por habilitarse.",
        }
    try:
        creds = cred.get_credential(db, tenant.id, key)
    except Exception as exc:
        return {"ok": False, "message": f"No se pudieron leer las credenciales: {exc}"}
    if not creds:
        return {"ok": False, "message": "Primero guarda las credenciales."}
    result = tester(creds)

    # Persiste el veredicto en la fila cifrada (si la hay): 'Conectado' verificable.
    row = db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider == key,
        )
    )
    if row is not None:
        row.last_test_at = datetime.now(timezone.utc)
        if result.get("ok") is True:
            row.status = "connected"
            row.last_error = None
        elif result.get("ok") is False:
            row.status = "error"
            row.last_error = result.get("message")
        db.add(row)
        db.flush()
    return result
