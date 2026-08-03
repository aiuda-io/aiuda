"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Evento que dispara Configuración al prender/apagar el modo sombra, para que el
// banner se actualice sin recargar.
export const SHADOW_EVENT = "shadow-mode-changed";

// Franja persistente mientras el modo sombra está activo: deja claro que NADA sale a
// clientes reales (semana de validación con datos reales). Se apaga en Configuración.
export function ShadowBanner() {
  const [on, setOn] = useState(false);

  useEffect(() => {
    api
      .shadowMode()
      .then((s) => setOn(!!s.modo_sombra))
      .catch(() => {});
    const handler = (e: Event) => setOn(!!(e as CustomEvent<{ activo: boolean }>).detail?.activo);
    window.addEventListener(SHADOW_EVENT, handler);
    return () => window.removeEventListener(SHADOW_EVENT, handler);
  }, []);

  if (!on) return null;

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-line-strong bg-panel px-4 py-1.5 text-center text-cuerpo text-ink-2">
      <span className="font-semibold text-ink">Modo sombra activo.</span>
      <span>Tu ayudante redacta y deja todo en Aprobaciones, pero no envía nada a clientes reales.</span>
    </div>
  );
}
