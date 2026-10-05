import Link from "next/link";

// La página para una dirección que no existe. Sin este archivo Next pone la suya,
// en inglés ("This page could not be found"), y es lo que veía el dueño al abrir
// un enlace viejo o mal escrito.
export default function NoEncontrada() {
  return (
    <div className="max-w-md py-10">
      <h1 className="text-seccion font-semibold tracking-tight text-ink">
        Esta página no existe
      </h1>
      <p className="mt-2 text-cuerpo leading-relaxed text-ink-2">
        La dirección está mal escrita o esa pantalla ya no está en aiuda. Tus datos siguen
        donde estaban.
      </p>
      <Link
        href="/"
        className="mt-4 inline-block rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong"
      >
        Ir al Resumen
      </Link>
    </div>
  );
}
