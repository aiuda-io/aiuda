import type { ReactNode } from "react";
import { inputCls } from "@/components/ui";

/**
 * Patrón de página de ajustes moderno (Linear/Vercel/Stripe): el título y la explicación
 * de cada bloque van a la izquierda; el control, a la derecha. Llena el ancho con estructura
 * en vez de dejar una columna angosta flotando con la mitad derecha vacía. Secciones
 * separadas por una línea fina, con aire vertical generoso.
 */
export function SettingsSection({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-x-10 gap-y-4 border-t border-line py-7 first:border-t-0 first:pt-0 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
      <div>
        <h2 className="text-seccion font-semibold text-ink">{title}</h2>
        {desc && <div className="mt-1.5 text-cuerpo text-ink-2">{desc}</div>}
      </div>
      <div className="min-w-0 max-w-2xl">{children}</div>
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
    <div className="space-y-1.5">
      <label className="block text-cuerpo font-semibold text-ink">{label}</label>
      {hint && <p className="text-apoyo text-ink-3">{hint}</p>}
      {children}
    </div>
  );
}

/** Contenedor de una página de ajustes: ancho cómodo, centrado, con aire. */
export function SettingsPage({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-5xl">{children}</div>;
}

/** El input canónico ahora vive en components/ui (`inputCls` / `<TextInput>`). Este
 *  alias mantiene el mismo estilo desde el primitivo compartido y evita romper a los
 *  importadores; migrar al primitivo directo cuando se toquen esos archivos. */
export const settingsInputCls = inputCls;
