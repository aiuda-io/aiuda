"use client";

import { useState } from "react";
import { api, type ExportEntidad } from "@/lib/api";
import { toast } from "@/components/toast";
import { SecondaryButton } from "@/components/ui";

/** Baja la lista como Excel con los filtros activos de la página. aiuda no es el
 *  sistema maestro: tus datos salen completos, en un xlsx que se puede re-importar
 *  tal cual (los encabezados son los campos que el importador entiende). */
export function ExportButton({
  entidad,
  filtros,
  count,
}: {
  entidad: ExportEntidad;
  filtros?: Record<string, string | null | undefined>;
  /** Registros visibles: con 0 el botón no se muestra (nada que exportar). */
  count?: number;
}) {
  const [descargando, setDescargando] = useState(false);
  if (count === 0) return null;

  const descargar = async () => {
    setDescargando(true);
    try {
      const blob = await api.exportXlsx(entidad, filtros);
      const d = new Date();
      const fecha = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${entidad}-${fecha}.xlsx`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast(`No se pudo exportar: ${(e as Error).message}`, "error");
    } finally {
      setDescargando(false);
    }
  };

  return (
    <SecondaryButton onClick={descargar} disabled={descargando}>
      {descargando ? "Descargando…" : "Exportar a Excel"}
    </SecondaryButton>
  );
}
