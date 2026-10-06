// Las secciones de Ajustes y sus direcciones (`/configuracion?seccion=…`).

/** Las cuatro secciones de Ajustes, por query (`/configuracion?seccion=…`). */
export const SECCIONES = [
  { key: "negocio", label: "Negocio" },
  { key: "conexiones", label: "Conexiones" },
  { key: "ia", label: "Tu IA" },
  { key: "telefono", label: "Teléfono y equipo" },
] as const;

export type Seccion = (typeof SECCIONES)[number]["key"];

/** La dirección de una sección de Ajustes. `abrir` deja abierto el panel de una
 *  conexión (solo tiene sentido en Conexiones). */
export function rutaAjustes(seccion: Seccion, abrir?: string): string {
  const q = new URLSearchParams();
  if (seccion !== "negocio") q.set("seccion", seccion);
  if (abrir) q.set("abrir", abrir);
  const cola = q.toString();
  return cola ? `/configuracion?${cola}` : "/configuracion";
}
