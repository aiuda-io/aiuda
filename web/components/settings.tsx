import type { ReactNode } from "react";

/**
 * Patrón de página de ajustes moderno (Linear/Vercel/Stripe): el título y la explicación
 * de cada bloque van a la izquierda; el control, a la derecha. Llena el ancho con estructura
 * en vez de dejar una columna angosta flotando con la mitad derecha vacía. Secciones
 * separadas por una línea fina, con aire vertical generoso.
 */
export function SettingsSection({
  title,
  desc,
  ancho,
  children,
}: {
  title: string;
  desc?: ReactNode;
  /** El contenido es una lista o una tabla y usa todo el ancho de la columna. Sin
   *  esto la columna se queda en medida de lectura, que es lo que piden un
   *  formulario y un texto corrido. */
  ancho?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-x-16 gap-y-5 border-t border-line py-10 first:border-t-0 first:pt-0 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
      <div>
        <h2 className="text-seccion font-semibold text-ink">{title}</h2>
        {desc && <div className="mt-1.5 text-cuerpo text-ink-2">{desc}</div>}
      </div>
      <div className={`min-w-0 ${ancho ? "" : "max-w-2xl"}`}>{children}</div>
    </section>
  );
}

/** Etiqueta + ayuda encima de un control, para apilar campos en la columna derecha. */
export function SettingsField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="block text-cuerpo font-semibold text-ink">{label}</label>
      {hint && <p className="text-apoyo text-ink-3">{hint}</p>}
      {children}
    </div>
  );
}

/** Contenedor de una página de ajustes. No define ancho: hereda el de la consola
 *  (`ANCHO_CONTENIDO` en components/shell.tsx), como cualquier otra pantalla. Lo
 *  que se acota es el texto corrido y los campos, en `SettingsSection`. */
export function SettingsPage({ children }: { children: ReactNode }) {
  return <div className="min-w-0">{children}</div>;
}
