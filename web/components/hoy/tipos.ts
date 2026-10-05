import { type PromiseItem, type ReconcileItem, type ReminderItem } from "@/lib/api";

/** Un mensaje redactado por un ayudante (recordatorio, cotización, respuesta de
 *  correo), con lo que el server le agrega para Hoy. */
export type Mensaje = ReminderItem & {
  /** Cuenta en "Por aprobar": la regla vive en el server (`_recordatorio_pide_decision`). */
  pide_decision?: boolean;
  /** null = no va ligado a una factura. */
  factura_abierta?: boolean | null;
  /** Cuándo cambió de estado por última vez. */
  updated_at?: string | null;
};

/** Las tres formas de renglón de "Por aprobar". */
export type Renglon =
  | { clase: "mensaje"; id: string; mensaje: Mensaje }
  | { clase: "pago"; id: string; pago: ReconcileItem }
  | { clase: "promesa"; id: string; promesa: PromiseItem };

/** Corre una acción contra el server, avisa lo que DE VERDAD pasó y refresca.
 *  `saleId` es el renglón que debe salir de la lista si todo salió bien. */
export type Ejecutar = <T>(
  fn: () => Promise<T>,
  ok: string | ((res: T) => string),
  saleId?: string,
) => Promise<boolean>;

export const idMensaje = (m: Mensaje) => `r-${m.id}`;
export const idPago = (p: ReconcileItem) => `c-${p.id}`;
export const idPromesa = (p: PromiseItem) => `p-${p.id}`;

export const esCotizacion = (m: Mensaje) => m.bucket === "cotizacion";
export const esCorreo = (m: Mensaje) => m.bucket === "respuesta_correo";

/** Qué es, en una palabra del dueño. */
export function claseDe(m: Mensaje): string {
  return esCotizacion(m) ? "Cotización" : esCorreo(m) ? "Respuesta de correo" : "Recordatorio";
}

export function nombreDe(m: Mensaje): string {
  return m.customer ?? m.title ?? "Sin nombre";
}

/** A quién le llega: el correo del hilo, el teléfono del cliente, o nada si falta. */
export function destinatarioDe(m: Mensaje): string | null {
  return m.correo?.para ?? m.customer_phone ?? null;
}

/** El canal por el que saldría si se aprueba sin elegir otro. */
export function canalPorDefecto(m: Mensaje): string {
  return m.channels.find((c) => c.connected)?.key ?? m.channel ?? "whatsapp";
}

export function etiquetaCanal(m: Mensaje, key: string): string {
  return m.channels.find((c) => c.key === key)?.label ?? "WhatsApp";
}

/** Un instante que manda el server, como fecha de verdad.
 *
 *  El server guarda en UTC y SQLite no conserva la zona, así que la hora llega sin
 *  ella ("2026-10-05T16:11:08"). Leída tal cual, el navegador la toma como hora local
 *  y en México queda seis horas adelantada: "enviado hace un momento" para algo de
 *  hace dos horas, y lo enviado en la tarde ya no cuenta como de hoy. */
export function instante(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const conZona = /T/.test(iso) && !/(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? `${iso}Z` : iso;
  const d = new Date(conZona);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function esDeHoy(iso: string | null | undefined): boolean {
  const d = instante(iso);
  return d !== null && d.toDateString() === new Date().toDateString();
}

/** "hace 20 min", "hace 2 h", "hace 3 d". */
export function haceRato(iso: string | null | undefined): string {
  const d = instante(iso);
  if (!d) return "";
  const mins = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  if (mins < 1) return "hace un momento";
  if (mins < 60) return `hace ${mins} min`;
  if (mins < 60 * 24) return `hace ${Math.floor(mins / 60)} h`;
  return `hace ${Math.floor(mins / (60 * 24))} d`;
}

/** "5 oct, 10:11": día y hora en la zona de quien mira. */
export function diaYHora(iso: string | null | undefined): string {
  const d = instante(iso);
  if (!d) return "";
  return d.toLocaleString("es-MX", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** ¿El texto pasa de lo que cabe a la vista sin expandir? */
export function esLargo(texto: string): boolean {
  return texto.length > 320 || texto.split("\n").length > 5;
}
