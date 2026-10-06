// Lo que comparten las pantallas de Cartera (Facturas, Promesas, Pagos, el panel de la
// factura, SAT e Importar): dinero en SU moneda, totales que no mezclan monedas, y las
// rutas a las que se manda al dueño cuando algo se arregla en otro lado.

import { ApiError } from "@/lib/api";

const MONEDA_BASE = "MXN";

/** A dónde se manda al dueño (rutas del contrato del paquete B). */
export const RUTA = {
  hoy: "/",
  cartera: "/facturas",
  promesas: "/facturas?vista=promesas",
  pagos: "/facturas?vista=pagos",
  sat: "/sat",
  importar: "/importar",
  ia: "/configuracion?seccion=ia",
  conexiones: "/configuracion?seccion=conexiones",
  portales: "/rutinas",
} as const;

function moneda(codigo?: string | null): string {
  return (codigo ?? "").trim().toUpperCase() || MONEDA_BASE;
}

/** Dinero en su moneda. Pesos sale "$1,234.00"; cualquier otra lleva su código por
 *  delante ("USD 1,234.00"), para que nunca se lea como pesos. */
export function dinero(valor: number, codigo?: string | null): string {
  const m = moneda(codigo);
  try {
    return valor.toLocaleString("es-MX", { style: "currency", currency: m });
  } catch {
    // Un código que el navegador no conoce: el número con su código, sin inventar símbolo.
    return `${m} ${valor.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

const NOMBRE_MONEDA: Record<string, string> = { MXN: "pesos", USD: "dólares", EUR: "euros" };

/** "pesos", "dólares"; un código sin nombre conocido se queda como código. */
export function nombreMoneda(codigo?: string | null): string {
  const m = moneda(codigo);
  return NOMBRE_MONEDA[m] ?? m;
}

export type TotalMoneda = { moneda: string; total: number; count: number };

/** Suma por moneda, sin mezclar. Pesos primero si hay; el resto, la que más registros
 *  tenga. La primera es "la principal": la cifra grande de la pantalla. */
export function totalesPorMoneda<T>(
  items: T[],
  monto: (item: T) => number,
  codigo: (item: T) => string | null | undefined,
): TotalMoneda[] {
  const m = new Map<string, TotalMoneda>();
  for (const item of items) {
    const k = moneda(codigo(item));
    const t = m.get(k) ?? { moneda: k, total: 0, count: 0 };
    t.total += monto(item);
    t.count += 1;
    m.set(k, t);
  }
  return [...m.values()].sort((a, b) => {
    if (a.moneda === MONEDA_BASE) return -1;
    if (b.moneda === MONEDA_BASE) return 1;
    return b.count - a.count || a.moneda.localeCompare(b.moneda);
  });
}

/** Varias cifras en una frase: "$1,200.00 y USD 300.00". Sin registros, cero pesos. */
export function dineroPorMoneda(totales: TotalMoneda[]): string {
  if (totales.length === 0) return dinero(0);
  return totales.map((t) => dinero(t.total, t.moneda)).join(" y ");
}

export function plural(n: number, uno: string, varios: string): string {
  return `${n} ${n === 1 ? uno : varios}`;
}

/** El color del punto de cada tramo de antigüedad (va solo en la marca). */
export const TRAMO_MARCA: Record<string, string> = {
  por_vencer: "var(--color-line-strong)",
  vence_pronto: "var(--color-accent)",
  vencida_reciente: "var(--color-warn)",
  vencida: "var(--color-warn-strong)",
  critica: "var(--color-danger)",
};

/** Atraso dicho con palabras: "12 días de atraso", "Vence hoy", "Vence en 5 días". */
export function atraso(dias: number): string {
  if (dias > 0) return `${plural(dias, "día", "días")} de atraso`;
  if (dias === 0) return "Vence hoy";
  return `Vence en ${plural(-dias, "día", "días")}`;
}

// ── Errores: reconocer el caso por su código, no por su texto ────────────────

export type Fallo = {
  mensaje: string;
  /** Lo que falta es conectar la IA (o la que hay no respondió): se arregla en Tu IA. */
  ia: boolean;
  /** Falta algo, no se rompió nada: se pinta como aviso, no como error. */
  aviso: boolean;
};

/** Un error de la API listo para pintarse. El texto ya viene en español del server;
 *  aquí solo se decide cómo se pinta y si lleva la liga a Tu IA. */
export function leerFallo(e: unknown): Fallo {
  const code = e instanceof ApiError ? e.code : undefined;
  if (code === "ia_no_conectada") {
    return { mensaje: "Falta conectar tu IA.", ia: true, aviso: true };
  }
  const mensaje = e instanceof Error && e.message && !/^Error \d+$/.test(e.message)
    ? e.message
    : "No se pudo completar. Inténtalo de nuevo.";
  return { mensaje, ia: code === "ia_fallo", aviso: code === "ia_tope" };
}
