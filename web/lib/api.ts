// Same-origin: /api/* se reescribe al backend local en next.config.ts. No hay
// sesiones ni logins: el API corre en 127.0.0.1 en la máquina del dueño.
// NEXT_PUBLIC_API_KEY quedó solo para scripts/dev; normalmente no se define.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

export type AgingLine = { bucket: string; count: number; total: number };

export type Cartera = {
  business_name: string;
  today: string;
  recovered_this_month: number;
  open_total: number;
  open_count: number;
  pending_approvals: number;
  active_promises: number;
  payment_reports: number;
  by_source: Record<string, number>;
  aging: AgingLine[];
};

export type ReminderItem = {
  id: string;
  agent: string;
  invoice_id: string | null;
  title: string | null;
  folio: string | null;
  customer: string | null;
  customer_id: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  amount: number | null;
  currency: string;
  due_date: string | null;
  bucket: string;
  tone: string;
  message: string;
  status: string;
  channel: string;
  channels: { key: string; label: string; connected: boolean }[];
  /** Solo respuestas de correo: a quién y a qué hilo responde. null en lo demás. */
  correo: { para: string; conversation_id?: string } | null;
  /** De dónde salió el dato que sustenta este trabajo (trazabilidad al aprobar). */
  procedencia: Procedencia | null;
  /** Qué ayudante del dueño produjo la propuesta (null si ninguno la gobierna). */
  propuesto_por: string | null;
  created_at: string;
  /** Cuándo salió de verdad (ISO). null si aún no se ha enviado. "Enviados" deriva de aquí. */
  sent_at?: string | null;
  /** Si el envío se intentó y tronó: el motivo visible (canal caído, sin contacto). */
  motivo_fallo?: string | null;
  /** Si se aprobó sin canal conectado: aviso honesto ("se enviará cuando conectes…"). */
  pendiente?: string | null;
};

/** Procedencia de un dato: qué es + de qué fuente(s) viene, con su presencia. */
export type Procedencia = {
  que?: string;
  source: string;
  sources?: string[];
  presence?: Record<string, { ref?: string; url?: string; file?: string; at?: string }>;
};

export type InvoiceItem = {
  id: string;
  folio: string;
  customer: string;
  customer_phone: string;
  amount: number;
  currency: string;
  issued_date: string;
  due_date: string;
  days_overdue: number;
  bucket: string;
  status: string;
  paid_at: string | null;
  source: string;
  presence: Record<string, { ref?: string; url?: string; file?: string; at?: string }>;
  verified: string;
  payment_reported: boolean;
  paid_source: string | null;
};

export type PromiseItem = {
  id: string;
  invoice_id: string;
  folio: string;
  customer: string;
  customer_id: string;
  amount: number;
  promised_date: string;
  note: string | null;
  days_left: number;
  fulfilled_at: string | null;
};

export type ChatMessage = {
  id: string;
  direction: string;
  author: string;
  body: string;
  created_at: string | null;
  // Entrega del saliente: sent | failed | pending | null (entrante/sin rastreo).
  delivery?: string | null;
  // Presentes solo en la respuesta de envío (no al listar el hilo).
  delivered?: boolean;
  delivery_error?: string | null;
};

export type CustomerDetail = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  kind: string;
  presence: Record<string, { ref?: string; url?: string; file?: string; at?: string }>;
  tags: string[];
  meta: Record<string, string>;
  // El cliente pidió no recibir mensajes (BAJA/STOP); null = puede recibir.
  opt_out: { at: string; via: string } | null;
  open_total: number;
  open_count: number;
  conversation_id: string | null;
  human_takeover: boolean;
  messages: ChatMessage[];
  invoices: {
    id: string;
    folio: string;
    amount: number;
    status: string;
    bucket: string;
    days_overdue: number;
  }[];
  reminders: { id: string; folio: string | null; status: string; channel: string; bucket: string; created_at: string }[];
  promises: { id: string; folio: string | null; promised_date: string; fulfilled: boolean }[];
  payments: { id: string; amount: number; paid_at: string; source: string; folio: string | null; status: string }[];
  citas: { id: string; title: string; starts_at: string | null }[];
};

export type Cfdi = {
  version: string | null;
  serie: string | null;
  folio: string | null;
  fecha: string | null;
  tipo: string | null;
  moneda: string | null;
  subtotal: number | null;
  total: number | null;
  uuid: string | null;
  fecha_timbrado: string | null;
  emisor: { rfc?: string; nombre?: string; regimen?: string };
  receptor: { rfc?: string; nombre?: string; uso?: string };
  iva: number | null;
  conceptos: number;
};

export type InvoiceDetail = InvoiceItem & {
  customer_id: string;
  conversation_id: string | null;
  cfdi: Cfdi | Record<string, never>;
  has_xml: boolean;
  has_pdf: boolean;
  reminders: {
    id: string;
    agent: string;
    tone: string;
    bucket: string;
    status: string;
    message: string;
    sent_at: string | null;
    created_at: string | null;
  }[];
  promises: {
    id: string;
    promised_date: string;
    note: string | null;
    fulfilled: boolean;
    fulfilled_at: string | null;
  }[];
};

/** Una inyección de write-back: lo confirmado en aiuda escrito de regreso a la fuente. */
export type WritebackEntry = {
  id: string;
  target: string;
  target_label?: string; // el nombre que ve el dueño (conexión a la medida = su nombre)
  action: string; // registrar_pago | actualizar_cliente | crear_*
  estado: string; // pendiente | inyectada | falló
  attempts: number;
  last_error: string | null;
  folio: string | null;
  amount: number | null;
  changes: Record<string, string | null> | null;
  evidencia: {
    en?: string;
    escrito?: Record<string, unknown>;
    respuesta?: {
      modo?: string;
      detalle?: string;
      payment_state?: string;
      saldo_odoo?: number;
      creado?: boolean;
      partner_id?: number;
      pedido?: string;
      /** Altas inyectadas: referencia del registro creado en el destino. */
      ref?: string | null;
    };
  } | null;
  reintento_en: string | null;
  created_at: string | null;
  done_at: string | null;
};

export type CustomerItem = {
  id: string;
  name: string;
  phone: string | null;
  open_invoices: number;
  open_total: number;
  tags: string[];
  kind: string;
  meta: Record<string, string>;
};

export type ProductItem = {
  id: string;
  name: string;
  sku: string | null;
  price: number | null;
  stock: number | null;
  unit: string | null;
  source: string;
  meta: Record<string, string>;
  presence: Record<string, { ref?: string; url?: string; file?: string; at?: string }>;
};

/** Estado de la fuente de prospección (DENUE · INEGI): sin token no hay búsqueda. */
export type ProspeccionFuente = {
  fuente: string;
  nombre: string;
  conectada: boolean;
};

/** Un negocio del directorio DENUE, con la marca de si YA está en tu cartera. */
export type NegocioDenue = {
  id: string;
  nombre: string;
  razon_social: string;
  actividad: string;
  telefono: string;
  correo: string;
  direccion: string;
  contactable: boolean;
  ya_registrado: boolean;
  cliente_id: string | null;
};

export type ProspeccionBusqueda = { total: number; resultados: NegocioDenue[] };

export type ProspeccionImport = {
  importados: number;
  ya_existian: number;
  omitidos: number;
  total: number;
  detalle: { id: string; cliente_id: string; creado: boolean }[];
};

export type AppointmentItem = {
  id: string;
  title: string;
  customer_name: string | null;
  customer_phone: string | null;
  starts_at: string | null;
  notes: string | null;
  source: string;
  /** Datos extra planos. Tras inyectarse, la liga vive en
   *  meta.inyectada_en[destino] = { ref, url } (la cita no tiene presence). */
  meta: Record<string, unknown> & {
    inyectada_en?: Record<string, { ref?: string | null; url?: string | null }>;
  };
};

/** Resultado del check "crear también en...": el alta quedó encolada al destino
 *  (el write-back la escribe en segundo plano; su estado se ve en la ficha). */
export type InyeccionEncolada = { outbox_id: string; target: string; status: string } | null;

/** Un destino que HOY puede recibir altas: conector con credencial real (Odoo,
 *  Google Calendar) o conexión a la medida cuya receta declara write_path. */
export type InyectarDestino = { target: string; label: string; conexion_id?: string };

/** Entidad inyectable (los singulares que entiende POST /v1/inyectar). */
export type EntidadInyectable = "cliente" | "producto" | "factura" | "cita";

/** GET /v1/inyectar/destinos: destinos disponibles por entidad (derivado de
 *  credenciales reales, no configurado a mano; lista vacía = honesto, nada). */
export type InyectarDestinos = Record<EntidadInyectable, InyectarDestino[]>;

/** Una factura candidata que propone el ayudante de conciliación para un pago. */
export type ReconcileCandidate = {
  invoice_id: string;
  folio: string;
  customer: string;
  amount: number;
  /** Lo que FALTA por cobrar (total menos abonos ya conciliados). */
  saldo: number;
  due_date: string;
  score: number;
  reason: string;
  cuadra: boolean;
  /** El pago no alcanza el saldo: aplicarlo sería un abono, la factura sigue abierta. */
  parcial: boolean;
};

/** Varias facturas del MISMO cliente cuyos saldos suman el pago (una transferencia, varias facturas). */
export type ReconcileGroup = {
  invoice_ids: string[];
  folios: string[];
  customer: string;
  total: number;
  score: number;
  reason: string;
  cuadra: boolean;
};

/** Un pago pendiente de conciliar, con la propuesta del ayudante de conciliación y alternativas. */
export type ReconcileItem = {
  id: string;
  amount: number;
  currency: string;
  paid_at: string;
  source: string;
  /** Procedencia legible si vino de un estado de cuenta en PDF ("de tu estado de cuenta de BBVA, marzo 2026"). */
  origen: string | null;
  reference: string | null;
  counterparty: string | null;
  proposal: ReconcileCandidate | null;
  alternates: ReconcileCandidate[];
  grupos: ReconcileGroup[];
  /** Qué propone el ayudante como mejor opción; null = ambiguo o sin candidatas. */
  propuesta_tipo: "factura" | "grupo" | null;
  /** Varias opciones parejas: el ayudante NO elige solo, decide el humano. */
  ambiguo: boolean;
  nota: string;
};

/** Un dicho de pago: el cliente DICE que ya pagó; se contrasta contra el banco. */
export type DichoPago = {
  invoice_id: string;
  folio: string;
  customer: string;
  amount: number;
  saldo: number;
  due_date: string;
  /** El pago pendiente del banco/pasarela que lo respalda, si existe. */
  respaldo: {
    payment_id: string;
    amount: number;
    paid_at: string;
    source: string;
    diferencia: number;
  } | null;
};

/** Estado honesto de una fuente de confirmación de pago (Belvo/Stripe). */
export type FuenteConfirmacion = { configurada: boolean; verificada_en_vivo: boolean };

export type ReconcileConfig = { tolerancia_pct: number; tolerancia_abs: number };

export type ReconcileBandeja = {
  pending: ReconcileItem[];
  count: number;
  dichos: DichoPago[];
  fuentes: Record<string, FuenteConfirmacion>;
  config: ReconcileConfig;
};

/** Aplicación de un pago a una factura al conciliar (cerrada o abonada). */
export type ReconcileAplicacion = {
  invoice_id: string;
  folio: string;
  aplicado: number;
  cerrada: boolean;
  saldo: number;
};

/** Un pago ya resuelto: conciliado (con sus aplicaciones) o rechazado. */
export type ReconcileResuelto = {
  id: string;
  amount: number;
  currency: string;
  paid_at: string;
  source: string;
  origen: string | null;
  reference: string | null;
  counterparty: string | null;
  status: "conciliado" | "ignorado";
  resuelto_el: string;
  aplicaciones: ReconcileAplicacion[];
  excedente: number;
};

export type Tag = { id: string; name: string; color: string; count?: number };

export type ConversationStatus = "identificado" | "por_identificar" | "descartado";

/** Hilo de correo: quién escribe y de qué va (la clave técnica vive en remote_phone). */
export type CorreoHilo = { de: string; nombre: string; asunto: string };

export type ConversationItem = {
  id: string;
  remote_phone: string;
  /** Canal del hilo: whatsapp | correo (sms cuando exista). */
  channel: string;
  /** Solo hilos de correo: remitente/nombre/asunto. null en WhatsApp. */
  correo: CorreoHilo | null;
  customer: string | null;
  customer_id: string | null;
  last_message: string | null;
  last_direction: string | null;
  last_at: string | null;
  messages: number;
  status: ConversationStatus;
  human_takeover: boolean;
};

export type ConversationDetail = {
  id: string;
  remote_phone: string;
  channel: string;
  correo: CorreoHilo | null;
  customer: string | null;
  customer_id: string | null;
  human_takeover: boolean;
  messages: {
    id: string;
    direction: string;
    author: string;
    body: string;
    delivery?: string | null;
    created_at: string;
  }[];
};

/** Plan de carrera: el nivel lo calcula el BACKEND a partir de acciones reales
 *  (filas de trabajo derivadas en cada lectura, no un contador). Aquí solo se pinta. */
export type Nivel = {
  nivel: string;
  /** Umbral de acciones del siguiente nivel; null en el máximo. */
  siguiente: number | null;
  /** Progreso [0..1] hacia el siguiente nivel. */
  progreso: number;
};

export type AgentState = {
  slug: string;
  active: boolean;
  actions: number;
  pending: number;
  sent: number;
  nivel: Nivel;
};

export type AgentConfig = {
  slug: string;
  user_rules: string[];
  auto_send_buckets: string[];
  business_context: string;
};

export type ImportResult = {
  filename: string;
  entity: string;
  entity_label: string;
  mapping?: Record<string, string | null>;
  created: number;
  skipped: number;
  errors: string[];
};

/** Paso 1 del uploader: lo que la IA propone antes de importar nada. */
export type ImportAnalysis = {
  filename: string;
  entity: string; // "" si no la reconoció
  confidence: number;
  columns: string[];
  sample: Record<string, string>[];
  mapping: Record<string, string | null>; // campo -> columna del usuario
  fields: Record<string, string>; // campo -> descripción
  types: { key: string; label: string }[];
  row_count: number;
};

export type UsageSummary = {
  month: string;
  total_cost_usd: number;
  by_model: { model: string; input_tokens: number; output_tokens: number; cost_usd: number }[];
  activity: {
    recordatorios_redactados: number;
    recordatorios_enviados: number;
    conversaciones_atendidas: number;
    mensajes_respondidos: number;
    promesas_registradas: number;
  };
};


/** La puerta que da a la red de la oficina. Apagada, aiuda solo habla consigo mismo. */
export type RedLocal = {
  prendida: boolean;
  puerto: number | null;
  direccion: string | null;
  /** Si aiuda alcanzó a anunciarse en la red (Bonjour). */
  anunciada: boolean;
  /** Lo que el dueño dejó decidido, aunque ahorita no haya red. */
  quiere_prendida: boolean;
  /** macOS pregunta una vez si aiuda puede ver la red local. null = no se sabe. */
  permiso_del_sistema: boolean | null;
  /** A dónde mandarlo si dijo que no. */
  ajustes?: string;
};

/** Un teléfono o tableta emparejado. No es una cuenta: es un aparato. */
export type Dispositivo = {
  id: string;
  nombre: string;
  papel: "dueno" | "invitado";
  /** Hasta cuánto aprueba solo. null = ve y propone, pero no aprueba. */
  tope_aprobacion: number | null;
  activo: boolean;
  ultimo_visto: string | null;
  revocado_en: string | null;
  creado: string | null;
};

/** Lo que va dentro del QR. La huella es lo que ata al teléfono a ESTA computadora. */
export type Invitacion = {
  qr: {
    v: number;
    host: string;
    puerto: number;
    huella: string;
    codigo: string;
    negocio: string;
  };
  /** El QR ya dibujado (data URI), para pintarlo sin librerías en el navegador. */
  qr_svg: string;
  caduca_en: number;
  papel: "dueno" | "invitado";
  tope_aprobacion: number | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      ...(init?.headers ?? {}),
    },
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// Descarga binaria (xlsx). request<T> fuerza res.json(); aquí regresa el Blob.
async function requestBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: {
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    },
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }
  return res.blob();
}

/** Listas exportables a Excel (una hoja por entidad, encabezados reimportables). */
export type ExportEntidad =
  | "facturas"
  | "clientes"
  | "prospectos"
  | "productos"
  | "citas"
  | "promesas"
  | "conciliacion";

/** GET /v1/workspace: identidad del negocio local (no hay cuentas ni sesiones). */
export type WorkspaceInfo = {
  business_name: string;
  role: string;
};

export type Profile = {
  business_name: string;
  owner_name: string;
  email: string;
  phone: string;
  rfc: string;
};

export type SearchResponse = {
  groups: { title: string; items: { label: string; sublabel: string; href: string }[] }[];
};

/** Un hito del embudo de activación; `done` se deriva del estado real en backend. */
export type OnboardingStep = {
  key: string;
  label: string;
  done: boolean;
  href: string;
};

export type OnboardingState = {
  steps: OnboardingStep[];
  done_count: number;
  total: number;
};

/** GET /v1/setup/estado: lo que aiuda encontró en ESTA computadora en el primer
 *  arranque. El asistente (components/setup-wizard.tsx) lo usa para proponer el
 *  camino más corto: si ya hay un modelo local corriendo, conectarlo es un clic. */
export type SetupEstado = {
  negocio: { nombre: string; listo: boolean };
  ia: {
    conectada: boolean;
    proveedor: string | null;
    ollama_corriendo: boolean;
    modelos_locales: string[];
    modelo_sugerido: string | null;
    base_url_local: string;
    env_key: boolean;
  };
  datos: { fuentes: string[]; clientes: number; facturas: number; listo: boolean };
  ayudantes: { total: number; listo: boolean };
  extras: { wacli: boolean };
  terminado: boolean;
};

/** Un modelo que aiuda recomienda para ESTA computadora. `cabe` es el veredicto
 *  honesto contra la memoria disponible: "bien" holgado, "justo" al límite, "no"
 *  no da. `para` es una línea en palabras del dueño ("el más equilibrado"). */
export type ModeloRecomendado = {
  nombre: string;
  tam_gb: number;
  cabe: "bien" | "justo" | "no";
  instalado: boolean;
  recomendado: boolean;
  para: string;
};

/** GET /v1/setup/maquina: la radiografía de la computadora (chip, memoria, si hay
 *  Ollama, qué modelos hay y cuáles convienen, qué CLIs de IA están instalados).
 *  Es OPCIONAL: si el backend no lo trae, el asistente cae al camino de siempre
 *  con lo que ya sabe /v1/setup/estado. */
export type SetupMaquina = {
  equipo: { chip: string; so: string; ram_gb: number; memoria_ia_gb: number; arquitectura: string };
  ollama: { instalado: boolean; corriendo: boolean; version: string | null; ruta: string | null };
  modelos_instalados: { nombre: string; tam_gb: number }[];
  recomendados: ModeloRecomendado[];
  clis: {
    claude: { instalado: boolean; ruta: string | null };
    codex: { instalado: boolean; ruta: string | null };
  };
};

/** Un sondeo de la descarga de un modelo local. `pct` va de 0 a 100 mientras
 *  `estado` sea "descargando"; se acepta `porcentaje` por si el backend lo nombra
 *  así. Todo lo demás es opcional: solo se pinta lo que llegue. */
export type SetupModeloProgreso = {
  /** "desconocido" = nadie pidió esa descarga en esta sesión del servidor. */
  estado: "descargando" | "listo" | "error" | "desconocido" | string;
  porcentaje?: number | null;
  /** Lo que se le dice al dueño: "Bajando 3 de 5 partes", el motivo del error. */
  detalle?: string | null;
  /** Alias tolerantes por si el backend nombra distinto el mismo dato. */
  pct?: number | null;
  error?: string | null;
  mensaje?: string | null;
};

/** POST /v1/setup/red/buscar: una IA compartida en la red local (la computadora
 *  buena de la oficina sirviendo el modelo). Es POST porque barrer la red es una
 *  acción que el dueño pide, no algo que pase solo al abrir. */
export type ServidorIAEnRed = {
  ip: string;
  puerto: number;
  equipo: string;
  base_url: string;
  programa: string;
  modelos: string[];
  protegido: boolean;
};

export type SetupRed = {
  mi_ip: string | null;
  encontrados: ServidorIAEnRed[];
  aviso: string;
};

export type IntegrationFlow = "read" | "writeback" | "channel" | "confirm" | "action";

/** Una capacidad que una fuente provee (lo que el aiudante realmente usa). */
export type ProvidedCap = { cap: string; label: string; live: boolean };

/** La declaración de una conexión a la medida: URL, auth, paginación y mapeo. */
export type CustomConnectorConfig = {
  base_url: string;
  list_path?: string;
  root?: string;
  /** "" ninguna (o header legado) | header | bearer | query | basic | oauth2_cc */
  auth_type?: string;
  /** Nombre del header o del query param, según auth_type. */
  auth_header?: string;
  token_url?: string;
  client_id?: string;
  mapping: Record<string, string>;
  /** "" sin paginación | offset | cursor */
  paging?: string;
  page_param?: string;
  size_param?: string;
  page_size?: number;
  cursor_param?: string;
  cursor_path?: string;
  timeout?: number;
  retries?: number;
  pause_ms?: number;
  /** Escritura (inyección aiuda -> tu API): ruta del POST de alta y el path (con
   *  puntos) al id del registro creado en la respuesta. Vacíos = solo lectura. */
  write_path?: string;
  write_id_path?: string;
};

/** Conexión a la medida guardada (sin el secreto; has_secret dice si hay clave). */
export type CustomConnector = CustomConnectorConfig & {
  id: string;
  name: string;
  cap: string;
  has_secret: boolean;
  /** Semáforo honesto: último Probar y última corrida de ingesta. */
  last_test_at?: string;
  last_test_ok?: boolean;
  last_test_error?: string;
  last_sync_at?: string;
  last_error?: string;
  last_count?: number;
};
export type CustomConnectorTest = CustomConnectorConfig & { auth_value?: string };
/** Receta compartible (open core): la declaración sin secretos ni identidad. */
export type CustomReceta = CustomConnectorConfig & { receta: number; name: string; cap: string };
export type CustomTestResult = {
  ok: boolean;
  error: string | null;
  count: number;
  sample: Record<string, unknown>[];
};

/** Capacidad de negocio, independiente de la fuente que la cumple. */
export type Capability = {
  key: string;
  label: string;
  desc: string;
  live: boolean;
  providers: string[];
  connected: boolean;
};

export type IntegrationNode = {
  key: string;
  name: string;
  group: "canal" | "datos" | "fiscal" | "operacion";
  logo: string | null;
  color: string;
  flows: IntegrationFlow[];
  rol: string;
  live: boolean;
  does: string;
  connected: boolean;
  configured: boolean;
  /** Semáforo del último "Probar conexión": ok = pasó, error = falló, untested =
   *  configurado sin probar, null = ni configurado. */
  verified: "ok" | "error" | "untested" | null;
  last_test_at: string | null;
  last_error: string | null;
  records: number;
  detail: string | null;
  agents: string[];
  provides: ProvidedCap[];
};

export type SatEmpresa = {
  rfc: string;
  nombre: string;
  efirma: boolean;
  vigente_hasta: string | null;
  plazo_dias: number;
  sync: Record<
    "emitidas" | "recibidas",
    { ultima_fecha: string | null; solicitud_pendiente: boolean }
  >;
};

export type SatEstado = {
  empresas: SatEmpresa[];
  maximo: number;
  boveda: {
    total: number;
    emitidas: number;
    recibidas: number;
    intercompania: number;
    desconocida: number;
  };
  cartera: {
    por_empresa: { rfc: string; abiertas: number; total: number }[];
    todo_junto: { abiertas: number; total: number };
  };
};

export type SatCfdi = {
  uuid: string;
  tipo: string | null;
  metodo_pago: string | null;
  folio: string | null;
  fecha: string | null;
  rfc_emisor: string | null;
  nombre_emisor: string | null;
  rfc_receptor: string | null;
  nombre_receptor: string | null;
  total: number | null;
  moneda: string | null;
  direccion: string;
  source: string;
  invoice_id: string | null;
};

export type SatBoveda = {
  cfdis: SatCfdi[];
  count: number;
  suma_total: number;
};

export type SatImportResult = {
  nuevos: number;
  duplicados: number;
  facturas_creadas: number;
  facturas_vinculadas: number;
  pue_en_boveda: number;
  pagos_aplicados: number;
  egresos_aplicados: number;
  intercompania: number;
  avisos: string[];
};

export type IntegrationConfig = {
  key: string;
  configured: boolean;
  values: Record<string, string>;
};

/** Una capacidad que provee una fuente, con qué aiudante la usa y si está prendida. */
export type SourceCap = {
  cap: string;
  label: string;
  desc: string;
  live: boolean;
  enabled: boolean;
  toggleable: boolean;
  agents: { slug: string; name: string; avatar: string }[];
};

export type IntegrationDetail = {
  key: string;
  name: string;
  rol: string;
  does: string;
  live: boolean;
  connected: boolean;
  configured: boolean;
  logo: string | null;
  color: string;
  group?: string;
  // Aviso honesto cuando la vía no es la oficial (ej. WhatsApp por wacli/Evolution),
  // igual que el modo de suscripción del proveedor de IA. No bloquea: informa.
  warning?: string | null;
  capabilities: SourceCap[];
};

export type IntegrationAgent = {
  slug: string;
  name: string;
  role: string;
  avatar: string;
  active: boolean;
  systems: string[];
  needs: string[];
  gaps: string[];
};

export type IntegrationsGraph = {
  business_name: string;
  systems: IntegrationNode[];
  agents: IntegrationAgent[];
  capabilities: Capability[];
  connected_count: number;
  available_count: number;
};

export type AgentSystem = {
  key: string;
  name: string;
  group: string;
  logo: string | null;
  color: string;
  flows: IntegrationFlow[];
  rol: string;
  live: boolean;
  does: string;
  connected: boolean;
  provides: ProvidedCap[];
};

export type AgentSystems = {
  slug: string;
  name: string;
  role: string;
  avatar: string;
  systems: AgentSystem[];
  capabilities: Capability[];
  needs: string[];
  gaps: string[];
  connected_count: number;
};

// "codex" = OpenAI. Se conecta simétrico a Claude: API key (sk-...) o suscripción de ChatGPT.
// La suscripción se conecta por device code ("Iniciar sesión con ChatGPT"), sin pegar nada.
// "local" = un endpoint OpenAI-compatible en tu máquina (Ollama, LM Studio, vLLM):
// la única vía donde ningún dato sale de tu computadora.
// "claude_cli"/"codex_cli" (modo "cli") = el Claude Code o el Codex que el dueño YA
// tiene instalado y con su sesión iniciada. Se conecta con un clic: el secreto va
// vacío porque no hay ninguno que guardar, la sesión vive dentro del propio programa.
export type ProviderName = "claude" | "codex" | "local" | "claude_cli" | "codex_cli";
export type ProviderMode = "api_key" | "subscription" | "cli";

/** Arranque del device code de OpenAI: el código de un solo uso, la URL a abrir, el intervalo
 *  de sondeo (segundos) y la expiración (segundos, ~15 min). La consola sondea con estos. */
export type OpenaiDeviceStart = {
  device_code: string;
  user_code: string;
  verification_uri: string;
  interval: number;
  expires_in: number;
};

/** Un sondeo del device code: pendiente (sigue), listo (conectado + veredicto), o error. */
export type OpenaiDevicePoll =
  | { status: "pending" }
  | { status: "success"; name: ProviderName; mode: ProviderMode; connected: boolean; test: ProviderTest }
  | { status: "error"; detail: string };

/** Estado del proveedor de IA conectado (panel /proveedor). */
export type ProviderState = {
  name: ProviderName;
  mode: ProviderMode;
  connected: boolean;
  /** Hay una API key por variable de entorno aunque no se haya conectado en el panel. */
  env_fallback: boolean;
  /** Secreto enmascarado ("••••••") si hay uno guardado; "" si no. */
  secret: string;
  /** Solo proveedor "local": base_url y modelo (no son secretos, se editan sin re-capturar). */
  local_config?: { base_url: string; model: string };
};

/** Veredicto de la prueba de conexión REAL del proveedor (POST /v1/provider/test):
 *  una llamada mínima a Anthropic por el mismo camino que usa el motor. */
export type ProviderTest =
  | { ok: true; mode: ProviderMode; model: string; latency_ms: number }
  | { ok: false; mode?: ProviderMode; code: string; error: string };

// --- Aiuditas (catálogo capability-first) + ayudantes del dueño ---

export type PerillaTipo = "enum" | "numero" | "bool" | "texto" | "hora";

export type PerillaOpcion = { value: string; label: string };

export type Perilla = {
  key: string;
  label: string;
  tipo: PerillaTipo;
  default: string | number | boolean;
  ayuda: string;
  live: boolean;
  opciones?: PerillaOpcion[];
  minimo?: number;
  maximo?: number;
  unidad?: string;
  depende_de?: { key: string; valor: string };
};

/** Una fuente de datos posible para una capacidad (de dónde puede leer una aiudita).
 *  `live` = el motor ya jala de ahí hoy; si no, está "por conectar". */
export type Fuente = {
  key: string;
  name: string;
  logo: string | null;
  color: string;
  live: boolean;
  /** Fuente por CUA (Computer Use Agent): sin conector API, opera el portal web.
   *  Es elegible (a diferencia de "por conectar"), pero aún no ejecuta en local. */
  experimental?: boolean;
};

export type AiuditaSpec = {
  id: string;
  perfil: string;
  tool: string;
  label: string;
  linea: string;
  lectura: boolean;
  live: boolean;
  reglas_libres: boolean;
  /** Capacidad de negocio de la que lee (ej. "cuentas_por_cobrar"). "" si no lee datos. */
  capacidad: string;
  /** Fuentes posibles para esa capacidad. Aquí el dueño define DE DÓNDE lee. */
  fuentes?: Fuente[];
  perillas: Perilla[];
};

export type PerfilSpec = { slug: string; name: string; desc: string };

export type AiuditasCatalog = { perfiles: PerfilSpec[]; aiuditas: AiuditaSpec[] };

export type AyudanteAppearance = {
  color?: number;
  hair?: string;
  eyes?: string;
  mouth?: string;
  hat?: string;
  accessory?: string;
  symbol?: string;
};

/** Config de una aiudita: valores de perillas (+ "reglas" si aplica). */
export type AiuditaConfig = Record<string, string | number | boolean>;

export type AyudanteDTO = {
  id: string;
  name: string;
  appearance: AyudanteAppearance;
  /** Instrucciones/persona libres del dueño. Se inyectan bajo las reglas de fábrica. */
  instructions: string;
  /** { aiudita_id: config }. La presencia de la llave = activa. */
  aiuditas: Record<string, AiuditaConfig>;
  /** Trabajo real atribuido a este ayudante (derivado de filas, por estado). */
  acciones: { pendientes: number; enviadas: number; total: number };
  /** Plan de carrera: el nivel que suman esas acciones (lo calcula el backend). */
  nivel: Nivel;
  createdAt: string | null;
};

/** Resultado de correr un ayudante ahora: propuestas HITL, nada sale solo. */
export type CorridaAyudante = {
  /** Aiuditas que corrieron en batch. */
  corrio: string[];
  /** Aiuditas activas que no corren solas (trabajan en el chat o bajo demanda). */
  sin_corrida: string[];
  propuestas: number;
  pendientes?: number;
  detalle?: string;
};

/** Un "recado" de CUA: un ayudante que fue a un portal a buscar algo (headless). */
export type CuaMision = {
  id: string;
  capacidad: string;
  sistema: string;
  status: "queued" | "running" | "done" | "failed";
  resumen: string;
  data: Record<string, unknown>;
  steps: string[];
  error: string;
  evidencia_capturas: number;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** Capturas en base64 (data:image/png). Solo en el detalle. */
  evidencia?: string[];
};

/** Un portal del lanzador: built-in (SAT/banca/tribunal) o a la medida ("portal:<id>").
 *  Dice si ya tiene dirección y si su acceso (login) quedó conectado por el handoff. */
export type CuaCapacidad = {
  capacidad: string;
  sistema: string;
  objetivo: string;
  url: string;
  url_configurada: boolean;
  /** true = portal a la medida (se puede borrar); false = built-in. */
  editable: boolean;
  tiene_sesion: boolean;
  sesion_guardada_en: string | null;
};

/** Un portal a la medida que el dueño registró por URL. */
export type CuaPortal = {
  id: string;
  nombre: string;
  url: string;
  notas: string;
  creado: string | null;
};

/** Estado de un handoff de login vivo: el dueño entrando al portal en una ventana. */
export type CuaSesionHandoff = {
  id: string;
  capacidad: string;
  sistema: string;
  url: string;
  estado:
    | "abriendo"
    | "esperando"
    | "guardando"
    | "guardado"
    | "cancelado"
    | "expirado"
    | "error";
  detalle: string;
};

/** Estado honesto de la oficina: si ESTE servidor tiene el navegador del asistente
 *  (extra `cua` + Chromium) y si el negocio tiene credencial de IA. Sin ambos, las
 *  tareas quedan en "No pudo" con la razón; la UI lo avisa antes de encolar.
 *  `handoff_posible`: ¿esta máquina puede abrir una ventana para que el dueño entre? */
export type CuaEstado = {
  navegador_listo: boolean;
  navegador_detalle: string;
  credencial_ia: boolean;
  listo: boolean;
  handoff_posible: boolean;
  handoff_detalle: string;
};

/** Una tarea de portal guardada con nombre para re-correrla con un clic. Vive en
 *  tenant.config (sin tabla propia). Correrla = cuaEncolar(capacidad, instruccion). */
export type RutinaBackoffice = {
  id: string;
  nombre: string;
  capacidad: string;
  sistema: string;
  instruccion: string;
  creado: string | null;
};

/** Qué está aprendiendo un agente de las correcciones del dueño. */
export type LearningSummary = {
  total: number;
  approved: number;
  edited: number;
  rejected: number;
  tasaSinEditar: number | null;
  recientes: { original: string; final: string; createdAt: string | null }[];
};

export const api = {
  integrations: () => request<IntegrationsGraph>("/v1/integrations"),
  satEstado: () => request<SatEstado>("/v1/sat/estado"),
  satBoveda: (filtros?: { rfc?: string; direccion?: string }) => {
    const params = new URLSearchParams();
    if (filtros?.rfc) params.set("rfc", filtros.rfc);
    if (filtros?.direccion) params.set("direccion", filtros.direccion);
    const query = params.toString();
    return request<SatBoveda>(`/v1/sat/boveda${query ? `?${query}` : ""}`);
  },
  satAgregarEmpresa: (body: { rfc: string; nombre?: string; plazo_dias: number }) =>
    request<{ empresas: SatEmpresa[]; maximo: number }>("/v1/sat/empresas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  satCambiarEmpresa: (rfc: string, body: { nombre?: string; plazo_dias?: number }) =>
    request<{ empresas: SatEmpresa[]; maximo: number }>(
      `/v1/sat/empresas/${encodeURIComponent(rfc)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  satQuitarEmpresa: (rfc: string) =>
    request<{ empresas: SatEmpresa[]; maximo: number }>(
      `/v1/sat/empresas/${encodeURIComponent(rfc)}`,
      { method: "DELETE" },
    ),
  satConectarEfirma: (form: FormData) =>
    request<{ empresa: SatEmpresa; maximo: number }>("/v1/sat/efirma", {
      method: "POST",
      body: form,
    }),
  satProbarEfirma: (rfc: string) =>
    request<{ ok: boolean; rfc: string; mensaje: string }>(
      `/v1/sat/efirma/${encodeURIComponent(rfc)}/probar`,
      { method: "POST" },
    ),
  satBorrarEfirma: (rfc: string) =>
    request<{ empresas: SatEmpresa[]; maximo: number }>(
      `/v1/sat/efirma/${encodeURIComponent(rfc)}`,
      { method: "DELETE" },
    ),
  satImportar: (form: FormData) =>
    request<SatImportResult>("/v1/sat/importar", { method: "POST", body: form }),
  agentSystems: (slug: string) => request<AgentSystems>(`/v1/agents/${slug}/systems`),
  // Conexiones a la medida (conector genérico por API): campos por necesidad, probar en vivo,
  // guardar (secreto cifrado en el backend), listar y borrar.
  customConnectorFields: () =>
    request<{ cap_fields: Record<string, string[]>; default: string[] }>("/v1/custom-connectors/fields"),
  listCustomConnectors: () => request<CustomConnector[]>("/v1/custom-connectors"),
  testCustomConnector: (body: CustomConnectorTest) =>
    request<CustomTestResult>("/v1/custom-connectors/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createCustomConnector: (body: CustomConnectorTest & { name: string; cap: string }) =>
    request<CustomConnector>("/v1/custom-connectors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Editar: la clave solo se reemplaza si auth_value viene con algo; vacía = se conserva.
  updateCustomConnector: (id: string, body: CustomConnectorTest & { name: string; cap: string }) =>
    request<CustomConnector>(`/v1/custom-connectors/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Re-probar una conexión guardada con su clave cifrada. Sin body prueba lo guardado;
  // con body prueba lo que estás editando (y usa la clave guardada si no mandas una).
  retestCustomConnector: (id: string, body?: CustomConnectorTest) =>
    request<CustomTestResult>(`/v1/custom-connectors/${id}/test`, {
      method: "POST",
      ...(body
        ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
        : {}),
    }),
  exportCustomConnector: (id: string) =>
    request<CustomReceta>(`/v1/custom-connectors/${id}/receta`),
  importCustomConnector: (receta: Record<string, unknown>) =>
    request<CustomConnector>("/v1/custom-connectors/importar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ receta }),
    }),
  deleteCustomConnector: (id: string) =>
    request<{ ok: boolean }>(`/v1/custom-connectors/${id}`, { method: "DELETE" }),
  integrationConfig: (key: string) =>
    request<IntegrationConfig>(`/v1/integrations/${key}/config`),
  integrationDetail: (key: string) =>
    request<IntegrationDetail>(`/v1/integrations/${key}`),
  setIntegrationCapabilities: (key: string, disabled: string[]) =>
    request<{ key: string; disabled: string[] }>(`/v1/integrations/${key}/capabilities`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    }),
  saveIntegration: (key: string, values: Record<string, string>) =>
    request<{ key: string; configured: boolean; connected: boolean }>(
      `/v1/integrations/${key}/config`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      },
    ),
  disconnectIntegration: (key: string) =>
    request<{ key: string; configured: boolean; connected: boolean }>(
      `/v1/integrations/${key}/config`,
      { method: "DELETE" },
    ),
  provider: () => request<ProviderState>("/v1/provider"),
  saveProvider: (name: ProviderName, mode: ProviderMode, secret: string) =>
    request<{ name: ProviderName; mode: ProviderMode; connected: boolean }>("/v1/provider", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, mode, secret }),
    }),
  disconnectProvider: () =>
    request<{ connected: boolean; env_fallback: boolean }>("/v1/provider", { method: "DELETE" }),
  testProvider: () => request<ProviderTest>("/v1/provider/test", { method: "POST" }),
  // OpenAI por SUSCRIPCIÓN, sin pegar nada: device code ("Iniciar sesión con ChatGPT"). start
  // pide el código; la consola muestra el código + la URL y sondea poll según el intervalo
  // hasta que el dueño autorice en su navegador. Al autorizar, el backend canjea, prueba y
  // guarda el bundle CIFRADO por tenant. El bundle nunca toca el navegador.
  startOpenaiDevice: () =>
    request<OpenaiDeviceStart>("/v1/provider/openai/device/start", { method: "POST" }),
  pollOpenaiDevice: (deviceCode: string, userCode: string) =>
    request<OpenaiDevicePoll>("/v1/provider/openai/device/poll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: deviceCode, user_code: userCode }),
    }),
  // OpenAI pegando el auth.json (fallback de power-user/self-host): el dueño corre `codex
  // login` en SU máquina y pega el contenido; el bundle se guarda CIFRADO por tenant. Sin
  // pegar nada, en self-host de una máquina el backend lee la sesión local. authJson opcional.
  connectOpenai: (authJson?: string) =>
    request<{ name: ProviderName; mode: ProviderMode; connected: boolean; test: ProviderTest }>(
      "/v1/provider/openai/connect",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(authJson ? { auth_json: authJson } : {}),
      },
    ),
  testIntegration: (key: string) =>
    request<{ ok: boolean | null; message: string; details?: Record<string, number | string> }>(
      `/v1/integrations/${key}/test`,
      { method: "POST" },
    ),
  whatsappQr: () => request<{ connected: boolean; qr: string | null }>("/v1/integrations/whatsapp/qr", { method: "POST" }),
  whatsappStatus: () => request<{ connected: boolean }>("/v1/integrations/whatsapp/status"),
  whatsappLogout: () => request<{ connected: boolean }>("/v1/integrations/whatsapp/session", { method: "DELETE" }),
  workspace: () => request<WorkspaceInfo>("/v1/workspace"),
  // Activación: progreso derivado del estado real (no flags persistidos). Lo
  // consume el bloque "Primeros pasos" del Resumen.
  onboardingState: () => request<OnboardingState>("/v1/onboarding/state"),
  // Primer arranque: qué encontró aiuda en la computadora y qué falta para trabajar.
  // Los aparatos del dueño y la puerta que da a la red de la oficina. El QR se
  // arma con lo que devuelve `crearInvitacion`; el token completo del aparato
  // solo lo ve el teléfono que lo canjea.
  redLocal: () => request<RedLocal>("/v1/red-local"),
  cambiarRedLocal: (prendida: boolean) =>
    request<RedLocal>("/v1/red-local", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prendida }),
    }),
  dispositivos: () => request<{ dispositivos: Dispositivo[] }>("/v1/dispositivos"),
  crearInvitacion: (papel: "dueno" | "invitado", tope?: number | null) =>
    request<Invitacion>("/v1/dispositivos/invitacion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ papel, tope_aprobacion: tope ?? null }),
    }),
  cancelarInvitacion: () =>
    request<{ cancelada: boolean }>("/v1/dispositivos/invitacion", { method: "DELETE" }),
  cambiarDispositivo: (id: string, cambio: Partial<Pick<Dispositivo, "nombre" | "papel" | "tope_aprobacion">>) =>
    request<Dispositivo>(`/v1/dispositivos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cambio),
    }),
  revocarDispositivo: (id: string) =>
    request<Dispositivo>(`/v1/dispositivos/${id}/revocar`, { method: "POST" }),
  setupEstado: () => request<SetupEstado>("/v1/setup/estado"),
  setupNegocio: (nombre: string, telefono?: string) =>
    request<{ nombre: string }>("/v1/setup/negocio", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, telefono }),
    }),
  setupTerminar: () => request<{ terminado: boolean }>("/v1/setup/terminar", { method: "POST" }),
  // Radiografía de la máquina + descarga de un modelo local, para que el paso de
  // la IA proponga modelos que SÍ caben aquí. Si el backend todavía no las trae,
  // el asistente atrapa el error y sigue con el camino de siempre.
  setupMaquina: () => request<SetupMaquina>("/v1/setup/maquina"),
  setupDescargarModelo: (modelo: string) =>
    request<{ modelo: string }>("/v1/setup/modelo/descargar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo }),
    }),
  setupProgresoModelo: (modelo: string) =>
    request<SetupModeloProgreso>(
      `/v1/setup/modelo/progreso?modelo=${encodeURIComponent(modelo)}`,
    ),
  // Buscar una IA compartida en la red local. Tarda unos segundos (barrido de la
  // subred); la UI debe mostrar que está buscando.
  setupBuscarEnRed: () => request<SetupRed>("/v1/setup/red/buscar", { method: "POST" }),
  profile: () => request<Profile>("/v1/profile"),
  saveProfile: (body: Profile) =>
    request<Profile>("/v1/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  search: (q: string) => request<SearchResponse>(`/v1/search?q=${encodeURIComponent(q)}`),
  shadowMode: () => request<{ modo_sombra: boolean }>("/v1/settings/modo-sombra"),
  setShadowMode: (activo: boolean) =>
    request<{ modo_sombra: boolean }>("/v1/settings/modo-sombra", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activo }),
    }),
  ventanaEnvio: () => request<{ ventana: string }>("/v1/settings/ventana-envio"),
  setVentanaEnvio: (ventana: string) =>
    request<{ ventana: string }>("/v1/settings/ventana-envio", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ventana }),
    }),
  setCustomerOptOut: (id: string, activo: boolean) =>
    request<{ opt_out: { at: string; via: string } | null }>(`/v1/customers/${id}/optout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activo }),
    }),
  activateWhatsappCloud: () =>
    request<{ via: string; instance: string }>("/v1/integrations/whatsapp-cloud/activate", {
      method: "POST",
    }),
  cartera: () => request<Cartera>("/v1/cartera"),
  reminders: (status = "pending_approval") =>
    request<ReminderItem[]>(`/v1/reminders?status=${status}`),
  invoices: (status = "open") => request<InvoiceItem[]>(`/v1/invoices?status=${status}`),
  invoiceDetail: (id: string) => request<InvoiceDetail>(`/v1/invoices/${id}`),
  writeback: (filtro: { invoice_id?: string; customer_id?: string }) => {
    const params = new URLSearchParams();
    if (filtro.invoice_id) params.set("invoice_id", filtro.invoice_id);
    if (filtro.customer_id) params.set("customer_id", filtro.customer_id);
    return request<{ entries: WritebackEntry[] }>(`/v1/writeback?${params.toString()}`);
  },
  retryWriteback: (id: string) =>
    request<WritebackEntry>(`/v1/writeback/${id}/retry`, { method: "POST" }),
  promises: (status = "active") => request<PromiseItem[]>(`/v1/promises?status=${status}`),
  customers: (kind?: "cliente" | "prospecto") =>
    request<CustomerItem[]>(kind ? `/v1/customers?kind=${kind}` : "/v1/customers"),
  objectSource: (tipo: "clientes" | "productos" | "facturas" | "citas") =>
    request<{
      tipo: string;
      source: string | null;
      source_label: string | null;
      new_url: string | null;
      native: boolean;
    }>(`/v1/objects/${tipo}/source`),
  products: () => request<ProductItem[]>("/v1/products"),
  createQuote: (body: {
    customer_id: string;
    items: { product_id: string; cantidad: number }[];
    descuento_pct?: number;
  }) =>
    request<{ id: string; title: string; message: string; status: string }>("/v1/quotes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Prospección con DENUE · INEGI: buscar no guarda nada; importar carga la
  // selección como prospectos con procedencia denue, sin duplicar la cartera.
  prospeccionFuente: () => request<ProspeccionFuente>("/v1/prospeccion/fuente"),
  prospeccionBuscar: (body: { condicion: string; lat: number; lng: number; radio_m: number }) =>
    request<ProspeccionBusqueda>("/v1/prospeccion/buscar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  prospeccionImportar: (negocios: Omit<NegocioDenue, "contactable" | "ya_registrado" | "cliente_id">[]) =>
    request<ProspeccionImport>("/v1/prospeccion/importar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ negocios }),
    }),
  appointments: () => request<AppointmentItem[]>("/v1/appointments"),
  // --- Altas directas + inyección a maestros ------------------------------
  // aiuda captura rápido (source="aiuda") y, con inyectar_a (+ conexion_id si el
  // destino es una conexión a la medida), el alta viaja también al maestro
  // elegido. Los 409/422 traen detail legible en español: se muestra tal cual.
  createCustomer: (body: {
    name: string;
    phone?: string;
    email?: string;
    kind?: "cliente" | "prospecto";
    inyectar_a?: string;
    conexion_id?: string;
  }) =>
    request<{
      id: string;
      name: string;
      phone: string | null;
      email: string | null;
      kind: string;
      inyeccion: InyeccionEncolada;
    }>("/v1/customers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createProduct: (body: {
    name: string;
    sku?: string;
    price?: number;
    stock?: number;
    unit?: string;
    inyectar_a?: string;
    conexion_id?: string;
  }) =>
    request<{
      id: string;
      name: string;
      sku: string | null;
      price: number | null;
      inyeccion: InyeccionEncolada;
    }>("/v1/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Inyectada a Odoo, la factura llega como BORRADOR: se revisa y timbra allá.
  createInvoice: (body: {
    customer_id: string;
    folio: string;
    amount: number;
    issued_date?: string;
    due_date: string;
    currency?: string;
    concepto?: string;
    inyectar_a?: string;
    conexion_id?: string;
  }) =>
    request<{
      id: string;
      folio: string;
      amount: number;
      customer: string;
      status: string;
      inyeccion: InyeccionEncolada;
    }>("/v1/invoices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createAppointment: (body: {
    title: string;
    starts_at?: string;
    customer_name?: string;
    customer_phone?: string;
    notes?: string;
    inyectar_a?: string;
    conexion_id?: string;
  }) =>
    request<{ id: string; title: string; starts_at: string | null; inyeccion: InyeccionEncolada }>(
      "/v1/appointments",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  // Pago registrado a mano: entra a la bandeja de conciliación como cualquier
  // depósito (el ayudante propone, tú confirmas). invoice_id es solo una pista.
  createPayment: (body: {
    amount: number;
    paid_at?: string;
    reference?: string;
    counterparty?: string;
    invoice_id?: string;
  }) =>
    request<{ id: string; amount: number; paid_at: string; status: string }>("/v1/payments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  inyectarDestinos: () => request<InyectarDestinos>("/v1/inyectar/destinos"),
  // Empuja un registro que ya vive en aiuda al maestro elegido (botón de la
  // ficha). 409 si ya vive allá, 422 si la conexión no escribe — detail legible.
  inyectar: (body: { entidad: EntidadInyectable; id: string; target: string; conexion_id?: string }) =>
    request<InyeccionEncolada>("/v1/inyectar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  customerDetail: (id: string) => request<CustomerDetail>(`/v1/customers/${id}`),
  tags: () => request<Tag[]>("/v1/tags"),
  createTag: (name: string, color?: string) =>
    request<Tag>("/v1/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, color }),
    }),
  updateTag: (id: string, body: { name?: string; color?: string }) =>
    request<Tag>(`/v1/tags/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteTag: (id: string) => request<{ removed: string }>(`/v1/tags/${id}`, { method: "DELETE" }),
  setCustomerTags: (id: string, tags: string[]) =>
    request<{ id: string; tags: string[] }>(`/v1/customers/${id}/tags`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    }),
  editCustomer: (
    id: string,
    body: { name?: string; email?: string; phone?: string; meta?: Record<string, string> },
  ) =>
    request<{ id: string; name: string; phone: string | null; email: string | null; writeback: string[] }>(
      `/v1/customers/${id}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  messageCustomer: (id: string, body: string) =>
    request<ChatMessage>(`/v1/customers/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }),
  // Adjuntar PDF/imagen y mandarlo por WhatsApp. multipart: NO fijar Content-Type
  // (el navegador pone el boundary).
  attachToCustomer: (id: string, file: File, caption: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("caption", caption);
    return request<ChatMessage>(`/v1/customers/${id}/attachments`, { method: "POST", body: fd });
  },
  conversations: () => request<ConversationItem[]>("/v1/conversations"),
  conversation: (id: string) => request<ConversationDetail>(`/v1/conversations/${id}`),
  // Bandeja unificada: descartar ruido, deshacer, y ligar un desconocido dándolo de alta.
  dismissConversation: (id: string) =>
    request<{ status: string }>(`/v1/conversations/${id}/dismiss`, { method: "POST" }),
  undismissConversation: (id: string) =>
    request<{ status: string }>(`/v1/conversations/${id}/undismiss`, { method: "POST" }),
  registrarClienteConversacion: (
    id: string,
    opts?: { name?: string; linkCustomerId?: string },
  ) =>
    request<{ id: string; name: string; created: boolean; linked?: boolean }>(
      `/v1/conversations/${id}/registrar-cliente`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: opts?.name ?? null,
          link_customer_id: opts?.linkCustomerId ?? null,
        }),
      },
    ),
  usage: () => request<UsageSummary>("/v1/usage"),
  approve: (id: string, channel = "whatsapp", message?: string) =>
    // La respuesta dice el estado FINAL honesto: delivery "encolado" (canal listo, el
    // envío corre en segundo plano) o "pendiente_canal" (aprobado; `aviso` trae el
    // "se enviará cuando conectes…" para el toast).
    request<{
      id: string;
      status: string;
      channel: string;
      delivery: "encolado" | "pendiente_canal";
      aviso: string | null;
    }>(`/v1/reminders/${id}/approve?channel=${encodeURIComponent(channel)}`, {
      method: "POST",
      ...(message !== undefined
        ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) }
        : {}),
    }),
  reject: (id: string) => request(`/v1/reminders/${id}/reject`, { method: "POST" }),
  // Reenvía un aprobado que quedó varado (sombra apagada después de aprobarlo, o el
  // envío en segundo plano no completó). No re-aprueba: approved→approved no es válido.
  sendReminder: (id: string) => request(`/v1/reminders/${id}/send`, { method: "POST" }),
  learningSummary: (agent = "mariana") =>
    request<LearningSummary>(`/v1/learning/summary?agent=${encodeURIComponent(agent)}`),
  pay: (invoiceId: string) => request(`/v1/invoices/${invoiceId}/pay`, { method: "POST" }),
  remind: (invoiceId: string) =>
    request<{ id: string; status: string; message: string }>(
      `/v1/invoices/${invoiceId}/remind`,
      { method: "POST" },
    ),
  fulfill: (promiseId: string) =>
    request(`/v1/promises/${promiseId}/fulfill`, { method: "POST" }),
  reconciliation: () => request<ReconcileBandeja>("/v1/reconciliation"),
  // Acepta una factura o varias (un pago puede liquidar un grupo).
  confirmReconcile: (paymentId: string, invoiceIds: string | string[]) =>
    request<{
      id: string;
      status: string;
      invoice: { id: string; folio: string; status: string };
      invoices: (ReconcileAplicacion & { status: string })[];
      excedente: number;
    }>(`/v1/reconciliation/${paymentId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        invoice_ids: Array.isArray(invoiceIds) ? invoiceIds : [invoiceIds],
      }),
    }),
  ignoreReconcile: (paymentId: string) =>
    request<{ id: string; status: string }>(`/v1/reconciliation/${paymentId}/ignore`, {
      method: "POST",
    }),
  reconcileResueltos: () =>
    request<{ resueltos: ReconcileResuelto[]; count: number }>("/v1/reconciliation/resueltos"),
  reconcileConfig: () => request<ReconcileConfig>("/v1/reconciliation/config"),
  saveReconcileConfig: (body: ReconcileConfig) =>
    request<ReconcileConfig>("/v1/reconciliation/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  aiuditasCatalog: () => request<AiuditasCatalog>("/v1/aiuditas/catalog"),
  ayudantes: () => request<AyudanteDTO[]>("/v1/ayudantes"),
  createAyudante: (body: { name: string; appearance?: AyudanteAppearance; aiuditas?: string[] }) =>
    request<AyudanteDTO>("/v1/ayudantes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateAyudante: (
    id: string,
    body: { name?: string; appearance?: AyudanteAppearance; instructions?: string },
  ) =>
    request<AyudanteDTO>(`/v1/ayudantes/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  ayudantePrompt: (id: string) =>
    request<{ system: string }>(`/v1/ayudantes/${id}/prompt`),
  cuaEstado: () => request<CuaEstado>("/v1/cua/estado"),
  cuaCapacidades: () => request<CuaCapacidad[]>("/v1/cua/capacidades"),
  cuaMisiones: () => request<CuaMision[]>("/v1/cua/misiones"),
  cuaMision: (id: string) => request<CuaMision>(`/v1/cua/misiones/${id}`),
  cuaEncolar: (capacidad: string, instruccion?: string) =>
    request<CuaMision>("/v1/cua/misiones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capacidad, instruccion }),
    }),
  cuaRutinas: () => request<RutinaBackoffice[]>("/v1/cua/rutinas"),
  cuaGuardarRutina: (body: { nombre: string; capacidad: string; instruccion?: string }) =>
    request<RutinaBackoffice>("/v1/cua/rutinas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  cuaBorrarRutina: (id: string) =>
    request<void>(`/v1/cua/rutinas/${id}`, { method: "DELETE" }),
  // Portales a la medida (registrar por URL) y direcciones de los built-in.
  cuaPortales: () => request<CuaPortal[]>("/v1/cua/portales"),
  cuaCrearPortal: (body: { nombre: string; url: string; notas?: string }) =>
    request<CuaPortal>("/v1/cua/portales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  cuaBorrarPortal: (id: string) =>
    request<void>(`/v1/cua/portales/${id}`, { method: "DELETE" }),
  cuaSetUrlBuiltin: (capacidad: string, url: string) =>
    request<CuaCapacidad>(`/v1/cua/portales/builtin/${capacidad}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  // Handoff de login: el dueño entra al portal en una ventana; su sesión se guarda cifrada.
  cuaIniciarSesion: (capacidad: string) =>
    request<CuaSesionHandoff>("/v1/cua/sesion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capacidad }),
    }),
  cuaEstadoSesion: (id: string) =>
    request<CuaSesionHandoff>(`/v1/cua/sesion/${id}`),
  cuaConfirmarSesion: (id: string) =>
    request<CuaSesionHandoff>(`/v1/cua/sesion/${id}/confirmar`, { method: "POST" }),
  cuaCancelarSesion: (id: string) =>
    request<CuaSesionHandoff>(`/v1/cua/sesion/${id}/cancelar`, { method: "POST" }),
  cuaOlvidarSesion: (capacidad: string) =>
    request<void>("/v1/cua/sesion/olvidar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capacidad }),
    }),
  deleteAyudante: (id: string) =>
    request<void>(`/v1/ayudantes/${id}`, { method: "DELETE" }),
  /** Corre el ayudante ahora: deja propuestas (HITL) en el Centro, atribuidas a él. */
  correrAyudante: (id: string) =>
    request<CorridaAyudante>(`/v1/ayudantes/${id}/correr`, { method: "POST" }),
  ayudante: (id: string) => request<AyudanteDTO>(`/v1/ayudantes/${id}`),
  setAiudita: (id: string, aiuditaId: string, config: AiuditaConfig) =>
    request<AyudanteDTO>(`/v1/ayudantes/${id}/aiuditas/${aiuditaId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  removeAiudita: (id: string, aiuditaId: string) =>
    request<AyudanteDTO>(`/v1/ayudantes/${id}/aiuditas/${aiuditaId}`, { method: "DELETE" }),
  ayudanteChat: (id: string, message: string, history: { role: string; body: string }[]) =>
    request<{ reply: string }>(`/v1/ayudantes/${id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    }),
  agents: () => request<AgentState[]>("/v1/agents"),
  agentChat: (slug: string, message: string, history: { role: string; body: string }[]) =>
    request<{ reply: string }>(`/v1/agents/${slug}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    }),
  activateAgent: (slug: string) => request(`/v1/agents/${slug}/activate`, { method: "POST" }),
  deactivateAgent: (slug: string) =>
    request(`/v1/agents/${slug}/deactivate`, { method: "POST" }),
  agentConfig: (slug: string) => request<AgentConfig>(`/v1/agents/${slug}/config`),
  saveAgentConfig: (slug: string, body: Partial<AgentConfig>) =>
    request<AgentConfig>(`/v1/agents/${slug}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  takeover: (conversationId: string, takeover: boolean) =>
    request(`/v1/conversations/${conversationId}/takeover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ takeover }),
    }),
  sendHumanMessage: (conversationId: string, body: string) =>
    request<{ id: string; delivered?: boolean; delivery_error?: string | null }>(
      `/v1/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      },
    ),
  resendMessage: (conversationId: string, messageId: string) =>
    request<{ id: string; delivery: string }>(
      `/v1/conversations/${conversationId}/messages/${messageId}/resend`,
      { method: "POST" },
    ),
  sync: () =>
    request<{
      pedidos_importados: number;
      pagos_confirmados: string[];
      fuentes: string[];
      /** Fuentes que no respondieron o leyeron parcial: se dice, no se esconde. */
      avisos: string[];
    }>("/v1/sync", { method: "POST" }),
  // Exporta la lista como xlsx respetando los filtros activos de la página
  // (facturas: status|bucket|q · clientes/prospectos: q|tag · promesas: status|q).
  exportXlsx: (entidad: ExportEntidad, filtros?: Record<string, string | null | undefined>) => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filtros ?? {})) if (v) params.set(k, v);
    const qs = params.toString();
    return requestBlob(`/v1/export/${entidad}.xlsx${qs ? `?${qs}` : ""}`);
  },
  importFile: (file: globalThis.File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportResult>("/v1/import", { method: "POST", body: form });
  },
  analyzeImport: (file: globalThis.File, entity?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (entity) form.append("entity", entity);
    return request<ImportAnalysis>("/v1/import/analyze", { method: "POST", body: form });
  },
  commitImport: (
    file: globalThis.File,
    entity: string,
    mapping: Record<string, string>,
    extras: string[],
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("entity", entity);
    form.append("mapping", JSON.stringify(mapping));
    form.append("extras", JSON.stringify(extras));
    return request<ImportResult>("/v1/import/commit", { method: "POST", body: form });
  },
  // Estado de cuenta bancario (PDF): paso 1, la previa (no escribe nada).
  analizarBanco: (file: globalThis.File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BancoAnalisis>("/v1/banco/analizar", { method: "POST", body: form });
  },
  // Paso 2: el dueño aprobó la previa; los depósitos entran a conciliación.
  importarBanco: (previa: BancoAnalisis) =>
    request<BancoImportResult>("/v1/banco/importar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(previa),
    }),
};

/** Un movimiento leído del estado de cuenta (cargo o abono, nunca ambos). */
export type BancoMovimiento = {
  fecha: string;
  concepto: string;
  referencia: string;
  cargo: number | null;
  abono: number | null;
};

/** La previa del estado de cuenta: qué se leyó, cómo y si cuadra. */
export type BancoAnalisis = {
  archivo: string;
  banco: string;
  /** banorte | bbva (parseo directo, sin IA) | ia (lo leyó la IA del dueño). */
  metodo: string;
  moneda: string;
  periodo_inicio: string | null;
  periodo_fin: string | null;
  periodo: string;
  saldo_inicial: number | null;
  saldo_final: number | null;
  cuadra: boolean;
  diferencia: number;
  depositos: { n: number; total: number };
  retiros: { n: number; total: number };
  movimientos: BancoMovimiento[];
  avisos: string[];
};

export type BancoImportResult = {
  creados: number;
  omitidos: number;
  cargos_ignorados: number;
  banco: string;
  periodo: string;
};

export const mxn = (value: number) =>
  value.toLocaleString("es-MX", { style: "currency", currency: "MXN" });

// Antigüedad de cartera: única fuente de verdad para etiqueta, color de badge (fg/bg)
// y color de la barra (bar). No redefinir estos tramos en las páginas.
export const BUCKET_META: Record<string, { label: string; fg: string; bg: string; bar: string }> = {
  por_vencer: { label: "Por vencer", fg: "text-ink-2", bg: "bg-line/50", bar: "bg-ok" },
  vence_pronto: { label: "Vence pronto", fg: "text-accent-ink", bg: "bg-accent-soft", bar: "bg-accent" },
  vencida_reciente: { label: "Vencida 1–15 d", fg: "text-warn", bg: "bg-warn-soft", bar: "bg-warn" },
  vencida: { label: "Vencida 16–45 d", fg: "text-warn-strong", bg: "bg-warn-strong-soft", bar: "bg-warn-strong" },
  critica: { label: "Vencida +45 d", fg: "text-danger", bg: "bg-danger-soft", bar: "bg-danger" },
  // No es antigüedad de cartera: es una respuesta de correo propuesta por el
  // ayudante que espera tu aprobación (misma pill en el Centro).
  respuesta_correo: { label: "Respuesta de correo", fg: "text-accent-ink", bg: "bg-accent-soft", bar: "bg-accent" },
};

export const TONE_LABEL: Record<string, string> = {
  amable: "amable",
  amable_directo: "amable directo",
  firme: "firme",
  urgente_escalado: "escalado a humano",
  comercial: "comercial",
};

// De dónde entró un PAGO en conciliación. Ojo: es OTRO dominio que SOURCE_LABEL
// (procedencia de un registro, en components/ui) — no confundir los dos.
export const CONCILIACION_ORIGEN: Record<string, string> = {
  banco: "Banco",
  stripe: "Stripe",
  manual: "Manual",
  reportado: "Reportado",
};
