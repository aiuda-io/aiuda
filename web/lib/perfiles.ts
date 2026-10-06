// Helpers de perfil (Cobranza, Ventas…) compartidos por la lista de ayudantes y la
// ficha de cada uno.

import type { AiuditaConfig, AiuditasCatalog, PerfilSpec } from "@/lib/api";

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
