// FUENTE ÚNICA de los destinos de la consola y de sus nombres.
//
// El menú, el buscador y el Rastro salen de aquí. Antes cada uno traía su lista y
// el mismo lugar se llamaba distinto según por dónde entraras ("Tu IA" en el menú,
// "Proveedor de IA" en el buscador). Un destino nuevo se agrega en DESTINOS y
// aparece con el mismo nombre en los tres lados.
//
// La consola es export estático: no hay segmentos dinámicos, las pestañas y las
// secciones van por query (`/facturas?vista=pagos`, `/configuracion?seccion=ia`).

/** Oficios que abren renglones del menú: sin un ayudante que haga ese trabajo, su
 *  pantalla no tiene nada que enseñar. */
export type Oficio = "ventas" | "recepcion";

export type Destino = {
  /** A dónde lleva, con su query si es una pestaña o una sección. */
  href: string;
  /** El nombre en pantalla. Uno solo por destino, en todos lados. */
  label: string;
  /** La puerta del menú bajo la que vive (su href). Un renglón del menú se apunta
   *  a sí mismo. `null`: no enciende ningún renglón. */
  puerta: string | null;
  /** Renglón del menú, en este orden. */
  menu?: true;
  /** Icono del menú (llave de ICONS en components/sidebar.tsx). */
  icono?: string;
  /** Solo existe si hay un ayudante de este oficio. */
  si?: Oficio;
  /** Otras palabras con las que alguien lo buscaría: el nombre que tuvo antes o lo
   *  que hay adentro. Nunca se pintan, solo sirven para encontrar. */
  claves?: string;
  /** Sale de la consola (el manual es una página aparte): navegación completa. */
  fuera?: true;
};

const DESTINOS: Destino[] = [
  // ── El menú ───────────────────────────────────────────────────────────────
  {
    href: "/",
    label: "Hoy",
    puerta: "/",
    menu: true,
    icono: "hoy",
    claves: "inicio por aprobar pendientes aprobaciones centro de mando resumen tablero no salio",
  },
  {
    href: "/facturas",
    label: "Cartera",
    puerta: "/facturas",
    menu: true,
    icono: "cartera",
    claves: "facturas por cobrar vencido cobranza saldo",
  },
  {
    href: "/conversaciones",
    label: "Mensajes",
    puerta: "/conversaciones",
    menu: true,
    icono: "mensajes",
    claves: "conversaciones whatsapp chats hilos respuestas",
  },
  { href: "/clientes", label: "Clientes", puerta: "/clientes", menu: true, icono: "clientes", claves: "etiquetas contactos" },
  {
    href: "/ayudantes",
    label: "Ayudantes",
    puerta: "/ayudantes",
    menu: true,
    icono: "ayudantes",
    claves: "equipo tu equipo aiuditas crear ayudante",
  },
  {
    href: "/productos",
    label: "Productos",
    puerta: "/productos",
    menu: true,
    icono: "productos",
    si: "ventas",
    claves: "catalogo precios cotizaciones",
  },
  {
    href: "/citas",
    label: "Agenda",
    puerta: "/citas",
    menu: true,
    icono: "agenda",
    si: "recepcion",
    claves: "citas calendario",
  },
  {
    href: "/configuracion",
    label: "Ajustes",
    puerta: "/configuracion",
    menu: true,
    icono: "ajustes",
    claves: "configuracion general preferencias",
  },

  // ── Pestañas de Cartera ───────────────────────────────────────────────────
  {
    href: "/facturas?vista=promesas",
    label: "Promesas",
    puerta: "/facturas",
    claves: "promesas de pago compromisos",
  },
  {
    href: "/facturas?vista=pagos",
    label: "Pagos",
    puerta: "/facturas",
    claves: "conciliacion banco estado de cuenta movimientos depositos",
  },
  {
    href: "/sat",
    label: "SAT",
    puerta: "/facturas",
    claves: "traer del sat cfdi boveda fiscal xml efirma facturas",
  },

  // ── Secciones de Ajustes ──────────────────────────────────────────────────
  {
    href: "/configuracion?seccion=negocio",
    label: "Negocio",
    puerta: "/configuracion",
    claves: "nombre del negocio datos modo de prueba",
  },
  {
    href: "/configuracion?seccion=conexiones",
    label: "Conexiones",
    puerta: "/configuracion",
    claves: "integraciones conectar whatsapp odoo excel correo stripe shopify",
  },
  {
    href: "/configuracion?seccion=ia",
    label: "Tu IA",
    puerta: "/configuracion",
    claves: "proveedor de ia inteligencia claude chatgpt openai llave modelo",
  },
  {
    href: "/configuracion?seccion=telefono",
    label: "Teléfono y equipo",
    puerta: "/configuracion",
    claves: "aparatos tus aparatos iphone celular colaboradores codigo qr",
  },

  // ── Sin renglón propio: se entra por un botón de otra pantalla ────────────
  {
    href: "/rutinas",
    label: "Portales",
    puerta: "/ayudantes",
    claves: "rutinas navegador portal",
  },
  {
    href: "/actividad",
    label: "Actividad",
    puerta: "/",
    claves: "enviado todo lo enviado historial bitacora",
  },
  // Tiene dos puertas (Conexiones para el Excel, Cartera > Pagos para el estado de
  // cuenta), así que no enciende ninguna.
  {
    href: "/importar",
    label: "Importar",
    puerta: null,
    claves: "importar datos excel csv subir archivo estado de cuenta",
  },
  {
    href: "/manual/index.html",
    label: "Manual",
    puerta: null,
    fuera: true,
    claves: "ayuda instrucciones documentacion como se usa problemas",
  },
];

// Rutas viejas que siguen vivas como redirección, y detalles: bajo qué puerta caen
// mientras están en pantalla, para que el menú nunca se quede sin marca a medio
// camino. Lo que no es redirección ni detalle se resuelve por prefijo, abajo.
const PUERTA_DE_RUTA: Record<string, string> = {
  "/centro": "/",
  "/aprobaciones": "/",
  "/promesas": "/facturas",
  "/conciliacion": "/facturas",
  "/integraciones": "/configuracion",
  "/proveedor": "/configuracion",
  "/aparatos": "/configuracion",
};

const sinQuery = (href: string) => href.split("?")[0];

/** Quita la diagonal final (el export estático puede servir `/facturas/`). */
function limpia(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

/** El renglón del menú que se enciende en esta ruta, o `null` si ninguno.
 *  Cubre hijas (`/clientes/detalle`), pestañas (`/facturas?vista=pagos` es la misma
 *  ruta) y redirecciones (`/proveedor`). */
export function puertaDe(pathname: string): string | null {
  const p = limpia(pathname);
  const exacto = DESTINOS.find((d) => d.href === p);
  if (exacto) return exacto.puerta;
  // Del más largo al más corto: `/integraciones/detalle` cae en `/integraciones`.
  const partes = p.split("/").filter(Boolean);
  for (let n = partes.length; n > 0; n--) {
    const base = "/" + partes.slice(0, n).join("/");
    if (base in PUERTA_DE_RUTA) return PUERTA_DE_RUTA[base];
    const d = DESTINOS.find((x) => x.href === base);
    if (d) return d.puerta;
  }
  return null;
}

/** ¿Hay algún ayudante que haga este oficio? Las aiuditas se llaman
 *  `oficio.tarea` (`ventas.generar_cotizacion`), así que basta el prefijo de las
 *  que tiene puestas. Recibe la lista de `useAyudantes()`. */
function hayOficio(
  ayudantes: { aiuditas: Record<string, unknown> }[],
  oficio: Oficio,
): boolean {
  return ayudantes.some((a) => Object.keys(a.aiuditas ?? {}).some((id) => id.startsWith(`${oficio}.`)));
}

/** Oficios presentes, listos para pasar a `menu()` y `destinos()`. */
export function oficiosDe(ayudantes: { aiuditas: Record<string, unknown> }[]): Oficio[] {
  return (["ventas", "recepcion"] as const).filter((o) => hayOficio(ayudantes, o));
}

const visible = (d: Destino, oficios: readonly Oficio[]) => !d.si || oficios.includes(d.si);

/** Los renglones del menú, en orden. */
export function menu(oficios: readonly Oficio[] = []): Destino[] {
  return DESTINOS.filter((d) => d.menu && visible(d, oficios));
}

/** Todo lo alcanzable, para el buscador. */
export function destinos(oficios: readonly Oficio[] = []): Destino[] {
  return DESTINOS.filter((d) => visible(d, oficios));
}

/** El nombre de la puerta de un destino ("Cartera" para Pagos), o "" si es él
 *  mismo un renglón del menú o no tiene puerta. Le da contexto en el buscador. */
export function dentroDe(d: Destino): string {
  if (!d.puerta || d.menu) return "";
  return DESTINOS.find((x) => x.menu && x.href === d.puerta)?.label ?? "";
}

// Nombre de cada ruta para el Rastro ("Volver a Cartera"). Sale de DESTINOS; las
// redirecciones heredan el nombre de su puerta por si alcanzan a pintarse.
export const SECTION_LABELS: Record<string, string> = (() => {
  const out: Record<string, string> = {};
  for (const d of DESTINOS) {
    if (d.fuera || d.href.includes("?")) continue;
    out[d.href] = d.label;
  }
  for (const [ruta, puerta] of Object.entries(PUERTA_DE_RUTA)) {
    out[ruta] = out[puerta] ?? "";
  }
  return out;
})();

// Rutas donde el Rastro vuelve a empezar: los renglones del menú y las
// redirecciones que desembocan en ellos. Entrar por el menú es empezar de nuevo.
// Portales, SAT, Importar y Actividad NO están aquí a propósito: no tienen renglón,
// así que conservan su "Volver a…" hacia la pantalla desde la que se entró.
const REINICIA = new Set<string>([
  ...DESTINOS.filter((d) => d.menu).map((d) => sinQuery(d.href)),
  ...Object.keys(PUERTA_DE_RUTA),
]);

export function isSection(href: string): boolean {
  return REINICIA.has(limpia(href));
}
