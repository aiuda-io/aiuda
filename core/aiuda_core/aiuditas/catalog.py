"""Catálogo de aiuditas (capacidades) con sus perillas configurables.

Una *aiudita* es una capacidad atómica que el dueño agrega a su ayudante. Cada una
declara:
  - una `linea`: la explicación corta, en lenguaje del dueño (qué hace / cuándo);
  - sus `perillas`: la config tipada que el negocio puede ajustar;
  - `reglas_libres`: si ofrece la caja "reglas de tu negocio" en lenguaje natural.

HONESTIDAD (anti-fachada). `live=True` solo cuando hay un ejecutor que de verdad
honra la perilla o la aiudita HOY. Lo que no, va `live=False` ("por conectar"): se
guarda la config lista para cuando su motor exista, pero la UI lo muestra en gris y
el motor no finge. Verdad verificada del motor (2026-07-07):
  - cobranza: ejecutor real (CleoEngine + flujo de aprobación). Vertical a fondo aquí.
  - ventas:    consultar_catalogo, consultar_cliente (lectura) y generar_cotizacion
               (CarlosEngine: propone, el humano aprueba).
  - recepcion: consultar_agenda, buscar_cita (solo lectura).
  - conciliacion: consultar_pagos (lectura) y conciliar (engine/reconcile propone el
               match; el humano confirma en /conciliacion — nunca cierra solo).
  - el resto:  sin ejecutor todavía.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PerillaTipo(str, Enum):
    ENUM = "enum"      # una opción de una lista cerrada
    NUMERO = "numero"  # entero con mínimo/máximo opcionales
    BOOL = "bool"      # sí/no
    TEXTO = "texto"    # texto corto libre
    HORA = "hora"      # "HH:MM" 24h


@dataclass(frozen=True)
class Opcion:
    """Una opción de una perilla ENUM: valor estable + etiqueta para el dueño."""

    value: str
    label: str


@dataclass(frozen=True)
class Perilla:
    """Una palanca tipada de una aiudita, en lenguaje del dueño."""

    key: str                 # estable, snake_case; llave en el JSON de config
    label: str               # etiqueta para el dueño
    tipo: PerillaTipo
    default: object          # valor por defecto sensato (el negocio puede no tocar nada)
    ayuda: str = ""          # una línea que explica la palanca
    opciones: tuple[Opcion, ...] = ()  # solo ENUM
    minimo: int | None = None          # solo NUMERO
    maximo: int | None = None          # solo NUMERO
    unidad: str = ""                   # "días", "hrs"… (solo NUMERO)
    # (otra_key, valor): la perilla solo aplica si esa otra perilla tiene ese valor.
    depende_de: tuple[str, str] | None = None
    live: bool = False       # ¿el motor la honra HOY?


@dataclass(frozen=True)
class Aiudita:
    """Una capacidad que el dueño agrega y configura en su ayudante."""

    id: str                  # "{perfil}.{tool}", ej. "cobranza.redactar_recordatorio"
    perfil: str              # rol al que pertenece, ej. "cobranza"
    tool: str                # nombre interno de la herramienta (snake_case)
    label: str               # verbo concreto: "Redactar recordatorio"
    linea: str               # la "línea más rica": qué hace y cuándo, en una frase
    lectura: bool = True     # solo consulta (no escribe ni envía nada)
    perillas: tuple[Perilla, ...] = ()
    reglas_libres: bool = False  # ¿ofrece la caja "reglas de tu negocio"?
    live: bool = False       # ¿hay ejecutor real detrás?
    # Capacidad (función de negocio) de la que LEE esta aiudita, ej.
    # "cuentas_por_cobrar". Es lo que diferencia a aiuda de un ERP: el dueño
    # elige, por capacidad, DE QUÉ FUENTE jala el dato (su Excel, Odoo, tienda…).
    # Las fuentes posibles se DERIVAN de la capacidad en la capa de integraciones
    # (una sola fuente de verdad); la elegida se guarda en la config como `_fuente`.
    capacidad: str = ""


@dataclass(frozen=True)
class Perfil:
    """Una categoría de aiuditas (el rol). También es el nombre de la plantilla."""

    slug: str
    name: str
    desc: str


# --- Perfiles (roles) -------------------------------------------------------

PERFILES: tuple[Perfil, ...] = (
    Perfil("cobranza", "Cobranza", "Vigila tu cartera, redacta recordatorios y registra promesas de pago."),
    Perfil("ventas", "Ventas", "Atiende prospectos y cotiza con tus precios reales."),
    Perfil("legal", "Legal y fiscal", "Monitorea acuerdos y plazos del SAT y tribunales."),
    Perfil("recepcion", "Recepción", "Responde preguntas frecuentes y agenda citas."),
    Perfil("conciliacion", "Conciliación", "Cruza CFDI contra movimientos bancarios."),
    Perfil("compras", "Compras", "Rastrea órdenes de compra y califica proveedores."),
    Perfil("contenido", "Contenido", "Redacta publicaciones y campañas con tu voz de marca."),
    Perfil("prospeccion", "Prospección", "Encuentra empresas que encajan con tu cliente ideal."),
)


# --- Perillas reutilizables -------------------------------------------------

_TONO = Perilla(
    key="tono_base",
    label="Tono base",
    tipo=PerillaTipo.ENUM,
    default="amable",
    ayuda="El punto de partida del mensaje. Si el atraso crece, se endurece solo (abajo).",
    opciones=(
        Opcion("amable", "Amable"),
        Opcion("directo", "Directo"),
        Opcion("firme", "Firme"),
    ),
    live=True,
)


# --- Aiuditas ---------------------------------------------------------------
# Cobranza va a fondo (vertical vivo). El resto se declara presente pero sin
# perillas todavía: se profundiza cuando le toque su vertical.

AIUDITAS: tuple[Aiudita, ...] = (
    # ---- COBRANZA (vivo) ----
    Aiudita(
        id="cobranza.consultar_cartera",
        perfil="cobranza",
        tool="consultar_cartera",
        label="Consultar cartera",
        linea="Lee tus facturas abiertas con su atraso real, nunca de memoria, antes de decir cualquier monto o folio.",
        lectura=True,
        capacidad="cuentas_por_cobrar",
        live=True,
    ),
    Aiudita(
        id="cobranza.redactar_recordatorio",
        perfil="cobranza",
        tool="redactar_recordatorio",
        label="Redactar recordatorio",
        linea="Crea el borrador del recordatorio de cobro con el tono correcto; espera tu aprobación antes de salir.",
        lectura=False,
        perillas=(
            _TONO,
            Perilla(
                key="escalar_por_atraso",
                label="Endurecer el tono según el atraso",
                tipo=PerillaTipo.BOOL,
                default=True,
                ayuda="Entre más vencida la factura, más firme el mensaje. Si lo apagas, usa siempre el tono base.",
                live=True,
            ),
            Perilla(
                key="firma",
                label="Firma del mensaje",
                tipo=PerillaTipo.TEXTO,
                default="",
                ayuda="Con qué cierra el recordatorio. Ej: «Equipo de Cobranza · Hanova». Vacío = sin firma.",
                live=True,
            ),
            Perilla(
                key="incluir_link_pago",
                label="Incluir link de pago",
                tipo=PerillaTipo.BOOL,
                default=False,
                ayuda="Anexa un link para pagar de una vez (tarjeta, OXXO o SPEI). Requiere una "
                "pasarela conectada (Mercado Pago, Clip o Conekta); sin ella, el recordatorio sale sin link.",
                live=True,
            ),
        ),
        reglas_libres=True,  # caja: "no menciones recargos", "ofrece pago en OXXO"…
        live=True,
    ),
    Aiudita(
        id="cobranza.registrar_promesa_pago",
        perfil="cobranza",
        tool="registrar_promesa_pago",
        label="Registrar promesa de pago",
        linea="Anota la fecha que prometió el cliente y le da seguimiento si no cumple.",
        lectura=False,
        perillas=(
            Perilla(
                key="dias_gracia",
                label="Días de gracia",
                tipo=PerillaTipo.NUMERO,
                default=0,
                ayuda="Tolerancia tras la fecha prometida antes de considerarla incumplida.",
                minimo=0,
                maximo=30,
                unidad="días",
                live=True,
            ),
            Perilla(
                key="seguir_si_incumple",
                label="Dar seguimiento si no cumple",
                tipo=PerillaTipo.BOOL,
                default=True,
                ayuda="Si pasa la fecha prometida sin pago, propone el siguiente paso.",
                live=True,
            ),
        ),
        live=True,
    ),
    Aiudita(
        id="cobranza.registrar_pago",
        perfil="cobranza",
        tool="registrar_pago",
        label="Registrar pago reportado",
        linea="Guarda que el cliente dice haber pagado; la factura sigue abierta hasta verificar contra el banco. Un dicho no es un pago.",
        lectura=False,
        live=True,
    ),
    Aiudita(
        id="cobranza.enviar_whatsapp",
        perfil="cobranza",
        tool="enviar_whatsapp",
        label="Enviar por WhatsApp",
        linea="Manda el recordatorio ya aprobado al cliente, respetando tus reglas de autonomía y de no-molestar.",
        lectura=False,
        perillas=(
            Perilla(
                key="autonomia",
                label="Cuándo puede enviar",
                tipo=PerillaTipo.ENUM,
                default="siempre_pedir",
                ayuda="El control es tuyo por defecto. El auto-envío es opt-in y nunca aplica a casos críticos.",
                opciones=(
                    Opcion("siempre_pedir", "Siempre pedir mi aprobación"),
                    Opcion("auto_bajo_umbral", "Auto-enviar bajo cierto atraso"),
                ),
                live=True,
            ),
            Perilla(
                key="umbral_auto_dias",
                label="Auto-enviar solo por debajo de",
                tipo=PerillaTipo.NUMERO,
                default=7,
                ayuda="Arriba de este atraso siempre pide tu aprobación.",
                minimo=1,
                maximo=44,
                unidad="días",
                depende_de=("autonomia", "auto_bajo_umbral"),
                live=True,
            ),
            Perilla(
                key="cooldown_dias",
                label="No volver a escribir antes de",
                tipo=PerillaTipo.NUMERO,
                default=4,
                ayuda="Evita molestar: no vuelve a contactar al mismo cliente dentro de este plazo.",
                minimo=0,
                maximo=30,
                unidad="días",
                live=True,  # ya existe en engine.py como reminder_cooldown_days
            ),
            Perilla(
                key="tope_critico_dias",
                label="Atraso crítico",
                tipo=PerillaTipo.NUMERO,
                default=45,
                ayuda="Arriba de esto nunca auto-envía: solo avisa que el responsable contactará en persona.",
                minimo=15,
                maximo=180,
                unidad="días",
                live=True,
            ),
            Perilla(
                key="ventana_horaria",
                label="Horario permitido para enviar",
                tipo=PerillaTipo.TEXTO,
                default="09:00-19:00",
                ayuda="Solo envía dentro de esta franja. Formato 24h, ej. 09:00-19:00.",
                live=True,
            ),
        ),
        live=True,
    ),
    Aiudita(
        id="cobranza.resumen_diario",
        perfil="cobranza",
        tool="resumen_diario",
        label="Resumen diario de cartera",
        linea="Te manda un resumen de tu cartera y lo accionable del día por WhatsApp.",
        lectura=True,
        capacidad="cuentas_por_cobrar",
        perillas=(
            Perilla(
                key="activo",
                label="Mandar resumen diario",
                tipo=PerillaTipo.BOOL,
                default=True,
                ayuda="Apágalo si no quieres el resumen automático.",
                live=True,
            ),
            Perilla(
                key="hora",
                label="Hora del resumen",
                tipo=PerillaTipo.HORA,
                default="08:00",
                ayuda="A qué hora llega. Formato 24h.",
                live=True,
            ),
        ),
        live=True,
    ),
    # ---- VENTAS (lectura viva, resto por conectar) ----
    Aiudita("ventas.consultar_catalogo", "ventas", "consultar_catalogo", "Consultar catálogo",
            "Busca productos, precios y existencias reales antes de cotizar.", lectura=True, capacidad="catalogo_productos", live=True),
    Aiudita("ventas.consultar_cliente", "ventas", "consultar_cliente", "Consultar cliente",
            "Revisa los datos y el saldo del cliente para atender con contexto.", lectura=True, capacidad="directorio_clientes", live=True),
    Aiudita(
        id="ventas.generar_cotizacion",
        perfil="ventas",
        tool="generar_cotizacion",
        label="Generar cotización",
        linea="Arma la cotización con tus precios reales; tú apruebas descuentos y cierres.",
        lectura=False,
        capacidad="catalogo_productos",  # los precios salen de tu catálogo (la fuente que elijas)
        perillas=(
            Perilla(
                key="validez_dias",
                label="Vigencia de la cotización",
                tipo=PerillaTipo.NUMERO,
                default=15,
                ayuda="Cuántos días es válido el precio cotizado.",
                minimo=1,
                maximo=90,
                unidad="días",
                live=True,
            ),
            Perilla(
                key="iva_incluido",
                label="Los precios ya incluyen IVA",
                tipo=PerillaTipo.BOOL,
                default=True,
                ayuda="Si lo apagas, la cotización suma el IVA (16%) aparte.",
                live=True,
            ),
            Perilla(
                key="descuento_max",
                label="Descuento máximo permitido",
                tipo=PerillaTipo.NUMERO,
                default=0,
                ayuda="Tope que el ayudante puede aplicar. Arriba de esto, lo decides tú.",
                minimo=0,
                maximo=100,
                unidad="%",
                live=True,
            ),
        ),
        reglas_libres=True,  # caja: "ofrece envío gratis arriba de $5,000", condiciones…
        live=True,
    ),
    Aiudita("ventas.agendar_seguimiento", "ventas", "agendar_seguimiento", "Agendar seguimiento",
            "Programa el recordatorio si el prospecto no responde.", lectura=False),
    Aiudita("ventas.registrar_oportunidad", "ventas", "registrar_oportunidad", "Registrar oportunidad",
            "Deja la oportunidad visible en el pipeline del equipo.", lectura=False),
    # ---- RECEPCIÓN (lectura viva, resto por conectar) ----
    Aiudita("recepcion.consultar_agenda", "recepcion", "consultar_agenda", "Consultar agenda",
            "Revisa la disponibilidad real del calendario.", lectura=True, capacidad="agenda", live=True),
    Aiudita("recepcion.buscar_cita", "recepcion", "buscar_cita", "Buscar cita",
            "Encuentra una cita existente por cliente o fecha.", lectura=True, capacidad="agenda", live=True),
    Aiudita("recepcion.agendar_cita", "recepcion", "agendar_cita", "Agendar cita",
            "Agenda con confirmación y recordatorio 24h antes.", lectura=False),
    Aiudita("recepcion.buscar_en_kb", "recepcion", "buscar_en_kb", "Responder preguntas frecuentes",
            "Contesta solo con la base de conocimiento que tu negocio aprobó.", lectura=True, reglas_libres=True),
    Aiudita("recepcion.escalar_a_humano", "recepcion", "escalar_a_humano", "Escalar a un humano",
            "Pasa la conversación al humano correcto, con todo el contexto.", lectura=False),
    # ---- LEGAL Y FISCAL (por conectar) ----
    Aiudita("legal.consultar_acuerdos", "legal", "consultar_acuerdos", "Consultar acuerdos",
            "Busca movimiento por expediente en tribunales.", lectura=True, capacidad="expedientes"),
    Aiudita("legal.calcular_plazo", "legal", "calcular_plazo", "Calcular plazo",
            "Cuenta los días hábiles restantes por tipo de recurso.", lectura=True),
    Aiudita("legal.resumir_acuerdo", "legal", "resumir_acuerdo", "Resumir acuerdo",
            "Traduce el acuerdo a lenguaje simple para WhatsApp.", lectura=True),
    Aiudita("legal.agendar_vencimiento", "legal", "agendar_vencimiento", "Agendar vencimiento",
            "Pone el vencimiento en el calendario del responsable.", lectura=False),
    # ---- CONCILIACIÓN (consulta y propuesta de matches vivas; CFDI por conectar) ----
    Aiudita("conciliacion.consultar_pagos", "conciliacion", "consultar_pagos", "Consultar pagos por conciliar",
            "Lee los depósitos detectados y a qué factura corresponden según la propuesta, antes de dar un pago por aplicado.",
            lectura=True, capacidad="confirmacion_pago", live=True),
    Aiudita("conciliacion.descargar_cfdi", "conciliacion", "descargar_cfdi", "Descargar CFDI",
            "Baja los CFDI del SAT con e.firma o CIEC, solo lectura.", lectura=True, capacidad="cfdi"),
    Aiudita("conciliacion.conciliar", "conciliacion", "conciliar", "Conciliar",
            "Cruza facturas contra depósitos y te propone las coincidencias; tú confirmas cada match.", lectura=False, live=True),
    Aiudita("conciliacion.detectar_irregulares", "conciliacion", "detectar_irregulares", "Detectar irregulares",
            "Marca cancelados, sin comprobante o sin complemento.", lectura=True, capacidad="cfdi"),
    # ---- COMPRAS (por conectar) ----
    Aiudita("compras.monitorear_ocs", "compras", "monitorear_ocs", "Monitorear órdenes de compra",
            "Detecta proveedores que no han confirmado.", lectura=True, capacidad="compras"),
    Aiudita("compras.comparar_precios", "compras", "comparar_precios", "Comparar precios",
            "Compara el precio actual contra tu histórico real.", lectura=True, capacidad="catalogo_productos"),
    Aiudita("compras.sugerir_reorden", "compras", "sugerir_reorden", "Sugerir reorden",
            "Prepara el borrador de orden de compra para que apruebes.", lectura=False),
    # ---- CONTENIDO (por conectar) ----
    Aiudita("contenido.redactar_post", "contenido", "redactar_post", "Redactar publicación",
            "Escribe posts para IG, FB y LinkedIn con tu voz de marca.", lectura=False, reglas_libres=True),
    Aiudita("contenido.redactar_campana", "contenido", "redactar_campana", "Redactar campaña",
            "Arma correos y promociones de temporada.", lectura=False, reglas_libres=True),
    Aiudita("contenido.programar_publicacion", "contenido", "programar_publicacion", "Programar publicación",
            "Programa la publicación tras tu aprobación.", lectura=False),
    # ---- PROSPECCIÓN (por conectar) ----
    Aiudita("prospeccion.definir_icp", "prospeccion", "definir_icp", "Definir cliente ideal",
            "Construye tu perfil de cliente ideal con tus mejores clientes reales.", lectura=True, reglas_libres=True),
    Aiudita("prospeccion.buscar_prospectos", "prospeccion", "buscar_prospectos", "Buscar prospectos",
            "Encuentra empresas que encajan, por zona y giro, en fuentes públicas.", lectura=True, capacidad="prospeccion"),
    Aiudita("prospeccion.preparar_ficha", "prospeccion", "preparar_ficha", "Preparar ficha",
            "Arma la ficha: quién es, por qué encaja y cómo abrir la conversación.", lectura=False),
)


# --- Índices y lookups ------------------------------------------------------

_AIUDITA_POR_ID: dict[str, Aiudita] = {a.id: a for a in AIUDITAS}
_PERFIL_POR_SLUG: dict[str, Perfil] = {p.slug: p for p in PERFILES}


def aiudita_por_id(aiudita_id: str) -> Aiudita | None:
    return _AIUDITA_POR_ID.get(aiudita_id)


def aiuditas_de_perfil(perfil: str) -> list[Aiudita]:
    return [a for a in AIUDITAS if a.perfil == perfil]


# --- Config: default + validación -------------------------------------------

def config_default(aiudita: Aiudita) -> dict:
    """Config inicial de una aiudita: el default de cada perilla (+ caja de reglas vacía)."""
    cfg: dict = {p.key: p.default for p in aiudita.perillas}
    if aiudita.reglas_libres:
        cfg["reglas"] = ""
    return cfg


def _coerce(perilla: Perilla, value: object) -> object:
    """Coacciona y acota un valor al tipo de la perilla; ante basura, vuelve al default."""
    try:
        if perilla.tipo is PerillaTipo.BOOL:
            return bool(value)
        if perilla.tipo is PerillaTipo.NUMERO:
            n = int(value)  # type: ignore[arg-type]
            if perilla.minimo is not None:
                n = max(perilla.minimo, n)
            if perilla.maximo is not None:
                n = min(perilla.maximo, n)
            return n
        if perilla.tipo is PerillaTipo.ENUM:
            valid = {o.value for o in perilla.opciones}
            return value if value in valid else perilla.default
        # TEXTO / HORA: string acotado
        return str(value)[:280]
    except (TypeError, ValueError):
        return perilla.default


def _perilla_payload(p: Perilla) -> dict:
    d: dict = {
        "key": p.key,
        "label": p.label,
        "tipo": p.tipo.value,
        "default": p.default,
        "ayuda": p.ayuda,
        "live": p.live,
    }
    if p.opciones:
        d["opciones"] = [{"value": o.value, "label": o.label} for o in p.opciones]
    if p.minimo is not None:
        d["minimo"] = p.minimo
    if p.maximo is not None:
        d["maximo"] = p.maximo
    if p.unidad:
        d["unidad"] = p.unidad
    if p.depende_de is not None:
        d["depende_de"] = {"key": p.depende_de[0], "valor": p.depende_de[1]}
    return d


def _aiudita_payload(a: Aiudita) -> dict:
    return {
        "id": a.id,
        "perfil": a.perfil,
        "tool": a.tool,
        "label": a.label,
        "linea": a.linea,
        "lectura": a.lectura,
        "live": a.live,
        "reglas_libres": a.reglas_libres,
        "capacidad": a.capacidad,  # la capa de integraciones deriva sus fuentes
        "perillas": [_perilla_payload(p) for p in a.perillas],
    }


def catalog_payload() -> dict:
    """El catálogo completo en forma serializable: una sola fuente para el frontend
    (perfiles + aiuditas + perillas), sin duplicar el esquema en TypeScript."""
    return {
        "perfiles": [{"slug": p.slug, "name": p.name, "desc": p.desc} for p in PERFILES],
        "aiuditas": [_aiudita_payload(a) for a in AIUDITAS],
    }


def validar_config(aiudita: Aiudita, entrada: dict | None) -> dict:
    """Limpia la config que llega del cliente: solo perillas conocidas, tipadas y
    acotadas. Lo desconocido se descarta (no confiamos en el cliente)."""
    entrada = entrada or {}
    cfg: dict = {}
    for p in aiudita.perillas:
        cfg[p.key] = _coerce(p, entrada[p.key]) if p.key in entrada else p.default
    if aiudita.reglas_libres:
        reglas = entrada.get("reglas", "")
        cfg["reglas"] = str(reglas)[:2000] if reglas is not None else ""
    # Fuente elegida (de dónde lee esta capacidad). Se preserva como string; la
    # validez contra las fuentes posibles la decide la capa de integraciones
    # (donde vive el mapa capacidad->fuentes), no el core.
    if aiudita.capacidad:
        fuente = entrada.get("_fuente")
        if isinstance(fuente, str) and fuente:
            cfg["_fuente"] = fuente[:40]
    return cfg
