export type AsistenteStatus = "activa" | "siguiente" | "diseño";

export type Asistente = {
  slug: string;
  /** Etiqueta visible: el rol. Los nombres de persona se retiraron, así que name = rol. */
  name: string;
  /** Mascota de aiuda, igual para todos: "/aiudante.png". */
  img: string;
  role: string;
  desc: string;
  status: AsistenteStatus;
  config: {
    reglas: string[];
    fuentes: { name: string; status: "conectada" | "disponible" | "planeada" }[];
    herramientas: string[];
    entrega: string[];
    autonomia: string;
  };
};

export const ASISTENTES: Asistente[] = [
  {
    slug: "mariana",
    name: "Cobranza",
    img: "/aiudante.png",
    role: "Cobranza",
    desc: "Vigila tu cartera, redacta recordatorios con el tono correcto y registra promesas de pago.",
    status: "activa",
    config: {
      reglas: [
        "Nunca envía un mensaje a un cliente directamente: ella redacta, un humano aprueba.",
        "El tono lo decide el sistema según el atraso; no negocia descuentos, quitas ni planes de pago.",
        "En atrasos críticos (+45 días) solo avisa que el responsable contactará personalmente.",
        "Nunca inventa montos, folios ni fechas: siempre consulta la cartera real.",
        "Disputas, quejas o temas legales los escala al humano, explícitamente.",
      ],
      fuentes: [
        { name: "Tu Excel o CSV, tal como lo llevas: la IA entiende su estructura", status: "conectada" },
        { name: "Odoo · facturas de cliente (XML-RPC)", status: "disponible" },
        { name: "WhatsApp Business · Evolution API", status: "disponible" },
        { name: "Belvo · detección de pagos bancarios", status: "disponible" },
        { name: "Shopify / WooCommerce · pedidos por cobrar de tu tienda", status: "disponible" },
        { name: "Stripe · cobros confirmados con tarjeta o link", status: "disponible" },
      ],
      herramientas: [
        "consultar_cartera: aging real de facturas, nunca de memoria",
        "redactar_recordatorio: crea borradores que esperan tu aprobación",
        "registrar_promesa_pago: captura fechas prometidas por el cliente",
        "registrar_pago: marca facturas cobradas",
        "enviar_whatsapp: solo ejecutable sobre recordatorios aprobados",
      ],
      entrega: [
        "Recordatorios por WhatsApp con tono graduado: amable, directo, firme, escalado",
        "Resumen diario de cartera a tu WhatsApp (8:00)",
        "Seguimiento de promesas: si no se cumplen, propone el siguiente paso",
        "Métrica de recuperado del mes: pagos sobre facturas que ella recordó",
      ],
      autonomia:
        "Aprobación humana por defecto en todo. El envío automático es opt-in por nivel de atraso y nunca aplica a casos críticos.",
    },
  },
  {
    slug: "carlos",
    name: "Ventas",
    img: "/aiudante.png",
    role: "Ventas",
    desc: "Atiende prospectos por WhatsApp y genera cotizaciones con tus precios reales.",
    status: "siguiente",
    config: {
      reglas: [
        "Cotiza solo con el catálogo y precios reales del negocio; sin descuentos no autorizados.",
        "Si no hay respuesta del prospecto, programa el seguimiento; no insiste más de lo configurado.",
        "Las excepciones de precio siempre pasan por el vendedor humano.",
      ],
      fuentes: [
        { name: "WhatsApp Business · Evolution API", status: "disponible" },
        { name: "Catálogo de productos (Odoo / Sheets / CSV)", status: "planeada" },
        { name: "Historial de cotizaciones previas", status: "planeada" },
        { name: "HubSpot · contactos y pipeline", status: "disponible" },
      ],
      herramientas: [
        "consultar_catalogo: productos, precios y existencias",
        "generar_cotizacion: PDF o mensaje estructurado",
        "agendar_seguimiento: recordatorio automático si no hay respuesta",
        "registrar_oportunidad: pipeline visible para el equipo",
      ],
      entrega: [
        "Cotizaciones en segundos, a cualquier hora",
        "Seguimientos automáticos que no dejan enfriar prospectos",
        "Reporte semanal de conversión por canal",
      ],
      autonomia:
        "Responde y cotiza solo; cierres, descuentos y condiciones especiales los aprueba el vendedor.",
    },
  },
  {
    slug: "lupita",
    name: "Legal y fiscal",
    img: "/aiudante.png",
    role: "Legal y fiscal",
    desc: "Monitorea acuerdos del SAT, tribunales y autoridades; calcula plazos en días hábiles.",
    status: "siguiente",
    config: {
      reglas: [
        "No es un repositorio de asuntos: se conecta a los que ya tienes (Excel, Odoo, tu sistema).",
        "Calcula plazos procesales con días inhábiles oficiales; ante duda, alerta antes y no después.",
        "Nunca da opinión jurídica: reporta el acuerdo, el plazo y la sugerencia de acción.",
      ],
      fuentes: [
        { name: "Lista de asuntos del despacho (Excel / CSV / Odoo)", status: "disponible" },
        { name: "Portales sin API (TFJA, IMSS, buzón SAT, tribunales) vía agente de cómputo (CUA)", status: "disponible" },
      ],
      herramientas: [
        "consultar_acuerdos: busca movimiento por expediente",
        "calcular_plazo: días hábiles restantes por tipo de recurso",
        "resumir_acuerdo: lenguaje simple, directo a WhatsApp",
        "agendar_vencimiento: al calendario del responsable",
      ],
      entrega: [
        "Notificación al abogado responsable con resumen y días hábiles restantes",
        "Alerta crítica si un plazo vence en menos de 3 días hábiles",
        "Reporte semanal de asuntos con y sin movimiento",
      ],
      autonomia: "Solo observa y notifica; nunca presenta promociones ni actúa ante la autoridad.",
    },
  },
  {
    slug: "valeria",
    name: "Recepción",
    img: "/aiudante.png",
    role: "Recepción",
    desc: "Responde preguntas frecuentes, agenda citas y escala al humano correcto.",
    status: "diseño",
    config: {
      reglas: [
        "Responde solo con la base de conocimiento que el negocio aprobó.",
        "Si no sabe, lo dice y escala; nunca inventa una respuesta.",
        "Las citas respetan la disponibilidad real del calendario.",
      ],
      fuentes: [
        { name: "Base de conocimiento del negocio (FAQ)", status: "planeada" },
        { name: "Google Calendar · disponibilidad y citas", status: "disponible" },
        { name: "WhatsApp Business · Evolution API", status: "disponible" },
      ],
      herramientas: [
        "buscar_en_kb: respuestas aprobadas por el negocio",
        "agendar_cita: con confirmación y recordatorio 24h antes",
        "escalar_a_humano: con el contexto completo de la conversación",
      ],
      entrega: [
        "Atención 24/7 en WhatsApp con la voz del negocio",
        "Citas agendadas y confirmadas sin intervención",
        "Resumen diario de conversaciones y tickets sin resolver",
      ],
      autonomia: "Autónoma en FAQ y citas; todo lo demás se escala con contexto.",
    },
  },
  {
    slug: "diego",
    name: "Conciliación",
    img: "/aiudante.png",
    role: "Conciliación",
    desc: "Cruza CFDI del SAT contra movimientos bancarios y prepara reportes para tu contador.",
    status: "diseño",
    config: {
      reglas: [
        "No modifica tu contabilidad: detecta diferencias y las presenta para revisión.",
        "Todo hallazgo lleva su evidencia: CFDI, movimiento y fecha.",
        "Las credenciales fiscales se usan solo para lectura.",
      ],
      fuentes: [
        { name: "SAT · CFDI emitidos y recibidos (Facturama)", status: "disponible" },
        { name: "Belvo · movimientos bancarios", status: "disponible" },
        { name: "ERP contable (Odoo, CONTPAQi)", status: "planeada" },
      ],
      herramientas: [
        "descargar_cfdi: del SAT, con e.firma o CIEC",
        "conciliar: cruza facturas contra depósitos",
        "detectar_irregulares: cancelados, sin comprobante, sin complemento",
      ],
      entrega: [
        "Reporte de diferencias banco–SAT listo para tu contador",
        "Alertas de CFDI cancelados que siguen en contabilidad",
        "Recordatorios de fechas de declaración",
      ],
      autonomia: "Solo lectura y reporte; ningún movimiento contable sin un humano.",
    },
  },
  {
    slug: "roberto",
    name: "Compras",
    img: "/aiudante.png",
    role: "Compras",
    desc: "Rastrea órdenes de compra, compara precios históricos y califica proveedores.",
    status: "diseño",
    config: {
      reglas: [
        "Sugiere órdenes de compra; no compra solo.",
        "Compara contra el histórico real del negocio, no contra listas externas.",
        "El scorecard de proveedores se basa en cumplimiento medible.",
      ],
      fuentes: [
        { name: "ERP · órdenes de compra e inventario", status: "planeada" },
        { name: "Correo · cotizaciones y confirmaciones de proveedores", status: "planeada" },
        { name: "SAT · CFDI de compras (Facturama)", status: "disponible" },
      ],
      herramientas: [
        "monitorear_ocs: detecta proveedores sin confirmar",
        "comparar_precios: actual vs histórico por producto",
        "sugerir_reorden: borrador de OC listo para aprobar",
      ],
      entrega: [
        "Alertas de desviación de precios y OCs sin respuesta",
        "Scorecard de proveedores por cumplimiento",
        "Resumen de compromisos de compra del mes",
      ],
      autonomia: "Todo es sugerencia: las órdenes las aprueba y envía un humano.",
    },
  },
  {
    slug: "memo",
    name: "Contenido",
    img: "/aiudante.png",
    role: "Contenido",
    desc: "Redacta publicaciones y campañas con la voz de tu marca, listas para tu aprobación.",
    status: "diseño",
    config: {
      reglas: [
        "Nada se publica sin aprobación; aprende del feedback de cada edición.",
        "Usa la voz de marca definida por el negocio, no la suya.",
        "No promete precios ni promociones que no estén en el catálogo.",
      ],
      fuentes: [
        { name: "Catálogo de productos y servicios", status: "planeada" },
        { name: "Historial de publicaciones aprobadas", status: "planeada" },
        { name: "Calendario editorial del negocio", status: "planeada" },
      ],
      herramientas: [
        "redactar_post: para IG, FB y LinkedIn con sugerencia de imagen",
        "redactar_campana: correos y promociones de temporada",
        "programar_publicacion: tras aprobación",
      ],
      entrega: [
        "Borradores semanales alineados al calendario editorial",
        "Descripciones de producto que venden",
        "Temporadas mexicanas integradas: Buen Fin, Hot Sale, fiestas",
      ],
      autonomia: "Redacta y propone; publicar siempre requiere visto bueno.",
    },
  },
  {
    slug: "sofia",
    name: "Prospección",
    img: "/aiudante.png",
    role: "Prospección",
    desc: "Encuentra empresas que encajan con tu cliente ideal y prepara fichas de contacto.",
    status: "diseño",
    config: {
      reglas: [
        "Construye el perfil de cliente ideal a partir de tus mejores clientes reales.",
        "Solo usa fuentes públicas y directorios oficiales.",
        "Entrega fichas para que tu equipo contacte; no hace outreach en frío sin permiso.",
      ],
      fuentes: [
        { name: "DENUE · INEGI (5.5M empresas mexicanas, fuente pública)", status: "disponible" },
        { name: "Directorios sectoriales y cámaras (CANACO, COPARMEX)", status: "planeada" },
        { name: "Tu base de clientes actuales (para el perfil ideal)", status: "planeada" },
      ],
      herramientas: [
        "definir_icp: perfil de cliente ideal con datos reales",
        "buscar_prospectos: empresas que encajan, por zona y giro",
        "preparar_ficha: contacto, razón de fit y mensaje sugerido",
      ],
      entrega: [
        "Lista semanal de prospectos calificados",
        "Ficha por prospecto: quién es, por qué encaja, cómo abrir",
        "Sugerencia de mensaje de apertura personalizado",
      ],
      autonomia: "Investiga y prepara; el primer contacto lo decide tu equipo.",
    },
  },
];

export function getAsistente(slug: string): Asistente | undefined {
  return ASISTENTES.find((a) => a.slug === slug);
}

/** Nombre visible de un agente por su slug: el rol. Los nombres de persona se retiraron, así
 *  que esto sustituye a cualquier `name` que venga del backend (que aún trae el rol). */
export function agentDisplayName(slug: string): string {
  return getAsistente(slug)?.role ?? "Ayudante";
}

/** Navegación que aporta cada agente al activarse. La consola es modular:
 *  activas un agente → aparece su sección. */
export const AGENT_NAV: Record<string, { title: string; items: { href: string; label: string }[] }> = {
  mariana: {
    title: "Cobranza",
    items: [
      { href: "/facturas", label: "Facturas" },
      { href: "/promesas", label: "Promesas de pago" },
      { href: "/conversaciones", label: "Conversaciones" },
      { href: "/clientes", label: "Clientes" },
    ],
  },
  carlos: {
    title: "Ventas",
    items: [{ href: "/productos", label: "Productos" }],
  },
  lupita: {
    title: "Legal y fiscal",
    items: [],
  },
  valeria: {
    title: "Recepción",
    items: [{ href: "/citas", label: "Agenda" }],
  },
  diego: {
    title: "Conciliación",
    items: [{ href: "/conciliacion", label: "Conciliación" }],
  },
  roberto: {
    title: "Compras",
    items: [],
  },
  memo: {
    title: "Contenido",
    items: [],
  },
  sofia: {
    title: "Prospección",
    items: [{ href: "/prospectos", label: "Prospectos" }],
  },
};
