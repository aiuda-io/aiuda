/* Layout de página "primario + riel de contexto".
 *
 * El patrón de casi toda vista de datos de la consola: el contenido principal
 * (tabla, lista) a la izquierda usando el ancho, y un riel de contexto a la
 * derecha con resumen o atajos derivados de los MISMOS datos — nunca una columna
 * centrada flotando con espacio muerto a los lados.
 *
 * Estos primitivos son la única forma de armar ese layout, para no repetir el grid
 * ni el estilo del riel en cada página. Agregar una vista nueva es declarativo:
 *
 *   <RailLayout rail={
 *     <RailSection label="Cartera">
 *       <RailStat label="Por cobrar" value={mxn(total)} strong />
 *     </RailSection>
 *   }>
 *     <MiTabla />
 *   </RailLayout>
 *
 * Sin `rail`, el contenido usa el ancho completo (mismo contenedor, sin grid).
 */
import type { ReactNode } from "react";

export function RailLayout({
  children,
  rail,
  sticky,
}: {
  children: ReactNode;
  rail?: ReactNode;
  // `sticky` fija el riel mientras el contenido principal hace scroll (p.ej. un
  // panel de despacho junto a un registro de actividad largo).
  sticky?: boolean;
}) {
  if (!rail) return <div className="min-w-0">{children}</div>;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_296px]">
      <div className="min-w-0">{children}</div>
      <aside
        className={`reveal hidden space-y-6 lg:block${sticky ? " lg:sticky lg:top-4 lg:self-start" : ""}`}
      >
        {rail}
      </aside>
    </div>
  );
}

/** Un bloque del riel: etiqueta en versalitas + su contenido (stats o lista). */
export function RailSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section>
      <RailLabel>{label}</RailLabel>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function RailLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">{children}</p>
  );
}

/** Renglón "etiqueta … valor" para un resumen. `strong` resalta la cifra titular. */
export function RailStat({
  label,
  value,
  strong,
  hint,
}: {
  label: string;
  value: string;
  strong?: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-line/50 pb-2 last:border-0">
      <span className="text-[12px] text-ink-3">
        {label}
        {hint && <span className="block text-[11px] text-ink-3/80">{hint}</span>}
      </span>
      <span
        className={`tnum shrink-0 ${strong ? "text-[14px] font-semibold text-ink" : "text-[12.5px] font-medium text-ink-2"}`}
      >
        {value}
      </span>
    </div>
  );
}

/** Renglón de una lista del riel (ranking, próximos): contenido libre, divisor abajo. */
export function RailRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line/50 py-2 last:border-0">
      {children}
    </div>
  );
}
