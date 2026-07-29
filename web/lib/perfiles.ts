// Helpers de perfil (Cobranza, Ventas…) compartidos por la ficha del ayudante y el
// picker de aiuditas. Antes estaban copiados en cada archivo; una sola fuente.

import type { AiuditaConfig, AiuditasCatalog, PerfilSpec } from "@/lib/api";
import { ACCENT_COLORS, appearanceForSlug } from "@/lib/look";

/** Color de identidad del perfil (Cobranza, Ventas…): reusa la paleta de los
 *  ayudantes para que cada área se sienta propia y se agrupe de un vistazo. */
export function perfilColor(perfil: string): string {
  return ACCENT_COLORS[appearanceForSlug(perfil).color] ?? ACCENT_COLORS[0];
}

/** Perfiles con al menos una aiudita activa: definen el "rol" del ayudante en una
 *  línea (encabezado de la ficha, chips de la tarjeta). `activos` es el mapa de
 *  aiuditas equipadas del ayudante (`ayudante.aiuditas`). */
export function perfilesActivos(
  catalog: AiuditasCatalog,
  activos: Record<string, AiuditaConfig>,
): PerfilSpec[] {
  return catalog.perfiles.filter((p) =>
    catalog.aiuditas.some((a) => a.perfil === p.slug && a.id in activos),
  );
}
