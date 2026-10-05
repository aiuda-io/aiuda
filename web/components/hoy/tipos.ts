import { type PromiseItem, type ReconcileItem, type ReminderItem } from "@/lib/api";

/** Un mensaje redactado por un ayudante (recordatorio, cotización, respuesta de
 *  correo). Es el `ReminderItem` del API con el nombre que le da Hoy. */
export type Mensaje = ReminderItem;

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

/** ¿El texto pasa de lo que cabe a la vista sin expandir? */
export function esLargo(texto: string): boolean {
  return texto.length > 320 || texto.split("\n").length > 5;
}
