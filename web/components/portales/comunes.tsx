// Lo que comparten las piezas de Portales: tipos, las palabras de cada estado y un par
// de íconos.
import type { CuaCapacidad, CuaMision } from "@/lib/api";

/** Un portal como lo manda el servidor. `del_dueno`: lo registró él, o le puso
 *  dirección o acceso a uno de fábrica. Los de fábrica sin tocar solo se han corrido
 *  contra portales de prueba y no se le enseñan. */
export type Portal = CuaCapacidad & { del_dueno?: boolean };

/** Estado de un encargo, con el color de su marca y si sigue vivo (en cola o
 *  trabajando: se refresca solo). */
export const ESTADO: Record<CuaMision["status"], { label: string; marca: string; vivo: boolean }> = {
  queued: { label: "En cola", marca: "var(--color-ink-3)", vivo: true },
  running: { label: "Adentro del portal", marca: "var(--color-accent)", vivo: true },
  done: { label: "Trajo el resultado", marca: "var(--color-ok)", vivo: false },
  failed: { label: "No pudo", marca: "var(--color-danger)", vivo: false },
};

export function Marca({ color, children }: { color?: string; children: React.ReactNode }) {
  return (
    <span className="mark" style={color ? ({ "--mark": color } as React.CSSProperties) : undefined}>
      {children}
    </span>
  );
}

export const instruccionDe = (m: CuaMision): string | null =>
  typeof m.data?._instruccion === "string" && m.data._instruccion ? m.data._instruccion : null;

/** La fecha más avanzada que tenga un encargo. */
export const cuandoFue = (m: CuaMision): string | null => m.finishedAt || m.startedAt || m.createdAt;

/** Una dirección legible: sin el https:// ni colas larguísimas. */
export function urlBonita(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname;
    return `${u.host}${path}`.replace(/\/$/, "").slice(0, 46);
  } catch {
    return url.slice(0, 46);
  }
}
