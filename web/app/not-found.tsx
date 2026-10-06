"use client";

import { PrimaryLink } from "@/components/ui";
import { useSinRegreso } from "@/components/rastro";

// La página para una dirección que no existe. Sin este archivo Next pone la suya,
// en inglés ("This page could not be found"), y es lo que veía el dueño al abrir
// un enlace viejo o mal escrito. Vive dentro del marco: el menú sigue ahí.
export default function NoEncontrada() {
  // Una sola salida: el botón de abajo. El "Volver a Hoy" del marco decía lo mismo
  // encima de él.
  useSinRegreso();
  return (
    <div className="max-w-md pt-10">
      <h1 className="text-titulo font-semibold text-ink">Esta pantalla no existe</h1>
      <p className="mt-3 text-cuerpo text-ink-2">
        La dirección está mal escrita o esa pantalla ya no está en aiuda. Tus datos siguen
        donde estaban.
      </p>
      <div className="mt-8">
        <PrimaryLink href="/">Ir a Hoy</PrimaryLink>
      </div>
    </div>
  );
}
