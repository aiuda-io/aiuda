"use client";

// "Inyectar a {destino}": empuja un registro que vive en aiuda hacia el maestro
// elegido (Odoo, Google Calendar o una conexión a la medida que escribe). Solo
// aparece si HOY hay destinos que reciben la entidad Y el registro no vive ya
// allá (presence); con varios destinos, un menú simple. El encolado es honesto:
// el write-back lo escribe en segundo plano y su estado se ve en la ficha.

import { useEffect, useRef, useState } from "react";
import { api, type EntidadInyectable, type InyectarDestino } from "@/lib/api";
import { toast } from "@/components/toast";

export function InyectarButton({
  entidad,
  id,
  presence,
  onQueued,
  small,
}: {
  entidad: EntidadInyectable;
  id: string;
  /** Dónde vive ya el registro: se ocultan esos destinos (no se re-inyecta). */
  presence?: Record<string, unknown> | null;
  /** Tras encolar: recarga writeback-status / la ficha. */
  onQueued?: () => void;
  /** Talla chica para convivir con los botones del encabezado de la ficha. */
  small?: boolean;
}) {
  const [destinos, setDestinos] = useState<InyectarDestino[]>([]);
  const [busy, setBusy] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .inyectarDestinos()
      .then((d) => setDestinos(d[entidad] ?? []))
      .catch(() => setDestinos([]));
  }, [entidad]);

  useEffect(() => {
    if (!abierto) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [abierto]);

  // La presencia de una conexión a la medida usa el NOMBRE que le puso el dueño
  // (su label); la de un conector nativo, su key (odoo, googlecalendar).
  const viveEn = (d: InyectarDestino) =>
    d.target === "custom" ? d.label in (presence ?? {}) : d.target in (presence ?? {});
  const opciones = destinos.filter((d) => !viveEn(d));

  if (opciones.length === 0) return null;

  async function ir(d: InyectarDestino) {
    setBusy(true);
    setAbierto(false);
    try {
      await api.inyectar({ entidad, id, target: d.target, conexion_id: d.conexion_id });
      toast(`Inyección encolada: viajando a ${d.label}.`, "success");
      onQueued?.();
    } catch (e) {
      // 409 (ya vive allá) / 422 (la conexión no escribe): detail legible tal cual.
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const cls = `rounded-md border border-line bg-surface font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50 ${
    small ? "px-2 py-0.5 text-apoyo" : "px-3 py-1.5 text-cuerpo"
  }`;

  if (opciones.length === 1) {
    return (
      <button onClick={() => ir(opciones[0])} disabled={busy} className={cls}>
        {busy ? "Encolando…" : `Inyectar a ${opciones[0].label}`}
      </button>
    );
  }

  return (
    <div ref={menuRef} className="relative inline-block">
      <button onClick={() => setAbierto((a) => !a)} disabled={busy} className={cls}>
        {busy ? "Encolando…" : "Inyectar a…"}
      </button>
      {abierto && (
        <ul className="absolute left-0 z-20 mt-1 min-w-44 overflow-hidden rounded-md border border-line bg-surface shadow-[0_8px_24px_rgba(13,45,62,0.12)]">
          {opciones.map((d) => (
            <li key={`${d.target}-${d.conexion_id ?? ""}`}>
              <button
                onClick={() => ir(d)}
                className="w-full px-3 py-2 text-left text-cuerpo text-ink transition-colors hover:bg-panel/50"
              >
                {d.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
